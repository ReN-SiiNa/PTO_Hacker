"""Durable state: SQLite.

Replaces two things that did not survive a VPS:
  - `st.session_state`, which is per-WebSocket and dies on refresh or reconnect
  - a single global `output/watchlist.json`, which raced on concurrent writes

Design notes:
  - One short-lived connection per call. SQLite is happy with this, and it
    sidesteps Streamlit's script-rerun threading entirely -- no cached handle to
    go stale, no check_same_thread games.
  - WAL mode so a background poller can write while the app reads.
  - Single-user by design: no owner column. Adding one later means a column and
    a WHERE clause, nothing structural.
  - Path from PTOHACKER_DB so a container can mount a volume somewhere else.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / "output" / "pto.db"
DB_PATH = Path(os.environ.get("PTOHACKER_DB", DEFAULT_DB))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL              -- JSON-encoded
);

CREATE TABLE IF NOT EXISTS company_holidays (
    year INTEGER NOT NULL,
    day  TEXT    NOT NULL,           -- ISO date
    name TEXT    NOT NULL,
    PRIMARY KEY (year, day)
);

CREATE TABLE IF NOT EXISTS commitments (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    year  INTEGER NOT NULL,
    start TEXT    NOT NULL,
    end   TEXT    NOT NULL,
    label TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_commitments_year ON commitments(year);

CREATE TABLE IF NOT EXISTS accepted (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    year  INTEGER NOT NULL,
    start TEXT    NOT NULL,
    end   TEXT    NOT NULL,
    UNIQUE (year, start, end)
);
CREATE INDEX IF NOT EXISTS ix_accepted_year ON accepted(year);

CREATE TABLE IF NOT EXISTS watch (
    key         TEXT PRIMARY KEY,
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart      TEXT NOT NULL,
    ret         TEXT,
    note        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS watch_price (
    key        TEXT    NOT NULL REFERENCES watch(key) ON DELETE CASCADE,
    checked_at TEXT    NOT NULL,
    price      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_watch_price_key ON watch_price(key, checked_at);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job         TEXT    NOT NULL,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    status      TEXT    NOT NULL DEFAULT 'running',  -- ok | nothing | error
    detail      TEXT    NOT NULL DEFAULT '',
    notified    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_runs_job ON runs(job, started_at);

-- Remembers what we have already told the user about, so a daily job does not
-- re-send the same alert every morning. Alert fatigue kills these products.
CREATE TABLE IF NOT EXISTS alerts_sent (
    fingerprint TEXT PRIMARY KEY,
    sent_at     TEXT NOT NULL
);
"""


_schema_lock = threading.Lock()
_schema_ready = False


@contextmanager
def connect():
    """A short-lived connection, with the schema guaranteed to exist.

    Self-initialising on purpose: any entry point -- the app, a test, a
    background poller -- can just call store functions. Requiring callers to
    remember init() first is a bug waiting to happen, and did happen: the
    engine test passed locally only because a database was already lying
    around, then failed on a clean checkout.
    """
    global _schema_ready
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    if not _schema_ready:
        with _schema_lock:
            if not _schema_ready:          # re-check: reruns can race
                con.executescript(SCHEMA)  # CREATE TABLE IF NOT EXISTS
                con.commit()
                _schema_ready = True
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    """Explicit setup. Optional -- connect() does this on first use."""
    with connect():
        pass


# ------------------------------------------------------------- settings
def get_setting(key: str, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def set_settings(values: dict) -> None:
    """Bulk upsert -- one transaction instead of one per widget."""
    with connect() as con:
        con.executemany(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [(k, json.dumps(v)) for k, v in values.items()],
        )


def all_settings() -> dict:
    with connect() as con:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}


# ----------------------------------------------------- company holidays
def company_holidays(year: int) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT day, name FROM company_holidays WHERE year=? ORDER BY day", (year,)
        ).fetchall()
    return [{"date": r["day"], "name": r["name"]} for r in rows]


def add_company_holidays(year: int, rows: list[dict]) -> int:
    """Insert, skipping dates already present. Returns how many landed."""
    if not rows:
        return 0
    with connect() as con:
        before = con.total_changes
        con.executemany(
            "INSERT OR IGNORE INTO company_holidays(year, day, name) VALUES(?, ?, ?)",
            [(year, r["date"], r["name"]) for r in rows],
        )
        return con.total_changes - before


