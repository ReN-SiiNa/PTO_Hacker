"""Presentation layer: design tokens, CSS, and the small components the app draws.

Colours come from the validated reference palette. Roles are declared once as CSS
custom properties and referenced by name, so a re-theme touches this file only.

Figure contracts followed here (dataviz skill, marks-and-anatomy):
  - Hero figure: one per view, >=48px, same sans as everything else.
  - Stat tile: label (sentence case) / value (semibold, compact) / optional delta.
  - Meter: fill in the accent, unfilled track a LIGHTER STEP OF THE SAME RAMP.
  - Text wears text tokens, never the series colour; a coloured mark sits beside it.
"""
from __future__ import annotations

import html

import streamlit as st

# ----------------------------------------------------------------- tokens
# Dark is SELECTED, not an automatic flip: the same hues re-stepped for the dark
# surface, then re-validated against it. See .streamlit/config.toml for the runs.
LIGHT: dict[str, str] = {
    "series_1": "#2a78d6",   # blue   - accent, committed breaks, the price line
    "series_2": "#eb6834",   # orange - breaks that cost leave
    "series_3": "#1baf7a",   # aqua   - free breaks (label-backed: 2.74:1)
    "ramp_100": "#cde2fb",   # lighter step of the blue ramp -> meter track
    "good": "#0ca30c",
    "warning": "#fab219",
    "critical": "#d03b3b",
    "surface": "#fcfcfb",
    "plane": "#f9f9f7",
    "ink": "#0b0b0b",
    "ink_2": "#52514e",
    "ink_muted": "#898781",
    "hairline": "#e1e0d9",
    "hover": "rgba(11, 11, 11, .05)",
    "ring": "rgba(11, 11, 11, .12)",
    "track_shadow": "rgba(11, 11, 11, .03)",
}

DARK: dict[str, str] = {
    "series_1": "#3987e5",
    "series_2": "#d95926",
    "series_3": "#199e70",
    "ramp_100": "#1c3a5c",   # dark-surface equivalent of the same blue ramp
    "good": "#0ca30c",
    "warning": "#fab219",
    "critical": "#d03b3b",
    "surface": "#1a1a19",
    "plane": "#0d0d0d",
    "ink": "#f0efec",
    "ink_2": "#c3c2b7",
    "ink_muted": "#898781",
    "hairline": "#2c2c2a",
    "hover": "rgba(255, 255, 255, .07)",
    "ring": "rgba(0, 0, 0, .45)",
    "track_shadow": "rgba(0, 0, 0, .25)",
}

# Replaced by inject() on every rerun, before any component draws.
T: dict[str, str] = LIGHT


def theme_type() -> str:
    """'dark' or 'light' -- follows the OS setting and the app's Appearance menu."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


def c(name: str) -> str:
    """A token's hex for the ACTIVE theme. Use this, never a literal."""
    return T[name]


