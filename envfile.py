"""Minimal .env loader.

Docker Compose reads .env by itself, so until now a `.env` file only worked
inside containers -- running `python daemon.py` on the host silently saw no
credentials and reported Telegram as unconfigured. This closes that gap so both
paths behave the same.

Stdlib only; python-dotenv would be a dependency for ~30 lines.

Rules:
  * a variable that was ALREADY in the real environment when this module was
    imported always wins, so `PTOHACKER_NOTIFY=console python daemon.py` still
    overrides the file
  * anything else is re-read from the file every time load() is called, so
    editing .env and refreshing the app picks up the change
  * `#` comments, blank lines and a leading `export ` are ignored
  * surrounding single or double quotes are stripped
  * values are taken literally: no shell expansion, no $VAR substitution

Why the first two rules are not just "don't overwrite what is set":
Streamlit re-runs the script on every interaction, and a plain
"skip keys already in os.environ" rule caches the FIRST value forever. Starting
the app with an empty `PTOHACKER_TELEGRAM_TOKEN=` put an empty string into the
process environment, and every later reload then skipped the key as "already
set" -- so filling in the token and refreshing left the UI insisting the
channel was not configured, while the CLI worked fine. Tracking which keys came
from the real environment, rather than which keys exist, fixes that.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / ".env"

# Variables that belong to the real environment, captured before we touch it.
_REAL_ENV: frozenset[str] = frozenset(os.environ)


def load(path: str | Path | None = None, override: bool = False) -> int:
    """Load KEY=VALUE pairs into os.environ. Returns how many were set."""
    p = Path(path or DEFAULT_PATH)
    if not p.exists():
        return 0

    loaded = 0
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # Refresh anything we own; never clobber the real environment.
        if override or key not in _REAL_ENV:
            if os.environ.get(key) != value:
                loaded += 1
            os.environ[key] = value
    return loaded