def remove_company_holiday(year: int, day: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM company_holidays WHERE year=? AND day=?", (year, day))


def clear_company_holidays(year: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM company_holidays WHERE year=?", (year,))


# ---------------------------------------------------------- commitments
def commitments(year: int) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT id, start, end, label FROM commitments WHERE year=? ORDER BY start",
            (year,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_commitment(year: int, start: date, end: date, label: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO commitments(year, start, end, label) VALUES(?, ?, ?, ?)",
            (year, start.isoformat(), end.isoformat(), label),
        )


def remove_commitment(row_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM commitments WHERE id=?", (row_id,))


# ------------------------------------------------------------- accepted
def accepted(year: int) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT id, start, end FROM accepted WHERE year=? ORDER BY start", (year,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_accepted(year: int, start: date, end: date) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO accepted(year, start, end) VALUES(?, ?, ?)",
            (year, start.isoformat(), end.isoformat()),
        )


def add_accepted_many(year: int, spans: list[tuple[date, date]]) -> None:
    with connect() as con:
        con.executemany(
            "INSERT OR IGNORE INTO accepted(year, start, end) VALUES(?, ?, ?)",
            [(year, s.isoformat(), e.isoformat()) for s, e in spans],
        )


def remove_accepted(row_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM accepted WHERE id=?", (row_id,))


def clear_accepted(year: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM accepted WHERE year=?", (year,))


# ------------------------------------------------------------ fare watch
def watch_items() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM watch ORDER BY depart").fetchall()
        out = []
        for r in rows:
            hist = con.execute(
                "SELECT checked_at, price FROM watch_price WHERE key=? "
                "ORDER BY checked_at",
                (r["key"],),
            ).fetchall()
            item = dict(r)
            item["history"] = [dict(h) for h in hist]
            out.append(item)
    return out


def upsert_watch(key: str, origin: str, destination: str, depart: str,
                 ret: str | None, note: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO watch(key, origin, destination, depart, ret, note) "
            "VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET note=excluded.note",
            (key, origin, destination, depart, ret, note),
        )


def delete_watch(key: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM watch_price WHERE key=?", (key,))
        con.execute("DELETE FROM watch WHERE key=?", (key,))


def record_price(key: str, price: int, checked_at: str | None = None) -> None:
    ts = checked_at or datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            "INSERT INTO watch_price(key, checked_at, price) VALUES(?, ?, ?)",
            (key, ts, price),
        )


def record_prices(rows: list[tuple[str, int]]) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        con.executemany(
            "INSERT INTO watch_price(key, checked_at, price) VALUES(?, ?, ?)",
            [(k, ts, p) for k, p in rows],
        )


# ------------------------------------------------------------- migration
def migrate_watchlist_json(path: Path) -> int:
    """One-time import of the old output/watchlist.json. Returns rows moved."""
    path = Path(path)
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return 0
    moved = 0
    for item in raw.get("items", []):
        key = (f"{item['origin']}-{item['destination']}-{item['depart']}-"
               f"{item.get('ret') or 'ow'}")
        upsert_watch(key, item["origin"], item["destination"], item["depart"],
                     item.get("ret"), item.get("note", ""))
        for p in item.get("history", []):
            record_price(key, p["price"], p.get("checked_at"))
        moved += 1
    if moved:
        path.rename(path.with_suffix(".json.migrated"))
    return moved


# ------------------------------------------------------------- run log
def start_run(job: str) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO runs(job, started_at) VALUES(?, ?)",
            (job, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, detail: str = "",
               notified: bool = False) -> None:
    with connect() as con:
        con.execute(
            "UPDATE runs SET finished_at=?, status=?, detail=?, notified=? WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), status, detail,
             int(notified), run_id),
        )


def recent_runs(limit: int = 50) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def last_run(job: str) -> dict | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM runs WHERE job=? AND finished_at IS NOT NULL "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (job,),
        ).fetchone()
    return dict(row) if row else None


def run_counts(since_iso: str) -> dict:
    with connect() as con:
        rows = con.execute(
            "SELECT status, COUNT(*) c FROM runs WHERE started_at >= ? GROUP BY status",
            (since_iso,),
        ).fetchall()
    return {r["status"]: r["c"] for r in rows}


# ----------------------------------------------------------- alert dedupe
def already_alerted(fingerprint: str) -> bool:
    with connect() as con:
        return con.execute(
            "SELECT 1 FROM alerts_sent WHERE fingerprint=?", (fingerprint,)
        ).fetchone() is not None


def mark_alerted(fingerprint: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO alerts_sent(fingerprint, sent_at) VALUES(?, ?)",
            (fingerprint, datetime.now().isoformat(timespec="seconds")),
        )


def forget_alerts(prefix: str) -> None:
    """Drop remembered alerts under a prefix, so they can fire again."""
    with connect() as con:
        con.execute("DELETE FROM alerts_sent WHERE fingerprint LIKE ?", (prefix + "%",))