def _css(t: dict[str, str]) -> str:
    return f"""
<style>
/* No webfont import on purpose: it would make every page load request a
   stylesheet from Google, leaking the viewer's IP and referer. The font
   stack in .streamlit/config.toml uses Inter when it is installed locally
   and falls back to the OS UI font otherwise. To get Inter everywhere,
   self-host the woff2 files and declare them with [[theme.fontFaces]]. */

:root {{
  --series-1: {t['series_1']};
  --series-2: {t['series_2']};
  --series-3: {t['series_3']};
  --ramp-100: {t['ramp_100']};
  --good: {t['good']};
  --warning: {t['warning']};
  --critical: {t['critical']};
  --surface: {t['surface']};
  --plane: {t['plane']};
  --ink: {t['ink']};
  --ink-2: {t['ink_2']};
  --ink-muted: {t['ink_muted']};
  --hairline: {t['hairline']};
  --hover: {t['hover']};
  --ring: {t['ring']};
  --track-shadow: {t['track_shadow']};
}}

/* ---- page frame ---- */
.block-container {{ padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1180px; }}
#MainMenu, footer {{ visibility: hidden; }}

html, body, [class*="st-"], button, input, textarea {{
  font-feature-settings: "cv05" 1, "ss01" 1;
}}

h1, h2, h3 {{ letter-spacing: -0.018em; }}
h1 {{ font-weight: 700; }}

/* ---- masthead ---- */
.ph-masthead {{
  display: flex; align-items: baseline; gap: .75rem;
  padding-bottom: .35rem; margin-bottom: 1.25rem;
  border-bottom: 1px solid var(--hairline);
}}
.ph-wordmark {{
  font-size: 1.55rem; font-weight: 700; letter-spacing: -0.03em; color: var(--ink);
}}
.ph-wordmark span {{ color: var(--series-1); }}
.ph-tagline {{ font-size: .9rem; color: var(--ink-muted); }}
.ph-year {{
  margin-left: auto; font-size: .78rem; font-weight: 600; letter-spacing: .04em;
  color: var(--ink-2); background: var(--plane); border: 1px solid var(--hairline);
  padding: .2rem .6rem; border-radius: 999px;
}}

/* ---- summary band ---- */
.ph-band {{
  display: grid; grid-template-columns: 1.35fr 1fr 1fr 1fr; gap: 1px;
  background: var(--hairline); border: 1px solid var(--hairline);
  border-radius: 14px; overflow: hidden; margin-bottom: .5rem;
}}
.ph-cell {{ background: var(--surface); padding: 1rem 1.15rem; }}
.ph-label {{
  font-size: .72rem; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
  color: var(--ink-muted); margin-bottom: .3rem;
}}
.ph-hero {{
  display: flex; align-items: baseline; gap: .35rem;
  font-size: 3rem; font-weight: 600; line-height: 1.05; color: var(--ink);
  font-variant-numeric: tabular-nums; letter-spacing: -0.035em;
}}
.ph-hero-unit {{ font-size: 1rem; font-weight: 500; color: var(--ink-2); }}
.ph-value {{
  display: flex; align-items: baseline; gap: .3rem;
  font-size: 1.6rem; font-weight: 600; line-height: 1.3; color: var(--ink);
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
}}
.ph-sub {{ font-size: .82rem; color: var(--ink-2); margin-top: .25rem; }}
.ph-delta {{ font-size: .82rem; font-weight: 600; margin-top: .25rem; }}
.ph-delta.good {{ color: var(--good); }}
.ph-delta.warn {{ color: var(--critical); }}

/* ---- meter: fill = accent, track = lighter step of the SAME ramp ---- */
.ph-meter {{
  height: 8px; width: 100%; border-radius: 999px;
  background: var(--ramp-100); overflow: hidden; margin-top: .6rem;
}}
.ph-meter-fill {{ height: 100%; border-radius: 999px; background: var(--series-1); }}
.ph-meter-fill.full {{ background: var(--good); }}

/* ---- break cards ---- */
.ph-card-head {{ display: flex; align-items: center; gap: .6rem; }}
.ph-accent {{ width: 4px; height: 34px; border-radius: 999px; flex: none; }}
.ph-title {{ font-size: 1.05rem; font-weight: 600; color: var(--ink); line-height: 1.2; }}
.ph-title small {{ display: block; font-size: .8rem; font-weight: 400; color: var(--ink-2); }}
.ph-span {{
  font-size: 1.75rem; font-weight: 600; color: var(--ink); line-height: 1;
  font-variant-numeric: tabular-nums; letter-spacing: -0.025em;
}}
.ph-span small {{ font-size: .82rem; font-weight: 500; color: var(--ink-2); margin-left: .3rem; }}

/* ---- chips ---- */
.ph-chips {{ display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .45rem; }}
.ph-chip {{
  font-size: .72rem; font-weight: 500; line-height: 1.5;
  padding: .1rem .5rem; border-radius: 999px;
  background: var(--plane); border: 1px solid var(--hairline); color: var(--ink-2);
  white-space: nowrap;
}}
.ph-chip.dot::before {{
  content: ""; display: inline-block; width: 6px; height: 6px; border-radius: 999px;
  margin-right: .35rem; vertical-align: middle; background: var(--mark, var(--ink-muted));
}}
.ph-chip.strong {{ color: var(--ink); font-weight: 600; }}

/* ---- tabs: segmented control, active pill filled ----
   Streamlit 1.60 renders tabs with React Aria, NOT BaseWeb. The selectors are
   [role="tablist"] / [data-testid="stTab"] / .react-aria-SelectionIndicator.
   Old [data-baseweb="tab"] rules silently match nothing. */
.stTabs [data-orientation="horizontal"] {{ border-bottom: none; }}

.stTabs [role="tablist"] {{
  gap: .25rem; width: fit-content; max-width: 100%; flex-wrap: wrap;
  background: var(--plane); border: 1px solid var(--hairline);
  border-radius: 12px; padding: 4px; margin-bottom: 1.4rem;
  box-shadow: inset 0 1px 2px var(--track-shadow);
}}

/* kill the sliding underline */
.stTabs .react-aria-SelectionIndicator {{
  display: none !important; height: 0 !important; background: transparent !important;
}}

.stTabs [data-testid="stTab"] {{
  height: auto; border-radius: 8px; padding: .42rem .95rem;
  color: var(--ink-2); background: transparent; border: none;
  transition: background .12s ease, color .12s ease;
}}
.stTabs [data-testid="stTab"] p {{
  font-size: .9rem; font-weight: 500; margin: 0; color: inherit;
}}
.stTabs [data-testid="stTab"]:hover {{
  background: var(--hover); color: var(--ink);
}}

/* white label on the filled pill is the documented pairing for this blue */
.stTabs [data-testid="stTab"][aria-selected="true"] {{
  background: var(--series-1); color: #fff;
  box-shadow: 0 1px 2px var(--ring);
}}
.stTabs [data-testid="stTab"][aria-selected="true"] p {{ font-weight: 600; }}
.stTabs [data-testid="stTab"][aria-selected="true"]:hover {{ background: var(--series-1); }}
.stTabs [data-testid="stTab"]:focus-visible {{
  outline: 2px solid var(--series-1); outline-offset: 2px;
}}

/* ---- misc ---- */
div[data-testid="stVerticalBlockBorderWrapper"] {{ background: var(--surface); }}
.stDataFrame {{ border-radius: 10px; }}
div[data-testid="stExpander"] details {{ border-radius: 10px; }}
.ph-note {{
  font-size: .82rem; color: var(--ink-2); background: var(--plane);
  border: 1px solid var(--hairline); border-left: 3px solid var(--series-1);
  border-radius: 8px; padding: .6rem .8rem; margin-bottom: .9rem;
}}
</style>
"""


