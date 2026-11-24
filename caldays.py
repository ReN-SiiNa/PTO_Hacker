"""Calendar model: turn a year + holiday list + weekend policy into a day-by-day map."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

WORK = "work"
WEEKEND = "weekend"
HOLIDAY = "holiday"


@dataclass(frozen=True)
class Holiday:
    day: date
    name: str
    scope: str = "national"
    confidence: str = "high"


def load_holidays(path: str | Path) -> tuple[list[Holiday], str]:
    """Read a holidays_XX_YYYY.json file. Returns (holidays, note)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = [
        Holiday(
            day=date.fromisoformat(h["date"]),
            name=h["name"],
            scope=h.get("scope", "national"),
            confidence=h.get("confidence", "high"),
        )
        for h in raw["holidays"]
    ]
    return sorted(out, key=lambda h: h.day), raw.get("note", "")


def available_holiday_files() -> list[Path]:
    return sorted(DATA_DIR.glob("holidays_*.json"))


def daterange(start: date, end: date):
    """Inclusive date iterator."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


class YearCalendar:
    """Classifies every day in [start, end] as work / weekend / holiday.

    weekend_days: ISO weekday numbers that are off (Mon=1 ... Sun=7).
                  Default {6, 7} = Sat+Sun. Use {7} for a 6-day week.
    """

    def __init__(
        self,
        start: date,
        end: date,
        holidays: list[Holiday],
        weekend_days: set[int] | None = None,
    ):
        self.start = start
        self.end = end
        self.weekend_days = weekend_days if weekend_days is not None else {6, 7}
        self.holiday_names: dict[date, str] = {
            h.day: h.name for h in holidays if start <= h.day <= end
        }
        self.days: list[date] = list(daterange(start, end))
        self.index: dict[date, int] = {d: i for i, d in enumerate(self.days)}
        self.kind: list[str] = [self._classify(d) for d in self.days]

    def _classify(self, d: date) -> str:
        # A holiday that lands on a weekend stays WEEKEND: it buys you nothing.
        if d.isoweekday() in self.weekend_days:
            return WEEKEND
        if d in self.holiday_names:
            return HOLIDAY
        return WORK

    def is_free(self, i: int) -> bool:
        return self.kind[i] != WORK

    def kind_of(self, d: date) -> str:
        return self.kind[self.index[d]]

    def label(self, d: date) -> str:
        k = self.kind_of(d)
        if k == HOLIDAY:
            return self.holiday_names[d]
        return k.capitalize()

    def wasted_holidays(self) -> list[tuple[date, str]]:
        """Holidays eaten by the weekend — useful to show the user what they lost."""
        return [
            (d, n)
            for d, n in sorted(self.holiday_names.items())
            if d.isoweekday() in self.weekend_days
        ]
