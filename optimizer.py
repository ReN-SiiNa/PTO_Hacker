"""The core engine: find the highest-leverage ways to spend a leave balance."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from caldays import WORK, YearCalendar


@dataclass(frozen=True)
class Break:
    """A contiguous stretch of days off, and the leave it costs to buy it."""

    start: date          # first day off (after extending into adjacent weekends/holidays)
    end: date            # last day off
    leave_days: tuple[date, ...]
    reasons: tuple[str, ...]   # holiday names bridged by this break

    @property
    def span(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def cost(self) -> int:
        return len(self.leave_days)

    @property
    def leverage(self) -> float:
        """Days off per leave day spent. Infinite (free) breaks report as span."""
        return self.span / self.cost if self.cost else float(self.span)

    @property
    def is_free(self) -> bool:
        return self.cost == 0

    def label(self) -> str:
        if self.start.month == self.end.month:
            return f"{self.start:%d}–{self.end:%d %b}"
        return f"{self.start:%d %b} – {self.end:%d %b}"

    def describe(self) -> str:
        cost = "0 leave" if self.is_free else f"{self.cost} leave day{'s' if self.cost > 1 else ''}"
        return f"{self.span} days off for {cost}"


def _extend(cal: YearCalendar, lo: int, hi: int) -> tuple[int, int]:
    """Grow a core interval outward across already-free days."""
    while lo - 1 >= 0 and cal.is_free(lo - 1):
        lo -= 1
    while hi + 1 < len(cal.days) and cal.is_free(hi + 1):
        hi += 1
    return lo, hi


def _make_break(cal: YearCalendar, lo: int, hi: int) -> Break:
    leave, reasons = [], []
    for i in range(lo, hi + 1):
        d = cal.days[i]
        if cal.kind[i] == WORK:
            leave.append(d)
        elif d in cal.holiday_names:
            reasons.append(cal.holiday_names[d])
    return Break(cal.days[lo], cal.days[hi], tuple(leave), tuple(reasons))


def make_commitment(cal: YearCalendar, start: date, end: date) -> Break:
    """A break the user has already decided to take, whatever the leverage.

    Extends outward across adjacent weekends/holidays so the span shown is the
    real time away, and counts only workdays against the leave balance.
    """
    lo, hi = _extend(cal, cal.index[start], cal.index[end])
    return _make_break(cal, lo, hi)


def blocked_indices(cal: YearCalendar, breaks: list[Break]) -> set[int]:
    """Day indices already spoken for by commitments or accepted breaks."""
    out: set[int] = set()
    for b in breaks:
        out.update(range(cal.index[b.start], cal.index[b.end] + 1))
    return out


def find_candidates(
    cal: YearCalendar,
    max_leave_per_break: int = 4,
    min_span: int = 3,
    require_bridge: bool = True,
    blocked: set[int] | None = None,
) -> list[Break]:
    """Every distinct break worth considering, deduped by its extended span.

    require_bridge: only keep paid breaks that actually bridge a public holiday.
        Without this the optimizer just buys isolated Fridays all year -- every
        single one is a 3-for-1, so it maximises raw days off while producing a
        plan nobody would ever act on.
    """
    seen: dict[tuple[int, int], Break] = {}
    n = len(cal.days)
    blocked = blocked or set()

    def clear(lo: int, hi: int) -> bool:
        return not any(k in blocked for k in range(lo, hi + 1))

    # Paid breaks: a core that starts and ends on a workday, then extends outward.
    for i in range(n):
        if cal.kind[i] != WORK or i in blocked:
            continue
        cost = 0
        for j in range(i, n):
            if cal.kind[j] == WORK:
                cost += 1
            if cost > max_leave_per_break:
                break
            if cal.kind[j] != WORK:
                continue  # cores must end on a workday, else it's a duplicate
            lo, hi = _extend(cal, i, j)
            if (hi - lo + 1) < min_span or (lo, hi) in seen or not clear(lo, hi):
                continue
            brk = _make_break(cal, lo, hi)
            if require_bridge and not brk.reasons:
                continue
            seen[(lo, hi)] = brk

    # Free breaks: maximal runs of weekend/holiday that are already long enough.
    i = 0
    while i < n:
        if cal.is_free(i):
            j = i
            while j + 1 < n and cal.is_free(j + 1):
                j += 1
            if (j - i + 1) >= min_span and (i, j) not in seen and clear(i, j):
                seen[(i, j)] = _make_break(cal, i, j)
            i = j + 1
        else:
            i += 1

    return sorted(seen.values(), key=lambda b: b.start)


def rank_candidates(candidates: list[Break]) -> list[Break]:
    """Best bang-for-buck first; longer wins ties."""
    return sorted(candidates, key=lambda b: (-b.leverage, -b.span, b.start))


def select_plan(
    cal: YearCalendar,
    candidates: list[Break],
    budget: int,
    longer_bias: float = 0.35,
) -> list[Break]:
    """Pick non-overlapping breaks maximising total days off within the leave budget.

    Exact DP over (day index, leave remaining) -- no greedy approximation.

    longer_bias: 0 maximises raw days off, which ties a week-long trip with two
        long weekends. Above 0 the score becomes span ** (1 + bias), so the same
        number of days off is worth more when concentrated into fewer, longer
        breaks -- which is what a real holiday actually needs to be.
    """
    score = lambda b: b.span ** (1.0 + longer_bias)  # noqa: E731
    n = len(cal.days)
    by_start: dict[int, list[Break]] = {}
    for b in candidates:
        if b.cost <= budget:
            by_start.setdefault(cal.index[b.start], []).append(b)

    # dp[i][r] = best achievable score from day i onward with r leave left.
    dp = [[0.0] * (budget + 1) for _ in range(n + 1)]
    take: dict[tuple[int, int], Break] = {}

    for i in range(n - 1, -1, -1):
        row, nxt = dp[i], dp[i + 1]
        for r in range(budget + 1):
            best, pick = nxt[r], None
            for b in by_start.get(i, ()):
                if b.cost > r:
                    continue
                val = score(b) + dp[cal.index[b.end] + 1][r - b.cost]
                if val > best:
                    best, pick = val, b
            row[r] = best
            if pick is not None:
                take[(i, r)] = pick

    plan, i, r = [], 0, budget
    while i < n:
        pick = take.get((i, r))
        if pick is not None and dp[i][r] > dp[i + 1][r]:
            plan.append(pick)
            i = cal.index[pick.end] + 1
            r -= pick.cost
        else:
            i += 1
    return plan


@dataclass
class PlanSummary:
    breaks: list[Break]
    budget: int

    @property
    def paid(self) -> list[Break]:
        return [b for b in self.breaks if not b.is_free]

    @property
    def leave_used(self) -> int:
        return sum(b.cost for b in self.breaks)

    @property
    def leave_left(self) -> int:
        return self.budget - self.leave_used

    @property
    def total_days_off(self) -> int:
        return sum(b.span for b in self.breaks)

    @property
    def longest(self) -> Break | None:
        return max(self.breaks, key=lambda b: b.span, default=None)

    @property
    def overall_leverage(self) -> float:
        return self.total_days_off / self.leave_used if self.leave_used else 0.0
