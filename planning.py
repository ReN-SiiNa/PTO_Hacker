"""Builds the current plan from stored settings.

The UI and the background jobs MUST agree on what your plan is -- if the app
shows one set of breaks and the Telegram digest another, the product is broken
in the most embarrassing possible way. So both build it here, once.

Pure: no Streamlit, no network. Safe to import from the daemon.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import config as cfg
import sources
import store
from caldays import Holiday, YearCalendar
from optimizer import Break, PlanSummary, blocked_indices, find_candidates, make_commitment


@dataclass
class PlanContext:
    year: int
    settings: dict
    cal: YearCalendar
    holidays: list[Holiday]
    company: list[Holiday]
    commitments: list[tuple[Break, str, int]] = field(default_factory=list)
    accepted: list[tuple[Break, int]] = field(default_factory=list)

    @property
    def chosen(self) -> list[Break]:
        breaks = [b for b, _, _ in self.commitments] + [b for b, _ in self.accepted]
        return sorted(breaks, key=lambda b: b.start)

    @property
    def balance(self) -> int:
        return int(self.settings.get("balance", cfg.DEFAULT_LEAVE_BALANCE))

    @property
    def spent(self) -> int:
        return sum(b.cost for b in self.chosen)

    @property
    def remaining(self) -> int:
        return max(0, self.balance - self.spent)

    @property
    def summary(self) -> PlanSummary:
        return PlanSummary(self.chosen, self.balance)

    def upcoming(self, today: date | None = None) -> list[Break]:
        today = today or date.today()
        return [b for b in self.chosen if b.start >= today]

    def label_for(self, brk: Break) -> str:
        for b, label, _ in self.commitments:
            if b.start == brk.start and b.end == brk.end:
                return label
        return ""

    def suggestions(self, after: date | None = None,
                    before: date | None = None) -> list[Break]:
        """What the remaining balance could still buy, avoiding what is booked.

        `after` matters more than it looks: a background job firing in November
        must not advise the user to take a break in March. Default is no filter
        so the UI still lists the whole year.
        """
        s = self.settings
        cands = find_candidates(
            self.cal,
            int(s.get("max_per_break", cfg.DEFAULT_MAX_LEAVE_PER_BREAK)),
            int(s.get("min_span", cfg.DEFAULT_MIN_SPAN)),
            bool(s.get("require_bridge", True)),
            blocked_indices(self.cal, self.chosen),
        )
        out = [c for c in cands if c.cost <= self.remaining]
        if after:
            out = [c for c in out if c.start >= after]
        if before:
            out = [c for c in out if c.end <= before]
        return out


def statutory_for(year: int, settings: dict) -> list[Holiday]:
    """Reproduce whatever holiday source the user picked in the sidebar."""
    if not settings.get("use_statutory", True):
        return []
    if settings.get("source", "holidays library") == "holidays library" \
            and sources.HAS_PYHOLIDAYS:
        try:
            return sources.from_library(
                settings.get("country", cfg.DEFAULT_COUNTRY),
                year,
                settings.get("subdiv"),
            )
        except Exception:
            return []
    files = sources.curated_files()
    if not files:
        return []
    hols, _ = sources.from_file(str(files[0]))
    return [h for h in hols if h.scope != "optional"]


def build(year: int | None = None) -> PlanContext:
    settings = store.all_settings()
    year = year or int(settings.get("year", cfg.DEFAULT_YEAR))

    company = [
        Holiday(day=date.fromisoformat(h["date"]), name=h["name"],
                scope="company", confidence="high")
        for h in store.company_holidays(year)
    ]
    holidays = sources.merge(company, statutory_for(year, settings))

    weekend = cfg.WEEKEND_PRESETS.get(
        settings.get("weekend", "Sat + Sun"), cfg.DEFAULT_WEEKEND
    )
    cal = YearCalendar(date(year, 1, 1), date(year, 12, 31), holidays, weekend)

    ctx = PlanContext(year=year, settings=settings, cal=cal,
                      holidays=holidays, company=company)
    for c in store.commitments(year):
        brk = make_commitment(cal, date.fromisoformat(c["start"]),
                              date.fromisoformat(c["end"]))
        ctx.commitments.append((brk, c["label"], c["id"]))
    for a in store.accepted(year):
        brk = make_commitment(cal, date.fromisoformat(a["start"]),
                              date.fromisoformat(a["end"]))
        ctx.accepted.append((brk, a["id"]))
    return ctx


def leave_year_end(year: int, settings: dict) -> date:
    """When unused leave lapses. Stored as MM-DD; defaults to 31 December."""
    raw = settings.get("leave_year_end", "12-31")
    try:
        month, day = (int(x) for x in str(raw).split("-"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return date(year, 12, 31)
