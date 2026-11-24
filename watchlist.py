"""Fare watchlist, backed by SQLite.

The public API is unchanged from the JSON version -- add / remove / refresh /
as_rows -- but nothing is held in memory between reruns and nothing races on a
file write. `refresh()` is safe to call from a background poller as well as the
app: both go through store.py, and WAL mode lets them overlap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import store
from flights import FareUnavailable


@dataclass
class PricePoint:
    checked_at: str
    price: int


@dataclass
class WatchItem:
    key: str
    origin: str
    destination: str
    depart: str
    ret: str | None
    note: str = ""
    history: list[PricePoint] = field(default_factory=list)

    @property
    def latest(self) -> int | None:
        return self.history[-1].price if self.history else None

    @property
    def best(self) -> int | None:
        return min((p.price for p in self.history), default=None)

    @property
    def delta(self) -> int | None:
        """Change since the previous check. Negative means it got cheaper."""
        if len(self.history) < 2:
            return None
        return self.history[-1].price - self.history[-2].price

    def record(self, price: int) -> None:
        store.record_price(self.key, price)
        self.history.append(PricePoint("", price))


def make_key(origin: str, destination: str, depart: str, ret: str | None) -> str:
    return f"{origin}-{destination}-{depart}-{ret or 'ow'}"


class Watchlist:
    """A thin view over the watch tables. Reads fresh on construction."""

    def __init__(self):
        self.items: dict[str, WatchItem] = {}
        self.load()

    def load(self) -> None:
        self.items = {}
        for row in store.watch_items():
            self.items[row["key"]] = WatchItem(
                key=row["key"],
                origin=row["origin"],
                destination=row["destination"],
                depart=row["depart"],
                ret=row["ret"],
                note=row["note"],
                history=[PricePoint(h["checked_at"], h["price"])
                         for h in row["history"]],
            )

    def add(self, origin: str, destination: str, depart: date,
            ret: date | None = None, note: str = "") -> WatchItem:
        key = make_key(origin, destination, depart.isoformat(),
                       ret.isoformat() if ret else None)
        store.upsert_watch(key, origin, destination, depart.isoformat(),
                           ret.isoformat() if ret else None, note)
        if key not in self.items:
            self.items[key] = WatchItem(key, origin, destination,
                                        depart.isoformat(),
                                        ret.isoformat() if ret else None, note)
        else:
            self.items[key].note = note or self.items[key].note
        return self.items[key]

    def remove(self, key: str) -> None:
        store.delete_watch(key)
        self.items.pop(key, None)

    def save(self) -> None:
        """No-op: every mutation already went to SQLite. Kept so callers that
        still say wl.save() keep working."""

    def refresh(self, provider) -> tuple[int, list[str]]:
        """Re-quote every watched route. Returns (updated, failures).

        One route failing must never lose the others: with a scraping backend a
        blocked or unparseable response is routine, so each is caught and the
        rest still get written.
        """
        rows, failures = [], []
        for item in self.items.values():
            try:
                q = provider.quote(
                    item.origin,
                    item.destination,
                    date.fromisoformat(item.depart),
                    date.fromisoformat(item.ret) if item.ret else None,
                )
            except FareUnavailable as exc:
                failures.append(str(exc))
                continue
            rows.append((item.key, q.price))
        if rows:
            store.record_prices(rows)
            self.load()
        return len(rows), failures

    def as_rows(self) -> list[dict]:
        return [
            {
                "Route": f"{i.origin}→{i.destination}",
                "Depart": i.depart,
                "Return": i.ret or "—",
                "Latest": i.latest,
                "Best seen": i.best,
                "Change": i.delta,
                "Checks": len(i.history),
                "Note": i.note,
                "_key": i.key,
            }
            for i in self.items.values()
        ]
