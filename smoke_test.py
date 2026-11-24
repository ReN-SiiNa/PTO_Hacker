"""Headless check of the whole pipeline. Run: python smoke_test.py

On Windows: PYTHONIOENCODING=utf-8 python smoke_test.py
"""
from datetime import date

import exporters
import getaways as gw
import sources
from caldays import Holiday, YearCalendar
from flights import MockFareProvider
from optimizer import (
    PlanSummary,
    blocked_indices,
    find_candidates,
    make_commitment,
    rank_candidates,
    select_plan,
)
from watchlist import Watchlist

YEAR, BUDGET = 2026, 18

# --- holiday sources, including a company calendar ------------------------
lib = sources.from_library("IN", YEAR)
curated, note = sources.from_file(sources.curated_files()[0])
company = [
    Holiday(date(YEAR, 5, 8), "Founder's Day", "company"),
    Holiday(date(YEAR, 12, 24), "Christmas Eve", "company"),
]
merged = sources.merge(company, lib)
assert len(merged) >= len(lib), "merge lost entries"
assert any(h.scope == "company" for h in merged), "company holidays dropped"
print(f"holidays: lib {len(lib)} + company {len(company)} -> merged {len(merged)} "
      f"| curated file {len(curated)}")

cal = YearCalendar(date(YEAR, 1, 1), date(YEAR, 12, 31), merged, {6, 7})
print(f"calendar: {len(cal.days)} days, "
      f"{sum(1 for k in cal.kind if k == 'work')} workdays, "
      f"{len(cal.wasted_holidays())} holidays lost to weekends")

# --- stage 1: commitments -------------------------------------------------
commit = make_commitment(cal, date(YEAR, 6, 15), date(YEAR, 6, 17))
print(f"\ncommitment 15-17 Jun -> {commit.label()}: {commit.describe()}")
assert commit.start <= date(YEAR, 6, 15) and commit.end >= date(YEAR, 6, 17)
assert all(cal.kind_of(d) == "work" for d in commit.leave_days)

blocked = blocked_indices(cal, [commit])
after_commit = BUDGET - commit.cost
print(f"blocked {len(blocked)} days, {after_commit} leave left")

# --- stage 2: suggestions must avoid the commitment -----------------------
cands = find_candidates(cal, 4, 3, True, blocked)
assert cands, "no candidates"
for c in cands:
    overlap = set(range(cal.index[c.start], cal.index[c.end] + 1)) & blocked
    assert not overlap, f"candidate {c.label()} overlaps the commitment"
print(f"candidates avoiding commitment: {len(cands)}")

affordable = [c for c in cands if c.cost <= after_commit]
auto = select_plan(cal, affordable, after_commit, 0.35)
chosen = sorted([commit] + auto, key=lambda b: b.start)
s = PlanSummary(chosen, BUDGET)

assert s.leave_used <= BUDGET, f"budget blown: {s.leave_used} > {BUDGET}"
for a, b in zip(chosen, chosen[1:]):
    assert a.end < b.start, f"overlap: {a.label()} / {b.label()}"
for b in chosen:
    assert b.cost == len(b.leave_days)
    assert all(cal.kind_of(d) == "work" for d in b.leave_days)
    assert b.span >= 3
print("invariants: budget OK, no overlaps, leave only on workdays, "
      "commitment preserved")

print(f"\nplan: {len(chosen)} breaks, {s.total_days_off} days off "
      f"for {s.leave_used} leave ({s.overall_leverage:.2f}x)")
for b in chosen:
    mark = " <- committed" if b == commit else ""
    print(f"  {b.label():<18} {b.span:>2}d off / {b.cost} leave{mark}")

print("\ntop 5 by leverage:")
for b in rank_candidates(cands)[:5]:
    print(f"  {b.label():<18} {b.describe():<30} "
          f"bridges: {', '.join(dict.fromkeys(b.reasons)) or '-'}")

# --- stage 3: getaways ----------------------------------------------------
print()
for city in gw.CITIES:
    dests = gw.for_city(city)
    assert dests, f"no getaways for {city}"
    for g in dests:
        assert g.cost_min <= g.cost_max, f"{g.name}: inverted cost band"
        assert g.min_nights <= g.ideal_nights, f"{g.name}: nights inconsistent"
        assert g.best_months, f"{g.name}: no season"
    print(f"  {gw.CITIES[city]:<12} {len(dests):>2} destinations, "
          f"from Rs{min(g.cost_min for g in dests):,}")

longest = s.longest
picks = gw.suggest("BLR", 8000, longest.span - 1, longest.start, season_only=True)
assert all(p.cost_min <= 8000 for p in picks), "over budget in suggestions"
assert all(p.min_nights <= longest.span - 1 for p in picks), "too short a break"
print(f"\nBLR getaways under Rs8,000 for {longest.label()} "
      f"({longest.span - 1}n, {longest.start:%B}): "
      + ", ".join(p.name for p in picks[:5]))

wide = gw.suggest("BLR", 8000, longest.span - 1, longest.start, season_only=False)
assert len(wide) >= len(picks), "season filter should only narrow"

# --- fares + watchlist ----------------------------------------------------
prov = MockFareProvider(peak_dates=set(cal.holiday_names))
qs = sorted(prov.quote_many("BLR", ["GOI", "CMB", "BKK"], longest.start, longest.end),
            key=lambda q: q.price)
assert prov.quote("BLR", "GOI", longest.start).price == \
       prov.quote("BLR", "GOI", longest.start).price, "mock not deterministic"
print("fares: " + ", ".join(f"{q.route} Rs{q.price:,}" for q in qs))

wl = Watchlist()
wl.items.clear()
it = wl.add("BLR", "GOI", longest.start, longest.end, note=longest.label())
it.record(qs[0].price)
it.record(qs[0].price + 500)
assert it.delta == 500 and it.best == qs[0].price
print(f"watchlist: latest {it.latest}, best {it.best}, delta {it.delta}")

# --- export ---------------------------------------------------------------
ics = exporters.to_ics(chosen)
csv_text = exporters.to_csv(chosen)
assert ics.count("BEGIN:VEVENT") == len(chosen)
assert ics.startswith("BEGIN:VCALENDAR") and ics.rstrip().endswith("END:VCALENDAR")
assert len(csv_text.splitlines()) == len(chosen) + 1
print(f"export: .ics {ics.count('BEGIN:VEVENT')} events, "
      f".csv {len(csv_text.splitlines()) - 1} rows")

print("\nALL CHECKS PASSED")