def inject() -> None:
    """Resolve the active theme's tokens and emit the stylesheet.

    Must run before any component draws -- it sets the module-level T that
    accent_for() and c() read.
    """
    global T
    T = DARK if theme_type() == "dark" else LIGHT
    st.markdown(_css(T), unsafe_allow_html=True)


# ------------------------------------------------------------- components
def _e(s) -> str:
    return html.escape(str(s))


def plural(n: int, word: str, suffix: str = "s") -> str:
    """'1 night' / '2 nights' -- no (s) crutches in the UI."""
    return f"{n} {word}{'' if n == 1 else suffix}"


def masthead(title: str, tagline: str, badge: str) -> None:
    head, *rest = title.split(" ", 1)
    st.markdown(
        f'<div class="ph-masthead">'
        f'<div class="ph-wordmark">{_e(head)}<span>{_e(" " + rest[0]) if rest else ""}</span></div>'
        f'<div class="ph-tagline">{_e(tagline)}</div>'
        f'<div class="ph-year">{_e(badge)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def summary_band(
    hero_value: int, hero_unit: str, hero_sub: str,
    used: int, total: int,
    leverage: str, leverage_sub: str,
    holidays: int, holidays_sub: str,
) -> None:
    """One hero figure plus three stat tiles, and the leave meter under the budget."""
    pct = 0 if total <= 0 else min(100, round(100 * used / total))
    full = " full" if used >= total > 0 else ""
    st.markdown(
        f'<div class="ph-band">'
        f'  <div class="ph-cell">'
        f'    <div class="ph-label">Days off</div>'
        f'    <div class="ph-hero">{hero_value}<span class="ph-hero-unit">days</span></div>'
        f'    <div class="ph-sub">{_e(hero_sub)}</div>'
        f"  </div>"
        f'  <div class="ph-cell">'
        f'    <div class="ph-label">Leave used</div>'
        f'    <div class="ph-value">{used}<span class="ph-hero-unit">of {total}</span></div>'
        f'    <div class="ph-meter"><div class="ph-meter-fill{full}" style="width:{pct}%"></div></div>'
        f'    <div class="ph-sub">{plural(total - used, "day")} still unspent</div>'
        f"  </div>"
        f'  <div class="ph-cell">'
        f'    <div class="ph-label">Leverage</div>'
        f'    <div class="ph-value">{_e(leverage)}</div>'
        f'    <div class="ph-sub">{_e(leverage_sub)}</div>'
        f"  </div>"
        f'  <div class="ph-cell">'
        f'    <div class="ph-label">Holidays in play</div>'
        f'    <div class="ph-value">{holidays}</div>'
        f'    <div class="ph-sub">{_e(holidays_sub)}</div>'
        f"  </div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def chips(items: list[str], mark: str | None = None, strong: bool = False) -> str:
    if not items:
        return ""
    cls = "ph-chip dot" if mark else "ph-chip"
    if strong:
        cls += " strong"
    style = f' style="--mark:{mark}"' if mark else ""
    inner = "".join(f'<span class="{cls}"{style}>{_e(t)}</span>' for t in items)
    return f'<div class="ph-chips">{inner}</div>'


def card_head(title: str, subtitle: str, accent: str, chip_html: str = "") -> str:
    return (
        f'<div class="ph-card-head">'
        f'  <div class="ph-accent" style="background:{accent}"></div>'
        f'  <div class="ph-title">{_e(title)}<small>{_e(subtitle)}</small></div>'
        f"</div>{chip_html}"
    )


def span_figure(span: int, caption: str) -> str:
    return (
        f'<div class="ph-span">{span}<small>days off</small></div>'
        f'<div class="ph-sub">{_e(caption)}</div>'
    )


def note(text: str) -> None:
    st.markdown(f'<div class="ph-note">{_e(text)}</div>', unsafe_allow_html=True)


def accent_for(brk, committed: bool = False) -> str:
    """Colour follows what the break IS, never its rank in a sorted list."""
    if committed:
        return c("series_1")
    return c("series_3") if brk.is_free else c("series_2")
