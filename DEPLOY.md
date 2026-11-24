# Running and deploying PTO-Hacker

Two paths: run it on your laptop, or put it on a VPS of your own. Both assume
you have cloned this repo.

---

## 1. Run it locally

**Requirements:** Python 3.10 or newer. Nothing else — no API keys, no database
server, no network access at runtime.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Open <http://localhost:8501>. A SQLite database is created at `output/pto.db` on
first run; everything you enter is kept there.

Check it works:

```bash
python smoke_test.py    # the planning engine, end to end
python store_test.py    # persistence, against a throwaway database
```

On Windows, prefix both with `PYTHONIOENCODING=utf-8` — the console is cp1252 and
the test output contains en-dashes.

### With Docker instead

```bash
docker compose up -d --build
```

Same URL. The database lives in a named volume (`pto-data`), so rebuilding the
image does not touch your data.

---

## 2. Deploy to your own VPS

A 1 GB / 1 vCPU box is plenty. Written for Ubuntu 22.04 / 24.04, CLI only —
no desktop, no browser on the machine.

### Fresh Ubuntu box: one script

On a bare Ubuntu 22.04 / 24.04 server with nothing installed:

```bash
# read it first, then run it
curl -fsSLO https://raw.githubusercontent.com/<you>/pto-hacker/main/scripts/ubuntu_setup.sh
less ubuntu_setup.sh
sudo bash ubuntu_setup.sh
```

It installs Docker from Docker's own apt repository, enables it at boot, sets the
timezone, adds a swapfile if there is none, turns on `ufw` **allowing SSH first**,
and enables unattended security upgrades. Every step checks before acting, so it
is safe to re-run. It deliberately stops short of cloning or starting anything.

Log out and back in afterwards so your docker group membership applies.

> Not yet run on a real server — it is syntax-checked only. Read it before
> trusting it with your box.

### No browser on the server

An Ubuntu CLI VPS has no way to open `localhost:8501`. Two options.

**Before you have a domain** — tunnel it to your own machine:

```bash
docker compose up -d --build                      # on the server
ssh -L 8501:localhost:8501 user@your-server-ip    # from your laptop
# open http://localhost:8501 in your laptop's browser
```

Nothing is exposed publicly; the traffic rides your SSH session.

**Checking it from the server itself**, with curl rather than eyes:

```bash
curl -I http://127.0.0.1:8501/_stcore/health   # expect HTTP/1.1 200 OK
docker compose ps                              # both services Up
docker compose logs --tail=50 worker
docker compose exec worker python daemon.py --list
```

### What you need for the public path

- A domain name with an **A record already pointing at that IP** — Caddy needs
  this to get a TLS certificate
- Ports **80** and **443** open at the provider's firewall as well as in `ufw`
  (cloud providers usually have their own security group on top)

### Steps

```bash
# 1. Get the code
git clone <your-repo-url> pto-hacker
cd pto-hacker

# 2. Configure
cp .env.example .env

# 3. Generate a password hash and paste it into .env
docker run --rm caddy:2.8-alpine caddy hash-password --plaintext 'your-password'

# 4. Edit .env: set PTO_DOMAIN, PTO_USER, PTO_PASSWORD_HASH
nano .env

# 5. Start the app plus the HTTPS proxy
docker compose --profile public up -d --build
```

Visit `https://your-domain`. Caddy obtains the certificate on first request and
renews it automatically. You will be asked for the username and password you set.

### What is actually exposed

| Port | Reachable from | Why |
|---|---|---|
| 80, 443 | the internet | Caddy — TLS, password, reverse proxy |
| 8501 | **localhost only** | `127.0.0.1:8501:8501` in `docker-compose.yml` |

Streamlit is never directly reachable from outside. Without the `public` profile
Caddy does not start at all, and the app is localhost-only — reach it over an SSH
tunnel if you prefer no public exposure:

```bash
ssh -L 8501:localhost:8501 user@your-vps     # then open localhost:8501
```

### Updating

```bash
git pull
docker compose --profile public up -d --build
```

The `pto-data` volume is untouched, so your plan survives the deploy. That is the
whole point of keeping the database outside the image.

---

## 2b. Making it stay up

"Deployed" and "stays up" are different problems. Three things kill a long-running
box, and each needs its own answer.

### It must survive the SSH session closing

`streamlit run` in a terminal dies the moment you disconnect. Never deploy that way.
Both supported paths run it as a managed background service instead: Docker with
`restart: unless-stopped`, or systemd with `Restart=always`.

### It must survive a reboot

This is the one people miss. Check the daemon itself starts at boot:

```bash
systemctl is-enabled docker      # want: enabled
sudo systemctl enable docker     # if it is not
```

`restart: unless-stopped` brings containers back when Docker starts — but only if
Docker starts. For systemd, `systemctl enable --now pto-hacker` does both.

Prove it rather than hoping:

```bash
sudo reboot
# wait, reconnect
docker compose ps                # both services Up
curl -I https://your-domain
```

### It must survive crashes and hangs

A crash is handled: the restart policy brings it straight back.

A **hang** is not. The container defines a `HEALTHCHECK`, but plain Docker and
Compose only *report* health — nothing restarts an unhealthy container. If you want
that, add a watchdog:

```yaml
  autoheal:
    image: willfarrell/autoheal
    restart: unless-stopped
    environment:
      AUTOHEAL_CONTAINER_LABEL: all
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

For a single-user tool this is usually overkill — Streamlit hangs are rare, and you
would notice. Know the gap exists rather than assuming the healthcheck covers it.

### It must not fill the disk

Container logs grow forever by default, and a full disk takes everything down months
after you stopped paying attention. `docker-compose.yml` caps them at 10 MB x 3 files
per service. Keep an eye on the rest:

```bash
df -h /                          # disk
docker system df                 # images, volumes, build cache
docker system prune -f           # reclaim old layers (safe: named volumes survive)
```

A 1 GB VPS with no swap can also be OOM-killed under memory spikes:

```bash
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Day-to-day commands

```bash
docker compose ps                      # what is running, and health
docker compose logs -f app             # follow logs
docker compose logs --tail=100 caddy   # TLS problems show up here
docker compose restart app             # bounce just the app
docker compose --profile public up -d --build   # deploy an update
```

systemd equivalents: `systemctl status pto-hacker`, `journalctl -u pto-hacker -f`,
`systemctl restart pto-hacker`.

### Lock the box down

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443
sudo ufw enable
sudo apt install -y unattended-upgrades    # security patches without you
```

Port 8501 is deliberately absent — the app is bound to `127.0.0.1`, so only Caddy
reaches it.

## 2c. The background worker

`docker compose up` starts two containers: `app` (the UI) and `worker` (the
scheduler). The worker is what makes this worth putting on a server.

### Turning on Telegram

1. Message **@BotFather** on Telegram, send `/newbot`, answer its two questions,
   and copy the token it gives you.
2. Put the token in `.env` as `PTOHACKER_TELEGRAM_TOKEN`.
3. Find your bot in Telegram and **send it any message** — bots cannot start a
   conversation, so without this step there is nothing to reply to.
4. Let the app find your chat id:

   ```bash
   python daemon.py --telegram-chat-id
   # or: docker compose exec worker python daemon.py --telegram-chat-id
   ```

   ```
   Chats that have messaged this bot:

     PTOHACKER_TELEGRAM_CHAT_ID=987654321   <- Aryan  'hi'
   ```

5. Put that line in `.env` too, so it ends up with:

```bash
PTOHACKER_NOTIFY=telegram
PTOHACKER_TELEGRAM_TOKEN=123456:ABC...
PTOHACKER_TELEGRAM_CHAT_ID=987654321
TZ=Asia/Kolkata
```

A `.env` file is read whether you run in Docker or directly with Python — a real
environment variable always wins over it, and `.env` is gitignored so your token
never reaches the repo.

`TZ` is not optional. The worker schedules by local hour and a container defaults
to UTC, so an "08:00" digest would arrive at 13:30 in India.

Prove it works before trusting it — this is the one step you must not skip,
because it is the only part of the pipeline that cannot be tested without your
credentials:

```bash
docker compose exec worker python daemon.py --test-notify
```

It sends a short message and exits non-zero if delivery fails. The test message
deliberately contains an underscore, which is exactly what breaks Telegram's
Markdown parser — if the whole thing arrives intact, the plain-text fallback is
working too.

Then:

```bash
docker compose exec worker python daemon.py --job digest   # a real digest
docker compose exec worker python daemon.py --list         # schedule + last run
docker compose logs -f worker
```

### Turning on real fares

```bash
PTOHACKER_FARES=google
```

This scrapes Google Flights through `fast-flights`. Understand what you are
switching on: it is against Google's terms of service, datacenter IPs get blocked
far more aggressively than home connections, and the format changes without
notice. **Expect it to break eventually.** The app degrades correctly when it does
— a failed route is logged and skipped, the other jobs still run, and the digest
still sends. Leave it unset for the offline mock.

### Running the worker without Docker

`python daemon.py --once` runs whatever is due and exits, so host cron works:

```cron
*/15 * * * * cd /home/ptohacker/app && PTOHACKER_DB=/var/lib/pto-hacker/pto.db   .venv/bin/python daemon.py --once >> /var/log/pto-hacker.log 2>&1
```

Or a second systemd unit running `daemon.py` with `Restart=always`.

## 3. Backups

All state is one SQLite file. **Do not `cp` it while the app is running** — WAL
mode means recent writes can still be in `pto.db-wal`, and a plain copy can catch
a torn state. Use SQLite's own backup:

```bash
docker compose exec app python -c \
  "import sqlite3,os; src=sqlite3.connect(os.environ['PTOHACKER_DB']); \
   dst=sqlite3.connect('/data/backup.db'); src.backup(dst); dst.close(); src.close()"

