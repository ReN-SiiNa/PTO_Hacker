"""Flight price adapters.

The optimizer never talks to a provider directly -- it goes through FareProvider.
Swap MockFareProvider for an Amadeus/Kiwi/Skyscanner implementation later and
nothing else in the app changes.
"""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

CURRENCY = "INR"

# Rough one-way base fares in INR, used only by the mock provider.
BASE_FARES: dict[tuple[str, str], int] = {
    ("BLR", "GOI"): 3200, ("BLR", "DEL"): 5200, ("BLR", "BOM"): 3800,
    ("BLR", "CCU"): 6100, ("BLR", "IXL"): 11500, ("BLR", "MAA"): 2600,
    ("DEL", "GOI"): 5400, ("DEL", "IXL"): 7200, ("DEL", "SXR"): 6400,
    ("DEL", "BOM"): 4600, ("DEL", "DXB"): 14500, ("DEL", "KTM"): 12000,
    ("BOM", "GOI"): 2900, ("BOM", "DXB"): 13000, ("BLR", "CMB"): 9800,
    ("BLR", "SIN"): 17500, ("BLR", "BKK"): 15000, ("DEL", "BKK"): 16500,
}
DEFAULT_BASE = 6000

AIRPORTS = {
    "BLR": "Bengaluru", "DEL": "Delhi", "BOM": "Mumbai", "MAA": "Chennai",
    "CCU": "Kolkata", "GOI": "Goa", "IXL": "Leh", "SXR": "Srinagar",
    "DXB": "Dubai", "KTM": "Kathmandu", "CMB": "Colombo", "SIN": "Singapore",
    "BKK": "Bangkok",
}


@dataclass(frozen=True)
class FareQuote:
    origin: str
    destination: str
    depart: date
    ret: date | None
    price: int
    currency: str = CURRENCY
    provider: str = "mock"

    @property
    def route(self) -> str:
        return f"{self.origin}→{self.destination}"


class FareProvider(ABC):
    name = "abstract"

    @abstractmethod
    def quote(self, origin: str, destination: str, depart: date,
              ret: date | None = None) -> FareQuote:
        ...

    def quote_many(self, origin: str, destinations: list[str], depart: date,
                   ret: date | None = None) -> list[FareQuote]:
        return [self.quote(origin, d, depart, ret) for d in destinations]


def _base_fare(origin: str, destination: str) -> int:
    key = (origin, destination)
    return BASE_FARES.get(key) or BASE_FARES.get((destination, origin)) or DEFAULT_BASE


def _jitter(*parts) -> float:
    """Deterministic pseudo-random in [0, 1) -- same inputs always give same price."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class MockFareProvider(FareProvider):
    """Plausible synthetic fares. Deterministic, offline, no API key.

    Models three real effects: peak-season demand, Friday/Sunday premiums, and
    the booking-window curve (cheap ~6 weeks out, expensive last-minute).
    """

    name = "mock"

    def __init__(self, today: date | None = None, peak_dates: set[date] | None = None):
        self.today = today or date.today()
        self.peak_dates = peak_dates or set()

    def _multiplier(self, depart: date) -> float:
        m = 1.0
        # Demand around holidays everyone else is also flying on.
        if depart in self.peak_dates:
            m *= 1.45
        # Friday out / Sunday back premium.
        if depart.isoweekday() in (5, 7):
            m *= 1.12
        # Booking-window curve.
        lead = (depart - self.today).days
        if lead < 0:
            m *= 1.9
        elif lead < 14:
            m *= 1.6
        elif lead < 30:
            m *= 1.25
        elif lead > 180:
            m *= 1.08
        else:
            m *= 0.95
        # Summer / Dec peaks.
        if depart.month in (5, 12):
            m *= 1.15
        return m

    def quote(self, origin: str, destination: str, depart: date,
              ret: date | None = None) -> FareQuote:
        base = _base_fare(origin, destination)
        legs = [depart] + ([ret] if ret else [])
        total = 0.0
        for leg in legs:
            noise = 0.85 + 0.35 * _jitter(origin, destination, leg, self.today)
            total += base * self._multiplier(leg) * noise
        price = int(round(total / 100.0) * 100)
        return FareQuote(origin, destination, depart, ret, price,
                         CURRENCY, self.name)


class FareUnavailable(RuntimeError):
    """A provider could not price this route right now. Callers should skip it,
    not crash: with a scraping backend this is expected, not exceptional."""


class GoogleFlightsProvider(FareProvider):
    """Real fares, scraped from Google Flights via the `fast-flights` library.

    UNOFFICIAL AND BEST-EFFORT. This is not an API -- `fast-flights` reverse-
    engineers Google's protobuf and uses TLS impersonation to get past bot
    detection. Consequences you must design around:

      * Google blocks datacenter IPs far more aggressively than home ones, so a
        daily poll from a VPS is exactly the pattern most likely to be throttled.
      * The protobuf format changes without notice and parsing breaks.
      * Automated access is against Google's terms of service.

    So: never the default, never load-bearing. Every caller must tolerate
    FareUnavailable and carry on. Opt in with PTOHACKER_FARES=google.
    """

    name = "google"

    def __init__(self, currency: str = CURRENCY, seat: str = "economy",
                 language: str = "en-US"):
        self.currency = currency
        self.seat = seat
        self.language = language

    def quote(self, origin: str, destination: str, depart: date,
              ret: date | None = None) -> FareQuote:
        try:
            from fast_flights import (  # imported lazily: optional dependency
                FlightQuery,
                Passengers,
                create_query,
                get_flights,
            )
        except ImportError as exc:
            raise FareUnavailable(
                "fast-flights is not installed. `pip install fast-flights`, or "
                "leave PTOHACKER_FARES unset to use the mock provider."
            ) from exc

        legs = [FlightQuery(date=depart.isoformat(), from_airport=origin,
                            to_airport=destination)]
        if ret:
            legs.append(FlightQuery(date=ret.isoformat(), from_airport=destination,
                                    to_airport=origin))

        try:
            query = create_query(
                flights=legs,
                trip="round-trip" if ret else "one-way",
                seat=self.seat,
                passengers=Passengers(adults=1),
                # Pinning currency matters: Google infers it from the server's
                # IP otherwise, so a VPS abroad would quote an Indian route in
                # the wrong currency and the price history would be nonsense.
                currency=self.currency,
                language=self.language,
            )
            results = get_flights(query)
        except Exception as exc:  # network, parse, bot-block -- all the same here
            raise FareUnavailable(
                f"{origin}->{destination}: {type(exc).__name__}: {exc}"
            ) from exc

        prices = [f.price for f in results
                  if isinstance(getattr(f, "price", None), (int, float)) and f.price > 0]
        if not prices:
            raise FareUnavailable(f"{origin}->{destination}: no priced results")

        return FareQuote(origin, destination, depart, ret, int(min(prices)),
                         self.currency, self.name)


PROVIDERS = {"mock": MockFareProvider, "google": GoogleFlightsProvider}


def get_provider(name: str | None = None, **kwargs) -> FareProvider:
    """Pick a provider. Defaults to the mock unless PTOHACKER_FARES says otherwise."""
    name = (name or os.environ.get("PTOHACKER_FARES", "mock")).strip().lower()
    try:
        cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown fare provider {name!r}. Known: {', '.join(sorted(PROVIDERS))}."
        ) from None
    if cls is MockFareProvider:
        return cls(**kwargs)
    return cls()
