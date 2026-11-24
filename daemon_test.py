"""Scheduling + job logic, against a throwaway DB. Run: python daemon_test.py

Deterministic: no sleeping, no wall-clock dependence, no network. Every time is
injected so the same assertions hold whenever this runs.
"""
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="ptohacker-daemon-test-"))
os.environ["PTOHACKER_DB"] = str(TMP / "test.db")
os.environ["PTOHACKER_NOTIFY"] = "none"
os.environ["PTOHACKER_FARES"] = "mock"

import daemon  # noqa: E402
import jobs  # noqa: E402
import notify  # noqa: E402
import store  # noqa: E402

store.init()
print(f"db: {store.DB_PATH}")


def stamp(job: str, when: datetime, status: str = "ok") -> None:
    """Record a completed run AT A GIVEN TIME.

    store.start_run() stamps the real clock, so tests that inject a fake `now`
    must backdate the row or they are comparing against today's date.
    """
    rid = store.start_run(job)
    store.finish_run(rid, status, "test")
    with store.connect() as con:
        con.execute("UPDATE runs SET started_at=?, finished_at=? WHERE id=?",
                    (when.isoformat(timespec="seconds"),
                     when.isoformat(timespec="seconds"), rid))


# ----------------------------------------------------- is_due: daily jobs
NOW = datetime(2026, 6, 15, 9, 0)          # a Monday, 09:00

assert daemon.is_due("expiry", NOW), "never run + past its hour -> due"
assert not daemon.is_due("expiry", NOW.replace(hour=7)), "before its hour -> not due"

stamp("expiry", NOW)
assert not daemon.is_due("expiry", NOW), "already ran today -> not due"
assert daemon.is_due("expiry", NOW + timedelta(days=1)), "next day -> due again"
print("is_due daily: hour gate, once-per-day, next-day rollover all OK")

# -------------------------------------------------- is_due: monthly digest
first_9am = datetime(2026, 7, 1, 9, 0)
assert daemon.is_due("digest", first_9am), "1st of month, past hour -> due"
assert not daemon.is_due("digest", datetime(2026, 7, 2, 9, 0)), "2nd -> not due"
assert not daemon.is_due("digest", datetime(2026, 7, 1, 7, 0)), "too early -> not due"

stamp("digest", first_9am)
assert not daemon.is_due("digest", datetime(2026, 7, 1, 10, 0)), "same month -> no"
assert daemon.is_due("digest", datetime(2026, 8, 1, 9, 0)), "next month -> yes"
print("is_due monthly: day gate, once-per-month, month rollover all OK")

assert not daemon.is_due("nonsense", NOW), "unknown job must never be due"

# ------------------------------------------------- run_job records and is safe
def _boom():
    raise RuntimeError("deliberate explosion")


jobs.JOBS["explode"] = _boom
status = daemon.run_job("explode", notify.NullNotifier())
assert status == "error", "a throwing job must be caught, not propagate"
last = store.last_run("explode")
assert last["status"] == "error" and "explosion" in last["detail"]
print("run_job: exceptions caught, logged as error, daemon survives")


class _Boom(notify.Notifier):
    name = "boom"

    def send(self, text, title=None):
        raise notify.NotifyError("channel down")


jobs.JOBS["talky"] = lambda: jobs.JobResult("ok", "did work", "a message")
status = daemon.run_job("talky", _Boom())
assert status == "ok", "delivery failure must not void the work"
last = store.last_run("talky")
assert not last["notified"] and "delivery failed" in last["detail"]
print("run_job: delivery failure recorded, job still counted as done")

# ------------------------------------------------------- alert de-duplication
store.forget_alerts("t:")
assert jobs._once("t:a") and not jobs._once("t:a"), "same alert must fire once"
assert jobs._once("t:b"), "a different alert still fires"
print("dedupe: an alert fires once and only once")

# ----------------------------------------------------------- job behaviour
store.set_settings({"year": 2026, "balance": 12, "home_city": "BLR",
                    "leave_year_end": "12-31", "use_statutory": True,
                    "source": "holidays library", "country": "IN",
                    "weekend": "Sat + Sun"})

r = jobs.check_fares(today=date(2026, 6, 15))
assert r.status == "nothing" and "no routes" in r.detail
print(f"fares, nothing watched: {r.status} - {r.detail}")

r = jobs.check_leave_expiry(today=date(2026, 1, 10))
assert r.status == "nothing", "January is not expiry season"
r = jobs.check_leave_expiry(today=date(2026, 11, 15))
assert r.status == "ok" and r.should_notify, "46 days out with 12 unspent -> warn"
assert "lapse" in r.message
r2 = jobs.check_leave_expiry(today=date(2026, 11, 16))
assert not r2.should_notify, "must not warn again the next day"
print(f"expiry: silent in Jan, warns in Nov, silent again next day")

store.add_accepted(2026, date(2026, 12, 25), date(2026, 12, 27))
r = jobs.check_reminders(today=date(2026, 12, 11))   # 14 days before
assert r.should_notify and "25" in r.message, "14-day reminder should fire"
assert not jobs.check_reminders(today=date(2026, 12, 12)).should_notify
print("reminders: fires on threshold, silent the following day")

r = jobs.monthly_digest(today=date(2026, 12, 1))
assert r.status == "ok" and r.should_notify
assert "December 2026" in r.message
print("digest: builds a message from the stored plan")

# A digest and the UI must agree -- both read planning.build()
import planning  # noqa: E402
ctx = planning.build(2026)
assert any(b.start == date(2026, 12, 25) for b in ctx.chosen), \
    "planning context must see what the store holds"
print("planning: UI and jobs share one source of truth")

print("\nALL DAEMON CHECKS PASSED")
