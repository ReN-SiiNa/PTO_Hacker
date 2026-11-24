"""The work the server does while nobody is watching.

Each job is a plain function: takes nothing, returns a JobResult. The daemon
decides when to run them, writes the run log, and delivers any message. Jobs
never touch the notifier directly, so they stay testable offline.

Design rule throughout: **only speak when there is something to say.** A job
that reports "nothing changed" every morning trains the user to mute it, and a
muted channel is a dead feature. Every alert is also fingerprinted in
`alerts_sent` so the same news is never delivered twice.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

import config as cfg
import getaways as gw
import planning
import store
from flights import get_provider
from watchlist import Watchlist

RUPEE = "₹"

# How far ahead to nudge about an upcoming break.
REMIND_DAYS = (30, 14, 3)
# Warn about lapsing leave at these distances from the leave-year end.
EXPIRY_DAYS = (90, 60, 30, 14)
# A fare must beat the previous best by at least this much to be worth a ping.
FARE_DROP_PCT = 5


@dataclass
class JobResult:
    status: str                 # ok | nothing | error
    detail: str = ""            # one line for the activity log
    message: str | None = None  # what to send, if anything

    @property
    def should_notify(self) -> bool:
        return bool(self.message)


def _money(v) -> str:
    return f"{RUPEE}{v:,}"


def _once(fingerprint: str) -> bool:
    """True the first time only. Keeps a daily job from repeating itself."""
    if store.already_alerted(fingerprint):
        return False
    store.mark_alerted(fingerprint)
    return True


# --------------------------------------------------------------- fares
def check_fares(today: date | None = None) -> JobResult:
    """Re-price watched routes; speak only on a meaningful new low."""
    today = today or date.today()
    wl = Watchlist()
    if not wl.items:
        return JobResult("nothing", "no routes watched")

    # Drop routes whose departure has passed. Without this a daemon running for
    # months accumulates dead watches and reports a failure every morning for
    # flights nobody can book -- real providers return "not found" for past dates.
    stale = [k for k, i in wl.items.items()
             if date.fromisoformat(i.depart) < today]
    for key in stale:
        wl.remove(key)
    if not wl.items:
        return JobResult("nothing", f"only stale routes ({len(stale)} pruned)")

    # Best price per route BEFORE this run, so we can tell what is actually new.
    previous = {k: i.best for k, i in wl.items.items()}

    provider = get_provider()
    updated, failures = wl.refresh(provider)
    if not updated:
        return JobResult("error", f"all {len(failures)} route(s) failed: "
                                  f"{failures[0][:80] if failures else ''}")

    wl.load()
    lines = []
    for key, item in wl.items.items():
        before, now = previous.get(key), item.latest
        if now is None:
            continue
        if before is None:
            continue  # first ever reading: nothing to compare against
        if now >= before:
            continue
        drop_pct = round(100 * (before - now) / before)
        if drop_pct < FARE_DROP_PCT:
            continue
        if not _once(f"fare:{key}:{now}"):
            continue
        lines.append(
            f"✈️ *{item.origin}→{item.destination}* "
            f"{item.depart}{' – ' + item.ret if item.ret else ''}\n"
            f"   {_money(now)}  (was {_money(before)}, down {drop_pct}%)"
            + (f"\n   _{item.note}_" if item.note else "")
        )

    detail = f"checked {updated} route(s), {len(lines)} drop(s)"
    if failures:
        detail += f", {len(failures)} failed"
    if stale:
        detail += f", {len(stale)} stale pruned"
    if not lines:
        return JobResult("ok", detail)
    return JobResult("ok", detail,
                     "Prices fell on routes you are watching:\n\n" + "\n\n".join(lines))


# -------------------------------------------------------- leave expiry
def check_leave_expiry(today: date | None = None) -> JobResult:
    """Warn before unused leave lapses. This is money the user is about to lose."""
    today = today or date.today()
    ctx = planning.build()
    end = planning.leave_year_end(ctx.year, ctx.settings)
    days_left = (end - today).days

    if days_left < 0:
        return JobResult("nothing", "leave year already ended")
    if ctx.remaining <= 0:
        return JobResult("nothing", "balance fully planned")

    threshold = min((d for d in EXPIRY_DAYS if days_left <= d), default=None)
    if threshold is None:
        return JobResult("nothing", f"{days_left} days to leave-year end")
    if not _once(f"expiry:{ctx.year}:{threshold}:{ctx.remaining}"):
        return JobResult("nothing", f"{threshold}-day warning already sent")

    best = ctx.suggestions(after=today, before=end)
    best.sort(key=lambda b: (-b.leverage, -b.span))
    picks = "\n".join(
        f"   • *{b.label()}* — {b.span} days off for "
        f"{b.cost} leave" for b in best[:3]
    ) or "   (no bridgeable windows left this year)"

    msg = (
        f"⏳ You have *{ctx.remaining} leave days* left and they lapse on "
        f"*{end:%d %B}* — {days_left} days away.\n\n"
        f"Best remaining windows:\n{picks}"
    )
    return JobResult("ok", f"warned: {ctx.remaining} days lapse in {days_left}", msg)


# ------------------------------------------------------- break reminders
def check_reminders(today: date | None = None) -> JobResult:
    """Nudge before a planned break so the leave request actually gets filed."""
    today = today or date.today()
    ctx = planning.build()
    lines = []
    for brk in ctx.upcoming(today):
        days = (brk.start - today).days
        threshold = min((d for d in REMIND_DAYS if days <= d), default=None)
        if threshold is None:
            continue
        if not _once(f"remind:{brk.start}:{threshold}"):
            continue
        label = ctx.label_for(brk)
        action = ("submit your leave request" if threshold >= 14
                  else "confirm bookings")
        lines.append(
            f"\U0001f5d3️ *{brk.label()}*{' — ' + label if label else ''}\n"
            f"   starts in {days} days · {brk.span} days off for "
            f"{brk.cost} leave\n   Time to {action}."
        )
    if not lines:
        return JobResult("nothing", f"{len(ctx.upcoming(today))} upcoming, none due")
    return JobResult("ok", f"{len(lines)} reminder(s)",
                     "Coming up:\n\n" + "\n\n".join(lines))


# -------------------------------------------------------- monthly digest
def monthly_digest(today: date | None = None) -> JobResult:
    """The heartbeat: what is planned, what it costs, what is still unspent.

    Budget comes from the curated getaway cost bands, which are hand-researched
    ranges -- honest as estimates, and independent of any fare provider.
    """
    today = today or date.today()
    ctx = planning.build()
    upcoming = ctx.upcoming(today)
    s = ctx.summary
    city = ctx.settings.get("home_city", cfg.DEFAULT_HOME_AIRPORT)

    if not upcoming:
        body = (f"No breaks planned for the rest of {ctx.year}.\n\n"
                f"You still have *{ctx.remaining} of {ctx.balance}* leave days "
                f"unspent.")
        return JobResult("ok", "digest sent (empty plan)", body)

    lines, lo_total, hi_total = [], 0, 0
    for brk in upcoming:
        nights = brk.span - 1
        options = gw.suggest(city, 25000, nights, brk.start, season_only=True)
        if options:
            lo = min(o.cost_min for o in options)
            hi = min(o.cost_max for o in options[:3])
            lo_total += lo
            hi_total += hi
            names = ", ".join(o.name for o in options[:3])
            cost = f"   est. {_money(lo)}–{_money(hi)} · {names}"
        else:
            cost = "   no in-season getaway fits this one"
        label = ctx.label_for(brk)
        lines.append(
            f"*{brk.label()}*{' — ' + label if label else ''}\n"
            f"   {brk.span} days off for {brk.cost} leave\n{cost}"
        )

    body = (
        f"*{today:%B %Y}* — your year so far\n\n"
        f"{s.total_days_off} days off planned for {s.leave_used} leave days "
        f"({s.overall_leverage:.1f}×). {ctx.remaining} days still unspent.\n\n"
        f"*Coming up ({len(upcoming)})*\n\n" + "\n\n".join(lines)
    )
    if lo_total:
        body += (f"\n\n*Rough budget for all of it:* "
                 f"{_money(lo_total)}–{_money(hi_total)} per person.\n"
                 f"_Estimated ranges, not quotes._")
    return JobResult("ok", f"digest sent, {len(upcoming)} upcoming", body)


# ------------------------------------------------------------- registry
JOBS = {
    "fares": check_fares,
    "expiry": check_leave_expiry,
    "reminders": check_reminders,
    "digest": monthly_digest,
}

# When each job is due. `monthly` fires on day 1.
SCHEDULE = {
    "fares": {"every": "daily", "hour": int(os.environ.get("PTOHACKER_FARES_HOUR", 6))},
    "expiry": {"every": "daily", "hour": 8},
    "reminders": {"every": "daily", "hour": 8},
    "digest": {"every": "monthly", "day": 1, "hour": 8},
}
