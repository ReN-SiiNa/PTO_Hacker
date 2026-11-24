# PTO-Hacker -- working notes

Streamlit demo: company holidays + leave balance -> locked commitments -> chosen long
weekends -> affordable getaways. Fully offline, no API keys.

Run: `streamlit run app.py`   (DB path: `PTOHACKER_DB`, default `output/pto.db`)
Verify: `PYTHONIOENCODING=utf-8 python smoke_test.py` (engine)
        `PYTHONIOENCODING=utf-8 python store_test.py` (persistence)

## Layer boundaries -- keep these

- `optimizer.py` is pure: takes a `YearCalendar`, returns `Break` objects. It knows
  nothing about Streamlit, fares, or getaways. Keep it that way -- it is the only part
  worth unit-testing and the only part worth reusing.
- `flights.py` exposes `FareProvider`. The UI and watchlist only ever talk to that
  interface, never to a concrete provider. A real API goes in as a new subclass plus
  one line in `get_provider()`.
- `caldays.py` must not import `sources.py` (sources imports caldays, not the reverse).
- `getaways.py` is data, not logic. Adding a city means adding a list, nothing else.
- `store.py` is the ONLY module that touches SQLite. `app.py` and `watchlist.py`
  call its functions; neither writes SQL. It imports nothing from the app.
- `ui.py` owns every colour, font and HTML fragment. `app.py` composes components and
  never writes raw CSS or hex. A re-theme touches `ui.py` + `.streamlit/config.toml`.

## Decisions already made -- don't re-litigate

- **Email drafting was removed** (was `emails.py`). Asked for and deleted. Don't
  reintroduce it unless the user asks.
- **Holidays on a weekend stay classified `WEEKEND`, not `HOLIDAY`.** They buy no extra
  time off. `YearCalendar.wasted_holidays()` surfaces them.
- **`require_bridge=True` by default.** Without it the DP buys isolated Fridays all
  year: every one is a 3-for-1, so it maximises raw days off and produces a plan nobody
  would act on. Observed, not theorised.
- **`longer_bias` scores a break as `span ** (1 + bias)`.** Raw days-off ties a 9-day
  trip with three long weekends; the bias breaks that tie toward real trips.
- **Selection is exact DP over `(day index, leave remaining)`, not greedy.** 366 x
  budget states, fast enough. Don't "optimise" it into a greedy pass.
- **Getaway costs are hand-researched bands, NOT generated from a fare API.** This was
  a deliberate call: a mock-generated "budget match" is circular -- it filters made-up
  numbers against a budget and looks like a recommendation while containing no
  information. Hand-entered ranges are honest, and they capture the drives and
  overnight trains that dominate real Indian weekend travel. Keep the mock confined to
  the Fare watch tab, clearly labelled synthetic.

## Architecture notes

- **State lives in SQLite, not `st.session_state`.** Session state is per-WebSocket:
  it dies on refresh, reconnect, or restart, and that is disqualifying on a server.
  `store.py` holds settings, company holidays, commitments, accepted breaks and fare
  history. The app reads fresh from the DB every rerun -- a handful of tiny queries,
  cheaper than the reasoning needed to keep a cache honest.
- **Rows store ISO date strings, never `Break` objects.** Breaks are rebuilt from
  those spans each run via `make_commitment()`. This matters: the calendar changes
  when the user edits holidays or the weekend pattern, and a stale pickled `Break`
  would silently disagree with it.
- **Commitments and accepted breaks carry their row id** through the UI, so Remove
  deletes by id. The old code popped by list index, which is wrong the moment
  anything re-sorts.
- **The schema is self-initialising.** `store.connect()` runs the DDL once per
  process behind a lock, so any entry point -- app, test, future poller -- can call
  store functions without remembering `init()` first. This was a real bug, not a
  hypothetical: `smoke_test.py` passed locally only because a database happened to
  exist, and blew up on a clean checkout with `no such table: watch`.
