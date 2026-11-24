#!/usr/bin/env bash
# Prepare a fresh Ubuntu server for PTO-Hacker.
#
#   curl -fsSLO https://raw.githubusercontent.com/<you>/pto-hacker/main/scripts/ubuntu_setup.sh
#   less ubuntu_setup.sh          # read it before running it
#   sudo bash ubuntu_setup.sh
#
# Installs Docker from Docker's own apt repo, sets the timezone, adds swap if
# there is none, enables the firewall (SSH first), and turns on security
# updates. It does NOT clone the repo or start the app -- it prints those steps
# at the end so you stay in control of them.
#
# Safe to re-run: every step checks before acting.
# Written for Ubuntu 22.04 / 24.04. Syntax-checked, but NOT yet run on a
# real server -- read it through before trusting it with your box.
set -euo pipefail

TZ_WANTED="${TZ_WANTED:-Asia/Kolkata}"
SWAP_SIZE="${SWAP_SIZE:-1G}"
TARGET_USER="${SUDO_USER:-${USER:-root}}"

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[32mok\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!!\033[0m %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
  warn "This is written for Ubuntu. Continuing anyway in 5s (Ctrl-C to stop)."
  sleep 5
fi
. /etc/os-release
say "Ubuntu ${VERSION_ID:-unknown} · user ${TARGET_USER}"

# ---------------------------------------------------------------- packages
say "Updating package lists"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg git ufw sqlite3 >/dev/null
ok "base packages present"

# ------------------------------------------------------------------- time
say "Timezone"
if [ "$(timedatectl show -p Timezone --value)" = "$TZ_WANTED" ]; then
  ok "already $TZ_WANTED"
else
  timedatectl set-timezone "$TZ_WANTED"
  ok "set to $TZ_WANTED"
fi
echo "    (the worker schedules by local time, so this decides when your digest arrives)"

# ------------------------------------------------------------------- swap
say "Swap"
if [ "$(swapon --show --noheadings | wc -l)" -gt 0 ]; then
  ok "swap already active"
elif [ -f /swapfile ]; then
  warn "/swapfile exists but is not active; leaving it alone"
else
  fallocate -l "$SWAP_SIZE" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "created $SWAP_SIZE swap (a 1 GB box can be OOM-killed without it)"
fi

# ----------------------------------------------------------------- docker
say "Docker"
if command -v docker >/dev/null 2>&1; then
  ok "already installed: $(docker --version)"
else
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin >/dev/null
  ok "installed $(docker --version)"
fi

systemctl enable --now docker >/dev/null 2>&1 || true
if [ "$(systemctl is-enabled docker 2>/dev/null)" = "enabled" ]; then
  ok "docker starts at boot — this is what makes restart policies survive a reboot"
else
  warn "docker is NOT enabled at boot; containers will not come back after a reboot"
fi

if [ "$TARGET_USER" != "root" ]; then
  if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx docker; then
    ok "$TARGET_USER already in the docker group"
  else
    usermod -aG docker "$TARGET_USER"
    ok "added $TARGET_USER to the docker group"
    warn "log out and back in for that to take effect"
    warn "note: docker group access is equivalent to root on this box"
  fi
fi

# --------------------------------------------------------------- firewall
say "Firewall"
# SSH first, always. Enabling ufw without it locks you out of your own server.
ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
if ufw status | head -1 | grep -q inactive; then
  ufw --force enable >/dev/null
  ok "enabled, with SSH allowed first"
else
  ok "already active"
fi
echo "    8501 is deliberately closed: the app binds 127.0.0.1 and only Caddy is public."
ufw status | sed 's/^/    /'

# -------------------------------------------------------- security updates
say "Unattended security upgrades"
apt-get install -y -qq unattended-upgrades >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
ok "enabled"

# ----------------------------------------------------------------- summary
say "Ready"
cat <<EOF

  Next steps, as ${TARGET_USER} rather than root:

    git clone <your-repo-url> ~/pto-hacker
    cd ~/pto-hacker
    cp .env.example .env
    nano .env          # TZ, Telegram token + chat id, and PTO_DOMAIN if public

  No domain yet? Run it private and reach it over an SSH tunnel:

    docker compose up -d --build
    # then, from your laptop:
    ssh -L 8501:localhost:8501 ${TARGET_USER}@<this-server-ip>
    # and open http://localhost:8501 in your own browser

  With a domain pointed at this server:

    docker compose --profile public up -d --build
    # https://your-domain, behind basic auth

  Check it from the command line (there is no browser here):

    curl -I http://127.0.0.1:8501/_stcore/health
    docker compose ps
    docker compose logs -f worker
    docker compose exec worker python daemon.py --list
    docker compose exec worker python daemon.py --job digest   # test Telegram

EOF
