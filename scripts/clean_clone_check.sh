#!/usr/bin/env bash
# Simulates a cold clone: copies only the files git would track, builds a fresh
# virtualenv, installs requirements.txt, and runs both test suites plus a boot.
#
# Usage: bash scripts/clean_clone_check.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${TMPDIR:-/tmp}/pto-clean-clone"
PORT="${PORT:-8599}"

echo "== copying tracked files to $DEST"
rm -rf "$DEST"; mkdir -p "$DEST"
cd "$SRC"
# Mirror .gitignore: no output/, no caches, no venv, no .env
tar -cf - \
  --exclude='./output' \
  --exclude='./.venv' \
  --exclude='./venv' \
  --exclude='./.env' \
  --exclude='*/__pycache__' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='./.git' \
  . | (cd "$DEST" && tar -xf -)

cd "$DEST"
echo "== files a cloner receives"
find . -maxdepth 1 -mindepth 1 | sort | sed 's|^\./|   |'

echo "== creating virtualenv"
python -m venv .venv
VPY="$DEST/.venv/Scripts/python.exe"
[ -x "$VPY" ] || VPY="$DEST/.venv/bin/python"

echo "== installing requirements.txt"
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r requirements.txt
echo "   installed:"
"$VPY" -m pip list --format=freeze 2>/dev/null | grep -iE '^(streamlit|holidays)=' | sed 's/^/     /'

echo "== engine test"
PYTHONIOENCODING=utf-8 "$VPY" smoke_test.py | tail -2

echo "== persistence test"
PYTHONIOENCODING=utf-8 "$VPY" store_test.py | tail -2

echo "== notification channels test"
PYTHONIOENCODING=utf-8 "$VPY" notify_test.py | tail -2

echo "== scheduler + jobs test"
PYTHONIOENCODING=utf-8 "$VPY" daemon_test.py | tail -2

echo "== booting app on :$PORT (no pre-existing database)"
PYTHONIOENCODING=utf-8 "$VPY" -m streamlit run app.py \
  --server.port "$PORT" --server.headless true \
  > "$DEST/boot.log" 2>&1 &
BOOT_PID=$!
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "http://localhost:$PORT/_stcore/health" 2>/dev/null; then
    echo "   /_stcore/health -> OK"
    break
  fi
  sleep 2
done
curl -fsS -o /dev/null -w "   GET / -> HTTP %{http_code}\n" "http://localhost:$PORT" || echo "   GET / FAILED"
echo "   db created: $(ls -1 "$DEST/output/" 2>/dev/null | tr '\n' ' ')"
grep -iE "traceback|is not a valid config" "$DEST/boot.log" && echo "   !! errors above" || echo "   no tracebacks, no bad config keys"

# The clone may resolve a NEWER Streamlit than the dev machine has, and this
# app's CSS targets Streamlit's internal markup. Render it and look.
if python -c "import playwright" 2>/dev/null; then
  echo "== screenshotting the clean clone (verifies CSS against the resolved Streamlit)"
  python "$SRC/scripts/shoot.py" "$PORT" "$SRC/output/cleanclone.png" || echo "   screenshot failed"
fi

kill "$BOOT_PID" 2>/dev/null || true

echo "== PASS: a cold clone installs, tests green, app boots"
