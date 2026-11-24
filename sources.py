"""Holiday sources.

Two interchangeable backends:
  1. `holidays` (vacanza/holidays, pip install holidays) -- 200+ countries and
     subdivisions, actively maintained, offline. Preferred when installed.
  2. A curated JSON file in data/ -- zero dependencies, fully editable, and the
     fallback when the library isn't available.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from caldays import DATA_DIR, Holiday, load_holidays

try:
    import holidays as _pyholidays
    HAS_PYHOLIDAYS = True
except ImportError:
    _pyholidays = None
    HAS_PYHOLIDAYS = False


def subdivisions(country: str) -> list[str]:
    if not HAS_PYHOLIDAYS:
        return []
    try:
        cls = getattr(_pyholidays, country)
    except AttributeError:
        return []
    return sorted(getattr(cls, "subdivisions", ()) or ())


def from_library(country: str, year: int, subdiv: str | None = None) -> list[Holiday]:
    if not HAS_PYHOLIDAYS:
        raise RuntimeError("The `holidays` package is not installed.")
    kwargs = {"years": year}
    if subdiv:
        kwargs["subdiv"] = subdiv
    cal = _pyholidays.country_holidays(country, **kwargs)
    return sorted(
        (Holiday(day=d, name=str(n), scope="national" if not subdiv else subdiv,
                 confidence="high")
         for d, n in cal.items()),
        key=lambda h: h.day,
    )


def from_file(path: str | Path) -> tuple[list[Holiday], str]:
    return load_holidays(path)


def curated_files() -> list[Path]:
    return sorted(DATA_DIR.glob("holidays_*.json"))


def merge(*groups: list[Holiday]) -> list[Holiday]:
    """Union of several holiday lists, first name wins on a date collision."""
    out: dict[date, Holiday] = {}
    for g in groups:
        for h in g:
            out.setdefault(h.day, h)
    return sorted(out.values(), key=lambda h: h.day)
