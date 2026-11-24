"""Defaults for the demo. Everything here is overridable in the sidebar."""
from __future__ import annotations

DEFAULT_YEAR = 2026
DEFAULT_COUNTRY = "IN"
DEFAULT_LEAVE_BALANCE = 18
DEFAULT_MAX_LEAVE_PER_BREAK = 4
DEFAULT_MIN_SPAN = 3
DEFAULT_WEEKEND = {6, 7}           # Sat + Sun (ISO weekday numbers)
DEFAULT_HOME_AIRPORT = "BLR"
DEFAULT_DESTINATIONS = ["GOI", "IXL", "CMB", "BKK", "SIN"]

WEEKEND_PRESETS = {
    "Sat + Sun": {6, 7},
    "Sun only": {7},
    "Fri + Sat": {5, 6},
}

APP_TITLE = "PTO-Hacker"
APP_TAGLINE = "Spend the fewest leave days for the most time off."

DEFAULT_LONGER_BIAS = 0.35
DEFAULT_GETAWAY_BUDGET = 8000
