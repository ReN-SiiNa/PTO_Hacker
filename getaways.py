"""Curated weekend getaways by home city.

Deliberately NOT generated from a fare API. Costs here are realistic mid-range
bands for one person, total trip (travel + stay + food), researched once and
hand-entered. They are typical ranges, not live quotes -- which is honest, and
more useful than a made-up number that looks precise.

It also covers the thing a flight-price model misses entirely: most real weekend
getaways in India are a drive or an overnight train, not a flight.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DRIVE = "drive"
TRAIN = "train"
BUS = "overnight bus"
FLY = "fly"

MODE_ICON = {DRIVE: "car", TRAIN: "train", BUS: "bus", FLY: "plane"}


@dataclass(frozen=True)
class Getaway:
    name: str
    region: str
    distance_km: int
    mode: str
    min_nights: int
    ideal_nights: int
    cost_min: int          # INR per person, whole trip
    cost_max: int
    best_months: tuple[int, ...]
    tags: tuple[str, ...]
    note: str = ""

    @property
    def cost_band(self) -> str:
        return f"₹{self.cost_min:,}–{self.cost_max:,}"

    @property
    def travel_text(self) -> str:
        if self.mode == FLY:
            return f"{self.mode}, {self.distance_km} km"
        return f"{self.mode}, ~{self.distance_km} km"

    def fits_budget(self, budget: int) -> bool:
        """Affordable if the low end of the band is within budget."""
        return self.cost_min <= budget

    def in_season(self, when: date) -> bool:
        return when.month in self.best_months


ALL = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
WINTER = (10, 11, 12, 1, 2, 3)
POST_MONSOON = (9, 10, 11, 12, 1, 2)
MONSOON_OK = (6, 7, 8, 9, 10, 11, 12, 1, 2, 3)
SUMMER_HILL = (3, 4, 5, 6, 9, 10, 11, 12, 1, 2)

CITIES: dict[str, str] = {
    "BLR": "Bengaluru",
    "DEL": "Delhi NCR",
    "BOM": "Mumbai",
    "MAA": "Chennai",
    "HYD": "Hyderabad",
    "PNQ": "Pune",
    "CCU": "Kolkata",
}

GETAWAYS: dict[str, list[Getaway]] = {
    "BLR": [
        Getaway("Nandi Hills", "Karnataka", 60, DRIVE, 0, 1, 1200, 3000, ALL,
                ("sunrise", "cheap", "day trip"), "Doable as a sunrise day trip."),
        Getaway("Mysuru", "Karnataka", 145, DRIVE, 1, 2, 3000, 7000, ALL,
                ("heritage", "palace", "food")),
        Getaway("Yercaud", "Tamil Nadu", 210, DRIVE, 1, 2, 4000, 8500, SUMMER_HILL,
                ("hills", "quiet", "cheap")),
        Getaway("Sakleshpur", "Karnataka", 220, DRIVE, 1, 2, 4500, 10000, MONSOON_OK,
                ("coffee", "trek", "monsoon"), "Best right after the rains."),
        Getaway("Kabini / Bandipur", "Karnataka", 220, DRIVE, 1, 2, 9000, 20000, POST_MONSOON,
                ("wildlife", "safari", "splurge"), "Resort rates drive the cost."),
        Getaway("Chikmagalur", "Karnataka", 240, DRIVE, 1, 2, 5000, 11000, MONSOON_OK,
                ("coffee", "hills", "trek")),
        Getaway("Coorg (Madikeri)", "Karnataka", 265, DRIVE, 1, 2, 6000, 13000, MONSOON_OK,
                ("coffee", "waterfalls", "popular")),
        Getaway("Ooty", "Tamil Nadu", 270, DRIVE, 2, 3, 5500, 12000, SUMMER_HILL,
                ("hills", "toy train", "cold")),
        Getaway("Wayanad", "Kerala", 280, DRIVE, 2, 3, 6000, 13000, POST_MONSOON,
                ("hills", "caves", "nature")),
        Getaway("Pondicherry", "Puducherry", 310, DRIVE, 2, 3, 6000, 13000, WINTER,
                ("beach", "french quarter", "cafes")),
        Getaway("Hampi", "Karnataka", 340, TRAIN, 2, 3, 4500, 9500, WINTER,
                ("ruins", "unesco", "cheap"), "Overnight train both ways saves a day."),
        Getaway("Gokarna", "Karnataka", 480, BUS, 2, 3, 5000, 10000, WINTER,
                ("beach", "backpacker", "cheap")),
        Getaway("Munnar", "Kerala", 470, DRIVE, 2, 3, 7000, 15000, POST_MONSOON,
                ("tea estates", "hills")),
        Getaway("Goa", "Goa", 560, FLY, 2, 3, 9000, 22000, WINTER,
                ("beach", "nightlife", "popular")),
        Getaway("Alleppey backwaters", "Kerala", 560, TRAIN, 2, 3, 10000, 22000, POST_MONSOON,
                ("houseboat", "backwaters", "splurge")),
        Getaway("Kochi", "Kerala", 545, FLY, 2, 3, 8000, 17000, POST_MONSOON,
                ("heritage", "food", "coast")),
    ],
    "DEL": [
        Getaway("Neemrana", "Rajasthan", 120, DRIVE, 1, 1, 4000, 9000, WINTER,
                ("fort palace", "quick", "heritage")),
        Getaway("Agra", "Uttar Pradesh", 230, TRAIN, 1, 1, 3000, 8000, WINTER,
                ("taj mahal", "heritage", "cheap"), "Gatimaan Express makes it a day trip."),
        Getaway("Rishikesh", "Uttarakhand", 240, DRIVE, 1, 2, 4000, 10000, POST_MONSOON,
                ("rafting", "yoga", "river")),
        Getaway("Jim Corbett", "Uttarakhand", 250, DRIVE, 1, 2, 7000, 16000, WINTER,
                ("wildlife", "safari")),
        Getaway("Lansdowne", "Uttarakhand", 250, DRIVE, 1, 2, 4000, 9000, SUMMER_HILL,
                ("quiet", "hills", "cheap")),
        Getaway("Chandigarh", "Punjab", 250, TRAIN, 1, 2, 4000, 9000, ALL,
                ("city", "food", "easy")),
        Getaway("Jaipur", "Rajasthan", 280, TRAIN, 1, 2, 5000, 12000, WINTER,
                ("heritage", "forts", "food")),
        Getaway("Mussoorie", "Uttarakhand", 280, DRIVE, 2, 2, 5500, 12000, SUMMER_HILL,
                ("hills", "mall road")),
        Getaway("Nainital", "Uttarakhand", 300, DRIVE, 2, 2, 5000, 11000, SUMMER_HILL,
                ("lake", "hills")),
        Getaway("Shimla", "Himachal", 350, TRAIN, 2, 3, 6000, 13000, SUMMER_HILL,
                ("hills", "toy train", "snow")),
        Getaway("Amritsar", "Punjab", 450, TRAIN, 1, 2, 4500, 10000, WINTER,
                ("golden temple", "food", "wagah")),
        Getaway("Dharamshala / McLeodganj", "Himachal", 480, BUS, 2, 3, 6000, 13000, SUMMER_HILL,
                ("tibetan", "hills", "cafes")),
        Getaway("Bir Billing", "Himachal", 500, BUS, 2, 3, 6500, 14000, (3, 4, 5, 9, 10, 11),
                ("paragliding", "adventure")),
        Getaway("Kasol / Parvati valley", "Himachal", 520, BUS, 2, 3, 6000, 13000, (3, 4, 5, 6, 9, 10, 11),
                ("backpacker", "trek", "river")),
        Getaway("Manali", "Himachal", 540, BUS, 2, 3, 7000, 16000, SUMMER_HILL,
                ("hills", "snow", "popular")),
        Getaway("Udaipur", "Rajasthan", 660, FLY, 2, 3, 10000, 22000, WINTER,
                ("lakes", "palaces", "splurge")),
    ],
    "BOM": [
        Getaway("Lonavala / Khandala", "Maharashtra", 83, DRIVE, 1, 1, 2500, 6000, MONSOON_OK,
                ("ghats", "monsoon", "cheap")),
        Getaway("Matheran", "Maharashtra", 85, TRAIN, 1, 2, 3000, 8000, POST_MONSOON,
                ("no cars", "hills", "toy train")),
        Getaway("Alibaug", "Maharashtra", 95, "ferry", 1, 2, 4000, 11000, WINTER,
                ("beach", "ferry", "quick")),
        Getaway("Kashid", "Maharashtra", 125, DRIVE, 1, 2, 4000, 10000, WINTER,
                ("beach", "quiet")),
        Getaway("Igatpuri", "Maharashtra", 120, DRIVE, 1, 2, 3000, 8000, MONSOON_OK,
                ("waterfalls", "monsoon", "cheap")),
        Getaway("Pune", "Maharashtra", 150, TRAIN, 1, 2, 3000, 8000, ALL,
                ("city", "food", "easy")),
        Getaway("Nashik", "Maharashtra", 165, DRIVE, 1, 2, 4500, 11000, POST_MONSOON,
                ("vineyards", "wine", "food")),
        Getaway("Silvassa", "DNH", 180, DRIVE, 1, 2, 3500, 9000, WINTER,
                ("quiet", "cheap")),
        Getaway("Bhandardara", "Maharashtra", 185, DRIVE, 1, 2, 3500, 9000, MONSOON_OK,
                ("lake", "camping", "stars")),
        Getaway("Saputara", "Gujarat", 250, DRIVE, 2, 2, 4500, 10000, MONSOON_OK,
                ("hills", "quiet")),
        Getaway("Mahabaleshwar / Panchgani", "Maharashtra", 260, DRIVE, 2, 2, 5000, 12000, POST_MONSOON,
                ("hills", "strawberries", "viewpoints")),
        Getaway("Tarkarli", "Maharashtra", 500, TRAIN, 2, 3, 6000, 13000, WINTER,
                ("beach", "snorkelling", "clear water")),
        Getaway("Goa", "Goa", 590, FLY, 2, 3, 8000, 20000, WINTER,
                ("beach", "nightlife", "popular")),
        Getaway("Hampi", "Karnataka", 690, TRAIN, 2, 3, 5500, 12000, WINTER,
                ("ruins", "unesco")),
    ],
    "MAA": [
        Getaway("Mahabalipuram", "Tamil Nadu", 55, DRIVE, 0, 1, 2000, 6000, WINTER,
                ("shore temple", "beach", "day trip")),
        Getaway("Tirupati", "Andhra Pradesh", 135, TRAIN, 1, 1, 2500, 7000, ALL,
                ("temple", "pilgrimage")),
        Getaway("Pondicherry", "Puducherry", 160, DRIVE, 1, 2, 4500, 11000, WINTER,
                ("beach", "french quarter", "cafes")),
        Getaway("Yelagiri", "Tamil Nadu", 230, DRIVE, 1, 2, 3000, 7000, SUMMER_HILL,
                ("hills", "cheap", "quiet")),
        Getaway("Yercaud", "Tamil Nadu", 230, DRIVE, 1, 2, 3500, 8000, SUMMER_HILL,
                ("hills", "coffee")),
        Getaway("Pichavaram", "Tamil Nadu", 240, DRIVE, 1, 2, 3500, 8000, WINTER,
                ("mangroves", "boating", "offbeat")),
        Getaway("Hogenakkal", "Tamil Nadu", 290, DRIVE, 1, 2, 3000, 7500, POST_MONSOON,
                ("waterfalls", "coracle")),
        Getaway("Tranquebar", "Tamil Nadu", 290, DRIVE, 1, 2, 4500, 11000, WINTER,
                ("danish fort", "offbeat", "coast")),
        Getaway("Kodaikanal", "Tamil Nadu", 520, BUS, 2, 3, 5000, 12000, SUMMER_HILL,
                ("hills", "lake")),
        Getaway("Ooty", "Tamil Nadu", 555, TRAIN, 2, 3, 5500, 13000, SUMMER_HILL,
                ("hills", "toy train")),
        Getaway("Bengaluru", "Karnataka", 350, TRAIN, 1, 2, 3500, 9000, ALL,
                ("city", "food", "breweries")),
        Getaway("Kochi", "Kerala", 690, TRAIN, 2, 3, 6000, 14000, POST_MONSOON,
                ("heritage", "coast", "food")),
    ],
    "HYD": [
        Getaway("Bidar", "Karnataka", 130, DRIVE, 1, 1, 2500, 6500, WINTER,
                ("fort", "heritage", "offbeat")),
        Getaway("Warangal", "Telangana", 145, TRAIN, 1, 1, 2500, 6500, WINTER,
                ("kakatiya temples", "unesco", "cheap")),
        Getaway("Nagarjuna Sagar", "Telangana", 165, DRIVE, 1, 2, 3500, 8000, POST_MONSOON,
                ("dam", "buddhist", "lake")),
        Getaway("Srisailam", "Andhra Pradesh", 215, DRIVE, 1, 2, 3000, 7500, POST_MONSOON,
                ("temple", "forest", "gorge")),
        Getaway("Gandikota", "Andhra Pradesh", 300, DRIVE, 1, 2, 3500, 9000, WINTER,
                ("canyon", "camping", "offbeat"), "The 'Grand Canyon of India'."),
        Getaway("Bhadrachalam", "Telangana", 310, DRIVE, 1, 2, 3000, 7500, WINTER,
                ("temple", "river")),
        Getaway("Horsley Hills", "Andhra Pradesh", 320, DRIVE, 1, 2, 3500, 8500, SUMMER_HILL,
                ("hills", "quiet", "cheap")),
        Getaway("Papikondalu", "Andhra Pradesh", 380, TRAIN, 2, 2, 5000, 11000, POST_MONSOON,
                ("river cruise", "gorge", "offbeat")),
        Getaway("Hampi", "Karnataka", 380, BUS, 2, 3, 4500, 10000, WINTER,
                ("ruins", "unesco", "cheap")),
        Getaway("Araku Valley", "Andhra Pradesh", 620, TRAIN, 2, 3, 5000, 11000, POST_MONSOON,
                ("coffee", "hills", "train ride")),
        Getaway("Goa", "Goa", 660, FLY, 2, 3, 9000, 20000, WINTER,
                ("beach", "nightlife")),
    ],
    "PNQ": [
        Getaway("Lavasa", "Maharashtra", 60, DRIVE, 1, 1, 3000, 8000, MONSOON_OK,
                ("lake", "quick")),
        Getaway("Tamhini Ghat", "Maharashtra", 60, DRIVE, 0, 1, 1500, 4000, (6, 7, 8, 9),
                ("waterfalls", "monsoon", "day trip")),
        Getaway("Lonavala", "Maharashtra", 65, DRIVE, 1, 1, 2500, 6000, MONSOON_OK,
                ("ghats", "monsoon", "cheap")),
        Getaway("Panchgani", "Maharashtra", 100, DRIVE, 1, 2, 3500, 9000, POST_MONSOON,
                ("hills", "viewpoints")),
        Getaway("Kolad", "Maharashtra", 115, DRIVE, 1, 2, 4000, 9500, (7, 8, 9, 10, 11),
                ("rafting", "river", "adventure")),
        Getaway("Mahabaleshwar", "Maharashtra", 120, DRIVE, 1, 2, 4000, 10000, POST_MONSOON,
                ("hills", "strawberries")),
        Getaway("Bhimashankar", "Maharashtra", 125, DRIVE, 1, 2, 2500, 6500, MONSOON_OK,
                ("trek", "temple", "forest")),
        Getaway("Alibaug", "Maharashtra", 145, DRIVE, 1, 2, 4000, 10000, WINTER,
                ("beach", "forts")),
        Getaway("Nashik", "Maharashtra", 210, DRIVE, 1, 2, 4500, 11000, POST_MONSOON,
                ("vineyards", "wine")),
        Getaway("Goa", "Goa", 450, BUS, 2, 3, 7000, 16000, WINTER,
                ("beach", "nightlife")),
    ],
    "CCU": [
        Getaway("Sundarbans", "West Bengal", 110, DRIVE, 1, 2, 4000, 11000, WINTER,
                ("mangroves", "tiger", "boat")),
        Getaway("Bishnupur", "West Bengal", 140, TRAIN, 1, 1, 2000, 5500, WINTER,
                ("terracotta temples", "heritage", "cheap")),
        Getaway("Shantiniketan", "West Bengal", 165, TRAIN, 1, 2, 2500, 7000, WINTER,
                ("tagore", "culture", "crafts")),
        Getaway("Mandarmani", "West Bengal", 175, DRIVE, 1, 2, 3000, 8000, WINTER,
                ("beach", "drivable sands")),
        Getaway("Digha", "West Bengal", 185, TRAIN, 1, 2, 2000, 6000, WINTER,
                ("beach", "cheap", "popular")),
        Getaway("Mukutmanipur", "West Bengal", 230, DRIVE, 1, 2, 2500, 6500, WINTER,
                ("dam", "quiet", "offbeat")),
        Getaway("Puri / Konark", "Odisha", 500, TRAIN, 2, 2, 4000, 10000, WINTER,
                ("beach", "temples", "sun temple")),
        Getaway("Darjeeling", "West Bengal", 620, TRAIN, 2, 3, 6000, 14000, POST_MONSOON,
                ("hills", "tea", "toy train")),
        Getaway("Gangtok", "Sikkim", 680, FLY, 2, 3, 8000, 18000, POST_MONSOON,
                ("mountains", "monasteries")),
    ],
}


def for_city(city: str) -> list[Getaway]:
    return GETAWAYS.get(city, [])


def suggest(
    city: str,
    budget: int,
    nights: int,
    when: date | None = None,
    season_only: bool = True,
) -> list[Getaway]:
    """Getaways you can afford, that fit the length of the break, in season.

    Sorted by how much of the budget they leave unspent -- cheapest useful first,
    then nearest.
    """
    out = []
    for g in for_city(city):
        if not g.fits_budget(budget):
            continue
        if nights < g.min_nights:
            continue
        if season_only and when is not None and not g.in_season(when):
            continue
        out.append(g)
    return sorted(out, key=lambda g: (g.cost_min, g.distance_km))


def all_tags(city: str) -> list[str]:
    return sorted({t for g in for_city(city) for t in g.tags})