- **One short-lived connection per call** (`store.connect()`). SQLite is fine with
  this and it sidesteps Streamlit's rerun threading entirely -- no cached handle to
  go stale, no `check_same_thread`. Don't "optimise" it into a cached connection.
- **WAL mode is deliberate**: it lets a future background poller write fares while
  the app reads. Keep it.
- **Settings are written only when changed** (`_changed` diff in app.py), so an idle
  rerun does not touch the disk.
- **`make_commitment()` extends outward** across adjacent free days, so re-deriving an
  already-extended range is idempotent. Accepted suggestions round-trip safely.
- **Blocking is by day index**, via `blocked_indices()`. `find_candidates()` skips any
  candidate touching a blocked day, which is what keeps stage-2 suggestions from
  colliding with stage-1 commitments.

## UI / theme

- **Palette is the validated reference palette**, not picked by eye. Categorical
  slots 1-3 (`#2a78d6` blue, `#eb6834` orange, `#1baf7a` aqua) were run through the
  dataviz skill's `validate_palette.py --pairs all --mode light`: all checks pass.
  Aqua measures 2.74:1 on the light surface, so **anything coloured aqua also carries
  a visible text label** ("Free", "Fits this break") -- colour is never the only
  channel. If you add a fourth hue, re-run the validator; don't eyeball it.
- **Colour follows what a break IS, never its position in a sorted list**
  (`ui.accent_for`): blue = committed, orange = costs leave, aqua = free. Re-sorting
  the list must not repaint anything.
- **One hero figure per view** (total days off, 3rem). The other three cells in the
  summary band are stat tiles. Don't add a second hero.
- **The leave meter's track is a lighter step of the same blue ramp** (`#cde2fb`
  under `#2a78d6`), per the meter spec -- not a grey track. It turns green only when
  the balance is fully spent, because here spending it all is the goal.
- **Price history is a single series**, so no legend: the caption names it. Hover
  comes free from Streamlit's Vega layer.
- **Both themes ship.** Streamlit 1.60 does support per-mode theming:
  `[theme.light]`, `[theme.dark]`, and `[theme.light.sidebar]` /
  `[theme.dark.sidebar]`. The viewer's OS setting picks one; Settings ->
  Appearance overrides it. Two keys are **top-level `[theme]` only** and error
  inside the per-mode sections: `base` and `chartCategoricalColors`.
- **Dark is selected, not flipped.** Same hues re-stepped for the dark surface
  (`#3987e5` / `#d95926` / `#199e70` on `#1a1a19`) and re-validated against it:
  all checks pass, including the contrast one that only WARNs in light. Never
  darken the light hexes algorithmically.
- `ui.py` holds two token dicts (`LIGHT`, `DARK`). `inject()` reads
  `st.context.theme.type`, sets the module-level `T`, and emits the matching CSS
  custom properties. **Components must call `ui.c("series_1")`, never a literal
  hex** -- that is what makes them follow the theme. `inject()` has to run before
  anything draws.
- Streamlit has no per-mode *chart* palette, so the one chart passes its colour
  explicitly via `ui.c("series_1")` and gets the right step either way.
- `ui.plural()` exists so the UI never prints "1 night(s)". Use it.

## Gotchas hit while building

- **Streamlit 1.60 renders tabs with React Aria, not BaseWeb.** Every
  `[data-baseweb="tab"]` rule you find online silently matches nothing -- the CSS
  applies cleanly and the UI just doesn't change. The real hooks are
  `[role="tablist"]`, `[data-testid="stTab"]`, `[aria-selected="true"]`, and
  `.react-aria-SelectionIndicator` for the underline. When a style no-ops, dump the
  DOM (`output/dom.py` does this via Playwright) instead of guessing again.
- `st.dataframe` goes through Arrow: a column must not mix types. Leverage renders as
  `"3.00x"` / `"free"` strings for that reason.
- `use_container_width` is deprecated -- use `width="stretch"`.
- Windows console is cp1252; scripts printing en-dashes or arrows need
  `PYTHONIOENCODING=utf-8`. The app itself is unaffected.