docker compose cp app:/data/backup.db ./pto-backup-$(date +%F).db
```

A weekly cron entry doing that is enough for a personal deployment. For
continuous off-box copies, point [Litestream](https://litestream.io) at the same
file.

To restore: stop the stack, copy the backup over `pto.db` in the volume, start again.

---

## 4. Without Docker (systemd)

If you would rather not run Docker:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin ptohacker
sudo -u ptohacker git clone <your-repo-url> /home/ptohacker/app
cd /home/ptohacker/app
sudo -u ptohacker python3 -m venv .venv
sudo -u ptohacker .venv/bin/pip install -r requirements.txt
sudo install -d -o ptohacker -g ptohacker /var/lib/pto-hacker
```

`/etc/systemd/system/pto-hacker.service`:

```ini
[Unit]
Description=PTO-Hacker
After=network.target

[Service]
User=ptohacker
WorkingDirectory=/home/ptohacker/app
Environment=PTOHACKER_DB=/var/lib/pto-hacker/pto.db
ExecStart=/home/ptohacker/app/.venv/bin/streamlit run app.py \
  --server.address=127.0.0.1 --server.port=8501 \
  --server.headless=true --browser.gatherUsageStats=false
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now pto-hacker
```

Then put Caddy or nginx in front of `127.0.0.1:8501`. **Binding to `127.0.0.1` is
not optional** — Streamlit's default is to listen on every interface, which would
put an unauthenticated app straight onto the public internet.

---

## 5. Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `PTOHACKER_DB` | `output/pto.db` | Where the SQLite database lives. Point at a mounted volume in production. |
| `PTO_DOMAIN` | — | Domain Caddy serves and requests a certificate for. |
| `PTO_USER` | — | Basic-auth username. |
| `PTO_PASSWORD_HASH` | — | Output of `caddy hash-password`. Never the plaintext. |

---

## 6. Honest status

What is tested and working:

- Scheduling, job behaviour and failure handling (`daemon_test.py`): hour and
  day gates, once-per-period, alert de-duplication, a throwing job not killing
  the daemon, and a failed send not voiding the job's work
- Real fares really do come back from the Google scraper — verified live, in INR

- A cold clone installs from `requirements.txt` and boots with no pre-existing
  database (`scripts/clean_clone_check.sh` verifies exactly this, including a
  fresh virtualenv and both test suites)
- State survives a full browser restart and a server restart
- The health endpoint `/_stcore/health` responds, so the container healthcheck is real

What is **not** verified, and you should check on your own box:

- **The Docker image has never been built.** It was written against a machine with
  no Docker installed, so `docker compose up --build` is unproven. The Compose file
  parses and the Dockerfile is conventional, but expect to debug it once.
- Caddy's certificate issuance depends on your DNS and firewall, which cannot be
  tested from here.

Privacy posture:

- All state is one SQLite file on your own disk. No outbound HTTP at runtime, and
  Streamlit's telemetry is disabled in `.streamlit/config.toml` (its default is on).
- Commitment labels are free text you typed — treat the database as personal data
  and back it up somewhere you control.

Known limitations by design:

- **Single user.** One password in front of the whole app; there are no accounts,
  and everyone who logs in shares one plan.
- **Fares are synthetic by default.** `MockFareProvider` is offline and invented.
  `PTOHACKER_FARES=google` gives real prices by scraping Google Flights — see
  section 2c for why that is opt-in and expected to break eventually. Getaway cost
  bands are hand-researched ranges, not quotes.
- **Graceful SIGTERM shutdown is unverified.** It is written correctly for Linux,
  but the dev machine is Windows, which does not deliver POSIX signals the same
  way. Worst case `docker compose stop` is a hard kill, which SQLite survives.
- **Streamlit holds session state in-process**, so this does not scale horizontally.
  For a personal or small-team tool on one VPS, that is irrelevant.
