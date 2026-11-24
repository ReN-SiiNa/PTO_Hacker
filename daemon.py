"""The always-on half of PTO-Hacker.

A long-running loop that wakes up, asks which jobs are due, runs them, records
what happened, and sends anything worth sending.

    python daemon.py              # run forever (this is what the VPS runs)
    python daemon.py --once       # run whatever is due right now, then exit
    python daemon.py --job digest # force one job regardless of schedule
    python daemon.py --list       # show schedule and last run of each job

Deliberately stdlib-only: no APScheduler, no Celery, no broker. The scheduling
rules here are "daily at an hour" and "monthly on day 1" -- a dependency to
express that would be a liability, not a convenience.

`--once` exists so the same code works under host cron if you would rather not
run a persistent process.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
import traceback
from datetime import date, datetime

import envfile

# Before importing anything that reads os.environ at import time.
envfile.load()

import jobs as job_module  # noqa: E402
import store  # noqa: E402
from notify import NotifyError, get_notifier  # noqa: E402

POLL_SECONDS = 300          # how often to re-check what is due
_stop = False


def _handle_signal(signum, _frame):
    """Exit cleanly on SIGTERM so `docker compose stop` is not a kill -9."""
    global _stop
    _stop = True
    print(f"[daemon] signal {signum}, finishing current cycle", flush=True)


def is_due(name: str, now: datetime) -> bool:
    """Has this job's window arrived, and has it not already run in it?"""
    rule = job_module.SCHEDULE.get(name)
    if not rule:
        return False
    if now.hour < rule.get("hour", 0):
        return False
    if rule["every"] == "monthly" and now.day != rule.get("day", 1):
        return False

    last = store.last_run(name)
    if not last:
        return True
    last_at = datetime.fromisoformat(last["started_at"])

    if rule["every"] == "daily":
        return last_at.date() < now.date()
    if rule["every"] == "monthly":
        return (last_at.year, last_at.month) < (now.year, now.month)
    return False


def run_job(name: str, notifier) -> str:
    """Run one job, log it, deliver its message. Never raises."""
    fn = job_module.JOBS[name]
    run_id = store.start_run(name)
    try:
        result = fn()
    except Exception:
        detail = traceback.format_exc(limit=3).strip().splitlines()[-1][:300]
        store.finish_run(run_id, "error", detail)
        print(f"[daemon] {name}: ERROR {detail}", flush=True)
        return "error"

    notified = False
    if result.should_notify:
        try:
            notifier.send(result.message, title=f"PTO-Hacker · {name}")
            notified = True
        except NotifyError as exc:
            # The job's work still counts -- only delivery failed.
            result.detail = f"{result.detail} (delivery failed: {exc})"[:300]
            print(f"[daemon] {name}: delivery failed: {exc}", flush=True)

    store.finish_run(run_id, result.status, result.detail, notified)
    print(f"[daemon] {name}: {result.status} — {result.detail}"
          f"{' [sent]' if notified else ''}", flush=True)
    return result.status


def run_due(notifier, now: datetime | None = None) -> int:
    now = now or datetime.now()
    due = [n for n in job_module.JOBS if is_due(n, now)]
    if not due:
        return 0
    print(f"[daemon] due at {now:%Y-%m-%d %H:%M}: {', '.join(due)}", flush=True)
    for name in due:
        run_job(name, notifier)
    return len(due)


def main() -> int:
    ap = argparse.ArgumentParser(description="PTO-Hacker background worker")
    ap.add_argument("--once", action="store_true",
                    help="run whatever is due now, then exit (for cron)")
    ap.add_argument("--job", metavar="NAME",
                    help=f"force one job: {', '.join(job_module.JOBS)}")
    ap.add_argument("--list", action="store_true",
                    help="show the schedule and each job's last run")
    ap.add_argument("--test-notify", action="store_true",
                    help="send a test message through the configured channel")
    ap.add_argument("--telegram-chat-id", action="store_true",
                    help="look up your Telegram chat id from the bot token")
    ap.add_argument("--interval", type=int, default=POLL_SECONDS,
                    help="seconds between due-checks (default 300)")
    args = ap.parse_args()

    store.init()
    notifier = get_notifier()

    if args.list:
        print(f"notifier: {notifier.name} "
              f"({'configured' if notifier.configured else 'NOT configured'})")
        print(f"database: {store.DB_PATH}\n")
        for name, rule in job_module.SCHEDULE.items():
            last = store.last_run(name)
            when = (f"{last['started_at']} ({last['status']})" if last else "never")
            print(f"  {name:10} {str(rule):52} last: {when}")
        return 0

    if args.telegram_chat_id:
        import notify as _notify
        try:
            found = _notify.discover_chat_id()
        except _notify.NotifyError as exc:
            print(f"FAILED: {exc}")
            return 1
        if not found:
            print("Nobody has messaged this bot yet.\n"
                  "Open Telegram, find your bot, send it any message, "
                  "then run this again.")
            return 1
        print("Chats that have messaged this bot:\n")
        for f in found:
            print(f"  PTOHACKER_TELEGRAM_CHAT_ID={f['chat_id']}"
                  f"   <- {f['name']}  {f['text']!r}")
        print("\nPut the right one in your .env file.")
        return 0

    if args.test_notify:
        print(f"channel: {notifier.name} "
              f"({'configured' if notifier.configured else 'NOT configured'})")
        if not notifier.configured:
            print("Set PTOHACKER_NOTIFY=telegram, PTOHACKER_TELEGRAM_TOKEN and "
                  "PTOHACKER_TELEGRAM_CHAT_ID, then try again.")
            return 1
        try:
            notifier.send(
                "If you are reading this on your phone, the channel works."
                "\n\nFormatting check: *bold* and a literal underscore_here."
                "\nThat underscore is deliberate: it is what breaks Telegram's"
                " Markdown parser, so if this whole message arrived, the"
                " plain-text fallback is working too."
                f"\n\nSent {datetime.now():%Y-%m-%d %H:%M} server time"
                f" ({date.today():%A}).",
                title="PTO-Hacker · test",
            )
        except NotifyError as exc:
            print(f"FAILED: {exc}")
            return 1
        print("Sent. Check your phone.")
        return 0

    if args.job:
        if args.job not in job_module.JOBS:
            print(f"unknown job {args.job!r}; known: {', '.join(job_module.JOBS)}")
            return 2
        return 0 if run_job(args.job, notifier) != "error" else 1

    if args.once:
        n = run_due(notifier)
        print(f"[daemon] {n} job(s) ran", flush=True)
        return 0

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    print(f"[daemon] started · notifier={notifier.name} "
          f"configured={notifier.configured} · db={store.DB_PATH} "
          f"· polling every {args.interval}s", flush=True)
    if not notifier.configured:
        print("[daemon] WARNING: channel not configured; alerts will be logged "
              "to the activity panel but not delivered", flush=True)

    while not _stop:
        try:
            run_due(notifier)
        except Exception:
            # A loop that dies on an unexpected error is not "always on".
            traceback.print_exc()
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)
    print("[daemon] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