- Don't name a module `calendar.py` or `holidays.py` -- both shadow things we import.
- Writing files via bash heredoc mangled backslash escapes; use the Write tool for
  anything containing escape sequences.
- `taskkill` is blocked by the permission classifier here, so a stale Streamlit server
  can't be killed -- start a new one on a different port instead.

## Packaging & deployment

- **The repo is the product now** -- someone clones it, runs it locally, deploys it
  to their own VPS. Anything needed for that must be tracked, which is why
  screenshots live in `docs/` and dev tooling in `scripts/`. `output/` is gitignored
  runtime state: never put anything there that a cloner needs.
- **`bash scripts/clean_clone_check.sh` is the gate before claiming the repo works.**
  It copies only tracked files to a temp dir, builds a fresh virtualenv, installs
  `requirements.txt`, runs both suites and boots the app with no pre-existing DB.
  It resolves whatever Streamlit is newest, which is how the 1.60-vs-1.67 question
  gets answered -- the custom tab CSS was verified against 1.67 this way.
- **`streamlit>=1.60` is a hard floor**, not caution: the app uses per-mode theme
  config, `st.context.theme`, `width="stretch"` and React-Aria tab markup.
- **The Docker image has never been built** -- there is no Docker on the dev machine.
  The Compose file parses and the Dockerfile is conventional, but do not describe it
  as tested. Say so in DEPLOY.md and to the user.
- **Streamlit binds every interface by default** (`server.address` is unset). Every
  deployment path here pins `127.0.0.1` or keeps the container port on loopback, with
  Caddy the only public listener. Do not "simplify" that away.
- **Nothing may phone home.** Two leaks were found and closed: Streamlit's
  `gatherUsageStats` defaults to TRUE (now false in `.streamlit/config.toml`, not
  just in the Dockerfile CMD), and `ui.py` imported Inter from Google Fonts, which
  hit Google on every page load. Don't reintroduce a CDN font, analytics, or any
  runtime HTTP call -- "no network calls" is a claim the README makes.
- **Backups must use SQLite's `.backup`, not `cp`** -- WAL means recent writes may sit
  in `pto.db-wal` and a plain copy can be torn.

## Background worker

- **`planning.build()` is the single source of truth for "what is my plan".** The
  UI and the jobs both call it. If they ever compute it separately they will
  disagree, and a digest that contradicts the screen is the worst possible bug for
  this product.
- **Jobs never touch the notifier.** They return a `JobResult`; `daemon.run_job`
  logs it and delivers. Keeps jobs testable with no network.
- **Only speak when there is something to say.** Every alert is fingerprinted in
  `alerts_sent`. A job that reports "nothing changed" daily gets muted, and a muted
  channel is a dead feature.
- **Thresholds take the TIGHTEST reached value**, via `min(... if days <= d)`.
  Taking the first match of a descending tuple was a real bug: the alert fired once
  at the loosest threshold and the fingerprint then suppressed every escalation.
  The `<=` form also survives the daemon being down for a few days.
- **`check_fares` prunes watches whose departure has passed.** Real providers
  return "not found" for past dates, so without this a long-running daemon reports
  a failure every morning forever.
- **A delivery failure must not void the job's work** -- `run_job` records the run
  as done with the failure noted, and never re-runs the work just to re-send.
- **TZ matters.** The daemon schedules by local hour and containers default to UTC,
  so compose sets `TZ`. Without it an "08:00" digest lands at 13:30 IST.
- Graceful SIGTERM shutdown is written for Linux and **unverified** -- Windows does
  not deliver POSIX signals the same way, so the dev machine cannot test it.

## Holiday data caveat

`data/holidays_IN_2026.json` carries a `confidence` field. Lunar and Islamic dates
(Eid, Muharram, Diwali) are estimates and shift with moon sighting. The `holidays`
library backend is more reliable; the curated file exists so a company-specific
calendar can be hand-edited. Never present either as authoritative.
