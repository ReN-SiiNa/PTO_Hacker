"""PTO-Hacker -- Streamlit demo.

A three-stage funnel:
    1. Lock in dates you have already committed to.
    2. Pick long weekends from what your remaining balance can buy.
    3. Match each break to a getaway you can afford from your city.

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

import envfile

envfile.load()

import config as cfg  # noqa: E402
import exporters  # noqa: E402
import getaways as gw
import jobs as job_module
import notify
import sources
import store
import ui
from caldays import Holiday, YearCalendar
from flights import AIRPORTS, MockFareProvider
from optimizer import (
    PlanSummary,
    blocked_indices,
    find_candidates,
    make_commitment,
    rank_candidates,
    select_plan,
)
from watchlist import Watchlist

INF = "∞"
RUPEE = "₹"
DASH = "—"
ARROW = "→"
TIMES = "×"

st.set_page_config(page_title=cfg.APP_TITLE, layout="wide")
ui.inject()


# ---------------------------------------------------------------- state
@st.cache_resource
def _bootstrap() -> dict:
    """Create the schema and import any legacy JSON. Runs once per process."""
    store.init()
    moved = store.migrate_watchlist_json(Path(__file__).parent / "output" / "watchlist.json")
    return {"migrated": moved, "db": str(store.DB_PATH)}


_boot = _bootstrap()
SAVED = store.all_settings()


@st.cache_data(show_spinner=False)
def _holidays_from_library(country: str, year: int, subdiv: str | None):
    return sources.from_library(country, year, subdiv)


@st.cache_data(show_spinner=False)
def _holidays_from_file(path: str):
    return sources.from_file(path)


def _watchlist() -> Watchlist:
    """Fresh view each rerun -- SQLite is the source of truth, not the session."""
    return Watchlist()


def _money(v) -> str:
    if v is None:
        return DASH
    sign = "-" if v < 0 else ""
    return f"{sign}{RUPEE}{abs(v):,}"


def _leverage_text(b) -> str:
    return "free" if b.is_free else f"{b.leverage:.1f}{TIMES}"


def _idx(options: list, value, fallback: int = 0) -> int:
    """Index of a saved selection, falling back when it is no longer offered."""
    try:
        return options.index(value)
    except (ValueError, TypeError):
        return fallback


def _parse_pasted(text: str, year: int) -> tuple[list[dict], list[str]]:
    """Parse 'YYYY-MM-DD, Name' lines. Returns (rows, errors)."""
    rows, errs = [], []
    for raw in text.splitlines():
        line = raw.strip().strip(",")
        if not line or line.lower().startswith(("date", "#")):
            continue
        parts = [p.strip() for p in line.replace("\t", ",").split(",", 1)]
        try:
            d = date.fromisoformat(parts[0])
        except ValueError:
            errs.append(f"{raw.strip()}  (date must be YYYY-MM-DD)")
            continue
        if d.year != year:
            errs.append(f"{raw.strip()}  (not in {year})")
            continue
        rows.append({"date": d.isoformat(),
                     "name": parts[1] if len(parts) > 1 and parts[1] else "Company holiday"})
    return rows, errs


# ---------------------------------------------------------------- sidebar
st.sidebar.markdown(
    '<div class="ph-label" style="margin-bottom:.8rem">Setup</div>',
    unsafe_allow_html=True,
)

year = int(st.sidebar.number_input(
    "Year", 2024, 2035, SAVED.get("year", cfg.DEFAULT_YEAR), step=1
))

curated_files = sources.curated_files()
source_opts = []
if sources.HAS_PYHOLIDAYS:
    source_opts.append("holidays library")
if curated_files:
    source_opts.append("curated file")
if not source_opts:
    st.error("No holiday source available. `pip install holidays` or add a file to data/.")
    st.stop()

source = st.sidebar.radio(
    "Statutory holidays", source_opts, horizontal=True,
    index=_idx(source_opts, SAVED.get("source"), 0),
)

note = ""
if source == "holidays library":
    country = st.sidebar.text_input(
        "Country code", SAVED.get("country", cfg.DEFAULT_COUNTRY)
    ).strip().upper()
    subs = sources.subdivisions(country)
    _sub_opts = ["(national only)"] + subs
    subdiv = st.sidebar.selectbox(
        "State / subdivision", _sub_opts,
        index=_idx(_sub_opts, SAVED.get("subdiv"), 0),
    )
    subdiv = None if subdiv == "(national only)" else subdiv
    try:
        statutory = _holidays_from_library(country, year, subdiv)
    except Exception as exc:
        st.sidebar.error(f"Could not load {country}: {exc}")
        st.stop()
else:
    choice = st.sidebar.selectbox("File", curated_files, format_func=lambda p: p.name)
    statutory, note = _holidays_from_file(str(choice))
    scopes = sorted({h.scope for h in statutory})
    keep = st.sidebar.multiselect(
        "Include scopes", scopes, default=[s for s in scopes if s != "optional"]
    )
    statutory = [h for h in statutory if h.scope in keep]

use_statutory = st.sidebar.checkbox(
    "Use statutory list", value=SAVED.get("use_statutory", True),
    help="Turn off to plan against your company calendar alone.",
)

st.sidebar.divider()
balance = st.sidebar.slider(
    "Leave balance (days)", 0, 40, SAVED.get("balance", cfg.DEFAULT_LEAVE_BALANCE)
)
_wk = list(cfg.WEEKEND_PRESETS)
weekend_name = st.sidebar.selectbox(
    "Weekend", _wk, index=_idx(_wk, SAVED.get("weekend"), 0)
)
_cities = list(gw.CITIES)
home_city = st.sidebar.selectbox(
    "Home city", _cities, index=_idx(_cities, SAVED.get("home_city"), 0),
    format_func=lambda c: f"{gw.CITIES[c]} ({c})",
)
leave_year_end = st.sidebar.text_input(
    "Leave year ends (MM-DD)", SAVED.get("leave_year_end", "12-31"),
    help="When unused leave lapses. The background job warns you before it does.",
).strip()

with st.sidebar.expander("Optimizer settings"):
    max_per_break = st.slider(
        "Max leave per break", 1, 10,
        SAVED.get("max_per_break", cfg.DEFAULT_MAX_LEAVE_PER_BREAK),
    )
    min_span = st.slider(
        "Minimum days off to count", 3, 10,
        SAVED.get("min_span", cfg.DEFAULT_MIN_SPAN),
    )
    require_bridge = st.checkbox(
        "Only breaks that bridge a holiday",
        value=SAVED.get("require_bridge", True),
        help="Off = may also buy isolated Fridays for plain 3-day weekends.",
    )
    longer_bias = st.slider(
        "Prefer fewer, longer breaks", 0.0, 0.8,
        SAVED.get("longer_bias", cfg.DEFAULT_LONGER_BIAS), 0.05
    )

# Persist the sidebar so reopening the app looks like you left it. Only writes
# the keys that actually changed, so an idle rerun touches the disk not at all.
_current = {
    "year": year, "source": source, "use_statutory": use_statutory,
    "balance": balance, "weekend": weekend_name, "home_city": home_city,
    "max_per_break": max_per_break, "min_span": min_span,
    "require_bridge": require_bridge, "longer_bias": longer_bias,
    "leave_year_end": leave_year_end,
}
if source == "holidays library":
    _current |= {"country": country, "subdiv": subdiv}
_changed = {k: v for k, v in _current.items() if SAVED.get(k) != v}
if _changed:
    store.set_settings(_changed)
    SAVED.update(_changed)

# ---------------------------------------------------------------- calendar
company_rows = store.company_holidays(year)
company = [
    Holiday(day=date.fromisoformat(h["date"]), name=h["name"],
            scope="company", confidence="high")
    for h in company_rows
]
all_holidays = sources.merge(company, statutory if use_statutory else [])

cal = YearCalendar(
    date(year, 1, 1), date(year, 12, 31),
    all_holidays, cfg.WEEKEND_PRESETS[weekend_name],
)

# Rebuild stored date ranges against the current calendar.
commitments, accepted = [], []
for c in store.commitments(year):
    s, e = date.fromisoformat(c["start"]), date.fromisoformat(c["end"])
    commitments.append((make_commitment(cal, s, e), c["label"], c["id"]))
for a in store.accepted(year):
    s, e = date.fromisoformat(a["start"]), date.fromisoformat(a["end"])
    accepted.append((make_commitment(cal, s, e), a["id"]))

committed_breaks = [b for b, _, _ in commitments]
accepted_breaks = [b for b, _ in accepted]
chosen = committed_breaks + accepted_breaks
spent = sum(b.cost for b in chosen)
remaining = max(0, balance - spent)
blocked = blocked_indices(cal, chosen)

candidates = find_candidates(cal, max_per_break, min_span, require_bridge, blocked)
affordable = [c for c in candidates if c.cost <= remaining]
summary = PlanSummary(sorted(chosen, key=lambda b: b.start), balance)

# ---------------------------------------------------------------- header
ui.masthead("PTO Hacker", cfg.APP_TAGLINE, str(year))

ui.summary_band(
    hero_value=summary.total_days_off,
    hero_unit="days",
    hero_sub=f"across {ui.plural(len(chosen), 'break')}" if chosen else "nothing planned yet",
    used=spent,
    total=balance,
    leverage=f"{summary.overall_leverage:.1f}{TIMES}" if spent else DASH,
    leverage_sub="days off per leave day",
    holidays=len(cal.holiday_names),
    holidays_sub=f"{len(company)} from your company" if company
                 else "statutory only",
)
(tab_hol, tab_commit, tab_weekends, tab_away, tab_fare, tab_activity,
 tab_export) = st.tabs(
    ["Holidays", "Commitments", "Long weekends", "Getaways",
     "Fare watch", "Activity", "Export"]
)

# ---------------------------------------------------------------- holidays
with tab_hol:
    st.subheader("Your company's holiday calendar")
    ui.note("Statutory lists rarely match what your employer actually gives you. "
            "Add your company's list here - it merges with, or replaces, the statutory one.")

    col_add, col_bulk = st.columns(2)

    with col_add:
        st.markdown("**Add one**")
        d = st.date_input("Date", value=date(year, 1, 1),
                          min_value=date(year, 1, 1), max_value=date(year, 12, 31),
                          key="add_hol_date")
        nm = st.text_input("Name", "", key="add_hol_name",
                           placeholder="e.g. Founder's Day")
        if st.button("Add holiday", width="stretch"):
            store.add_company_holidays(
                year, [{"date": d.isoformat(),
                        "name": nm.strip() or "Company holiday"}]
            )
            st.rerun()

    with col_bulk:
        st.markdown("**Paste or upload a list**")
        up = st.file_uploader("CSV with date,name per row", type=["csv", "txt"])
        pasted = st.text_area(
            "One per line: `2026-03-04, Holi`", height=120, key="paste_hols",
            placeholder="2026-03-04, Holi\n2026-10-20, Dussehra",
        )
        text = pasted
        if up is not None:
            text = (text + "\n" + up.getvalue().decode("utf-8", "replace")).strip()
        if st.button("Import", type="primary", width="stretch"):
            rows, errs = _parse_pasted(text, year)
            added = store.add_company_holidays(year, rows)
            dupes = len(rows) - added
            if added:
                st.success(f"Imported {ui.plural(added, 'date')}.")
            if dupes:
                st.info(f"{ui.plural(dupes, 'date')} already on the list.")
            if errs:
                st.warning("Skipped:\n\n" + "\n\n".join(f"- `{e}`" for e in errs[:10]))
            if added:
                st.rerun()

    if company_rows:
        st.divider()
        st.markdown("**Company holidays added**")
        for i, h in enumerate(company_rows):
            hd = date.fromisoformat(h["date"])
            weekendy = hd.isoweekday() in cfg.WEEKEND_PRESETS[weekend_name]
            cols = st.columns([3, 4, 2, 1])
            cols[0].write(f"{hd:%a, %d %b %Y}")
            cols[1].write(h["name"])
            cols[2].write(":grey[falls on a weekend]" if weekendy else "")
            if cols[3].button("Remove", key=f"delhol{i}"):
                store.remove_company_holiday(year, h["date"])
                st.rerun()
        if st.button("Clear all company holidays"):
            store.clear_company_holidays(year)
            st.rerun()

    st.divider()
    if note:
        st.info(note)
    st.markdown(f"**All {len(all_holidays)} holidays in play**")
    st.dataframe(
        [{"Date": h.day.isoformat(), "Day": h.day.strftime("%a"), "Name": h.name,
          "Source": "company" if h.scope == "company" else "statutory",
          "Usable": "no - weekend" if cal.kind_of(h.day) != "holiday" else "yes"}
         for h in all_holidays],
        width="stretch", hide_index=True, height=320,
    )
    wasted = cal.wasted_holidays()
    if wasted:
        st.caption(f"{ui.plural(len(wasted), 'holiday')} "
                   f"{'falls' if len(wasted) == 1 else 'fall'} on a weekend "
                   "and buy you nothing.")

# ------------------------------------------------------------ commitments
with tab_commit:
    st.subheader("Dates you already know you're taking")
    ui.note("A wedding, a visa appointment, a trip already booked. These lock in first "
            "and everything else plans around them, regardless of leverage.")

    col_a, col_b, col_c = st.columns([2, 2, 3])
    cs = col_a.date_input("From", value=date(year, 1, 1),
                          min_value=date(year, 1, 1), max_value=date(year, 12, 31),
                          key="com_start")
    ce = col_b.date_input("To", value=date(year, 1, 1),
                          min_value=date(year, 1, 1), max_value=date(year, 12, 31),
                          key="com_end")
    cl = col_c.text_input("What is it?", "", key="com_label",
                          placeholder="e.g. Cousin's wedding")

    if cs > ce:
        st.warning("'From' is after 'To'.")
    else:
        preview = make_commitment(cal, cs, ce)
        over_budget = preview.cost > remaining
        st.write(
            f"Costs **{ui.plural(preview.cost, 'leave day')}** and gives you "
            f"**{preview.span} days off** ({preview.label()})."
            + (f" You only have {remaining} left." if over_budget else "")
        )
        if st.button("Lock these dates in", type="primary", disabled=over_budget):
            store.add_commitment(year, cs, ce, cl.strip() or "Commitment")
            st.rerun()

    st.divider()
    if not commitments:
        st.info("Nothing locked in yet. Skip this step if you have no fixed dates.")
    else:
        for i, (b, label, row_id) in enumerate(commitments):
            with st.container(border=True):
                cols = st.columns([5, 3, 2])
                tags = ["Locked in"] + list(dict.fromkeys(b.reasons))
                cols[0].markdown(
                    ui.card_head(label, b.label(), ui.c("series_1"),
                                 ui.chips(tags, mark=ui.c("series_1"))),
                    unsafe_allow_html=True,
                )
                cols[1].markdown(
                    ui.span_figure(b.span, b.describe()), unsafe_allow_html=True
                )
                if cols[2].button("Remove", key=f"delcom{i}", width="stretch"):
                    store.remove_commitment(row_id)
                    st.rerun()

# --------------------------------------------------------------- weekends
with tab_weekends:
    st.subheader(f"Long weekends you can still buy with {remaining} leave days")

    if remaining <= 0:
        st.info("No leave left. Remove a commitment or raise your balance.")
    elif not affordable:
        st.warning(
            "Nothing fits. Loosen the optimizer settings in the sidebar "
            "(lower the minimum span, or allow breaks that don't bridge a holiday)."
        )
    else:
        bar1, bar2 = st.columns([3, 2])
        bar1.caption(
            f"{len(affordable)} options, best value first. Accept the ones you want "
            "-- the rest recompute against what's left."
        )
        if bar2.button("Auto-fill best combination", type="primary", width="stretch"):
            store.add_accepted_many(
                year,
                [(b.start, b.end)
                 for b in select_plan(cal, affordable, remaining, longer_bias)],
            )
            st.rerun()

        sort_by = st.radio("Sort by", ["Leverage", "Longest", "Date"],
                           horizontal=True, key="wk_sort")
        if sort_by == "Leverage":
            shown = rank_candidates(affordable)
        elif sort_by == "Longest":
            shown = sorted(affordable, key=lambda b: (-b.span, b.cost))
        else:
            shown = sorted(affordable, key=lambda b: b.start)

        for i, b in enumerate(shown[:40]):
            with st.container(border=True):
                cols = st.columns([5, 3, 2])
                accent = ui.accent_for(b)
                cost_tag = "Costs nothing" if b.is_free else ui.plural(b.cost, "leave day")
                tags = [cost_tag] + list(dict.fromkeys(b.reasons))
                cols[0].markdown(
                    ui.card_head(b.label(), f"{_leverage_text(b)} leverage", accent,
                                 ui.chips(tags, mark=accent)),
                    unsafe_allow_html=True,
                )
                leave_txt = (", ".join(d.strftime("%d %b") for d in b.leave_days)
                             if b.leave_days else "no leave needed")
                cols[1].markdown(
                    ui.span_figure(b.span, f"Leave: {leave_txt}"),
                    unsafe_allow_html=True,
                )
                if cols[2].button("Add to plan", key=f"acc{i}", width="stretch"):
                    store.add_accepted(year, b.start, b.end)
                    st.rerun()
        if len(shown) > 40:
            st.caption(f"Showing the top 40 of {len(shown)}.")

    st.divider()
    st.subheader("Accepted")
    if not accepted:
        st.caption("Nothing accepted yet.")
    else:
        for i, (b, row_id) in enumerate(accepted):
            cols = st.columns([5, 3, 2])
            cols[0].markdown(
                ui.card_head(b.label(), b.describe(), ui.accent_for(b)),
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                ui.chips(["Free" if b.is_free else ui.plural(b.cost, "leave day")],
                         mark=ui.accent_for(b)),
                unsafe_allow_html=True,
            )
            if cols[2].button("Remove", key=f"delacc{i}", width="stretch"):
                store.remove_accepted(row_id)
                st.rerun()
        if st.button("Clear accepted"):
            store.clear_accepted(year)
            st.rerun()

# --------------------------------------------------------------- getaways
with tab_away:
    st.subheader(f"Where to go from {gw.CITIES[home_city]}")
    ui.note("Hand-curated destinations with realistic cost bands for one person "
            "(travel + stay + food). Typical ranges, not live quotes - and they include "
            "the drives and overnight trains a flight search would never show you.")

    if not chosen:
        st.info("Lock in a commitment or accept a long weekend first.")
    else:
        pick = st.selectbox(
            "Break", sorted(chosen, key=lambda b: b.start),
            format_func=lambda b: f"{b.label()}  ({b.span} days)",
        )
        nights = pick.span - 1
        colb, cols_ = st.columns([3, 2])
        budget = colb.slider("Budget per person", 1500, 25000,
                             cfg.DEFAULT_GETAWAY_BUDGET, 500, format=f"{RUPEE}%d")
        season_only = cols_.checkbox("Only destinations in season", value=True)

        picks = gw.suggest(home_city, budget, nights, pick.start, season_only)
        st.write(
            f"**{len(picks)}** of {len(gw.for_city(home_city))} destinations fit "
            f"{ui.plural(nights, 'night')} under {_money(budget)}"
            + (f" and are good in {pick.start:%B}." if season_only else ".")
        )
        if not picks:
            st.warning("Nothing fits. Raise the budget or untick the season filter.")

        for g in picks:
            with st.container(border=True):
                cols = st.columns([4, 3, 3])
                roomy = nights >= g.ideal_nights
                accent = ui.c("series_3") if roomy else ui.c("series_2")
                cols[0].markdown(
                    ui.card_head(g.name, g.region, accent,
                                 ui.chips(list(g.tags))),
                    unsafe_allow_html=True,
                )
                cols[1].markdown(
                    f'<div class="ph-value">{g.cost_band}</div>'
                    f'<div class="ph-sub">per person, all in</div>'
                    + ui.chips([g.travel_text]),
                    unsafe_allow_html=True,
                )
                fit = ("Fits this break" if roomy
                       else f"Tight — {ui.plural(g.ideal_nights, 'night')} is better")
                cols[2].markdown(
                    f'<div class="ph-sub"><b>{ui.plural(g.ideal_nights, "night")} '
                    f'ideal</b></div>'
                    + ui.chips([fit], mark=accent)
                    + (f'<div class="ph-sub">{g.note}</div>' if g.note else ""),
                    unsafe_allow_html=True,
                )

        with st.expander(f"All {len(gw.for_city(home_city))} destinations from "
                         f"{gw.CITIES[home_city]}"):
            st.dataframe(
                [{"Destination": g.name, "Region": g.region,
                  "Distance": f"{g.distance_km} km", "Travel": g.mode,
                  "Ideal nights": g.ideal_nights, "Typical cost": g.cost_band,
                  "Tags": ", ".join(g.tags)}
                 for g in gw.for_city(home_city)],
                width="stretch", hide_index=True,
            )

# ------------------------------------------------------------- fare watch
with tab_fare:
    ui.note("Flight fares come from a deterministic mock provider. The numbers are "
            "synthetic; the watch loop is real. Swap in a live adapter and nothing "
            "else changes.")
    provider = MockFareProvider(peak_dates=set(cal.holiday_names))
    home_air = st.selectbox(
        "From", list(AIRPORTS),
        index=list(AIRPORTS).index(home_city if home_city in AIRPORTS
                                   else cfg.DEFAULT_HOME_AIRPORT),
        format_func=lambda c: f"{c} {DASH} {AIRPORTS[c]}",
    )

    if chosen:
        pick2 = st.selectbox(
            "Break", sorted(chosen, key=lambda b: b.start),
            format_func=lambda b: f"{b.label()} {DASH} {b.span} days", key="farebrk",
        )
        dests = st.multiselect(
            "Destinations", [c for c in AIRPORTS if c != home_air],
            default=[d for d in cfg.DEFAULT_DESTINATIONS if d != home_air],
            format_func=lambda c: f"{c} {DASH} {AIRPORTS[c]}",
        )
        if dests:
            quotes = sorted(provider.quote_many(home_air, dests, pick2.start, pick2.end),
                            key=lambda q: q.price)
            st.dataframe(
                [{"Route": q.route, "To": AIRPORTS[q.destination],
                  "Out": q.depart.isoformat(),
                  "Back": q.ret.isoformat() if q.ret else DASH,
                  "Return fare": _money(q.price)} for q in quotes],
                width="stretch", hide_index=True,
            )
            add = st.selectbox("Add to fare watch", quotes,
                               format_func=lambda q: f"{q.route} {DASH} {_money(q.price)}")
            if st.button("Watch this route", type="primary"):
                wl = _watchlist()
                item = wl.add(add.origin, add.destination, add.depart, add.ret,
                              note=pick2.label())
                item.record(add.price)
                wl.save()
                st.success(f"Watching {add.route} for {pick2.label()}.")
    else:
        st.info("Plan a break first.")

    st.divider()
    st.subheader("Watchlist")
    wl = _watchlist()
    rows = wl.as_rows()
    if not rows:
        st.caption("Empty.")
    else:
        st.dataframe(
            [{k: (_money(v) if k in ("Latest", "Best seen", "Change") else v)
              for k, v in r.items() if k != "_key"} for r in rows],
            width="stretch", hide_index=True,
        )
        ca, cb = st.columns(2)
        if ca.button("Refresh prices"):
            n, failures = wl.refresh(provider)
            if n:
                st.success(f"Re-quoted {ui.plural(n, 'route')}.")
            for f in failures:
                st.warning(f"Could not price {f}")
            if n:
                st.rerun()
        drop = cb.selectbox("Remove", [r["_key"] for r in rows])
        if cb.button("Remove selected"):
            wl.remove(drop)
            wl.save()
            st.rerun()
        sel = st.selectbox(
            "Price history", [r["_key"] for r in rows],
            format_func=lambda k: f"{wl.items[k].origin}{ARROW}{wl.items[k].destination}",
        )
        pts = wl.items[sel].history
        if len(pts) > 1:
            # Single series: no legend needed, the title names it. Hover comes
            # free with Streamlit's Vega layer.
            st.line_chart(
                [{"Check": i + 1, "Fare": p.price} for i, p in enumerate(pts)],
                x="Check", y="Fare", color=ui.c("series_1"), height=240,
            )
            st.caption(
                f"Best seen {_money(wl.items[sel].best)} over "
                f"{len(pts)} checks · fares are synthetic"
            )
        else:
            st.caption("Refresh a few times to build history.")

# -------------------------------------------------------------- activity
with tab_activity:
    st.subheader("What the server did while you were away")
    ui.note(
        "This is the point of running it on a server rather than a laptop. "
        "Working software that is working correctly looks exactly like software "
        "doing nothing — this is the evidence."
    )

    notifier = notify.get_notifier()
    provider_name = os.environ.get("PTOHACKER_FARES", "mock")
    since = (date.today() - timedelta(days=30)).isoformat()
    counts = store.run_counts(since)
    total = sum(counts.values())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Runs, last 30 days", total)
    k2.metric("Alerts sent", sum(1 for r in store.recent_runs(500) if r["notified"]))
    k3.metric("Channel", notifier.name,
              "ready" if notifier.configured else "not configured",
              delta_color="off")
    k4.metric("Fare source", provider_name,
              "real prices" if provider_name == "google" else "synthetic",
              delta_color="off")

    if not notifier.configured:
        st.warning(
            "No notification channel configured, so alerts are recorded here but "
            "not delivered. Set PTOHACKER_NOTIFY=telegram with "
            "PTOHACKER_TELEGRAM_TOKEN and PTOHACKER_TELEGRAM_CHAT_ID.",
        )

    st.markdown("**Scheduled jobs**")
    for name, rule in job_module.SCHEDULE.items():
        last = store.last_run(name)
        cols = st.columns([2, 3, 3, 2])
        when = "monthly on the 1st" if rule["every"] == "monthly" else "daily"
        cols[0].markdown(f"**{name}**")
        cols[1].caption(f"{when} from {rule.get('hour', 0):02d}:00")
        if last:
            cols[2].caption(f"{last['started_at'].replace('T', ' ')} "
                            f"· {last['status']} · {last['detail'][:40]}")
        else:
            cols[2].caption("never run")
        if cols[3].button("Run now", key=f"runjob{name}", width="stretch"):
            with st.spinner(f"running {name}..."):
                run_id = store.start_run(name)
                try:
                    res = job_module.JOBS[name]()
                    sent = False
                    if res.should_notify and notifier.configured:
                        try:
                            notifier.send(res.message, title=f"PTO-Hacker · {name}")
                            sent = True
                        except notify.NotifyError as exc:
                            st.error(f"Delivery failed: {exc}")
                    store.finish_run(run_id, res.status, res.detail, sent)
                    st.success(f"{name}: {res.status} — {res.detail}")
                    if res.message:
                        st.code(res.message, language=None, wrap_lines=True)
                        if not sent:
                            st.caption("Not delivered — no channel configured.")
                except Exception as exc:
                    store.finish_run(run_id, "error", str(exc)[:300])
                    st.error(f"{name} failed: {exc}")
            st.rerun()

    st.divider()
    st.markdown("**Recent runs**")
    runs = store.recent_runs(60)
    if not runs:
        st.caption("Nothing yet. Start the worker with `python daemon.py`, or "
                   "use Run now above.")
    else:
        st.dataframe(
            [{"When": r["started_at"].replace("T", " "),
              "Job": r["job"],
              "Result": r["status"],
              "Detail": r["detail"],
              "Notified": "yes" if r["notified"] else ""}
             for r in runs],
            width="stretch", hide_index=True, height=340,
        )

# ---------------------------------------------------------------- export
with tab_export:
    plan = sorted(chosen, key=lambda b: b.start)
    if not plan:
        st.info("Nothing to export yet.")
    else:
        st.write(
            f"**{len(plan)} breaks** {DASH} {summary.total_days_off} days off "
            f"for {spent} leave days ({summary.overall_leverage:.1f}{TIMES})."
        )
        ics = exporters.to_ics(plan, f"{cfg.APP_TITLE} {year}")
        csv_text = exporters.to_csv(plan)
        ca, cb = st.columns(2)
        ca.download_button("Download calendar (.ics)", ics, file_name=f"pto-{year}.ics",
                           mime="text/calendar", type="primary", width="stretch")
        cb.download_button("Download plan (.csv)", csv_text, file_name=f"pto-{year}.csv",
                           mime="text/csv", width="stretch")
        st.caption("All-day transparent events; imports into Google, Outlook or Apple.")
        st.code(csv_text, language="text")
