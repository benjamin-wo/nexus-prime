"""Live fares, product prices and flight status, as the chat tools ask for them and as
they come back. Pure rules, no I/O.

All of it is someone else's data, read at one moment: every result says when it was checked,
and prices change. Nothing here books or buys anything.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

# The cabins Google Flights knows, by SerpApi's ``travel_class``.
type Cabin = Literal["economy", "premium_economy", "business", "first"]
TRAVEL_CLASS: dict[str, str] = {
    "economy": "1",
    "premium_economy": "2",
    "business": "3",
    "first": "4",
}

MAX_ADULTS = 9
# Google Flights sells about eleven months ahead.
MAX_DAYS_AHEAD = 330
# The calendar is asked for a window this long at most.
MAX_CALENDAR_DAYS = 62
MAX_TRIP_DAYS = 60
FARES_SHOWN = 3
OFFERS_SHOWN = 5
CALENDAR_SHOWN = 5

_FLIGHT = re.compile(r"^([A-Z][A-Z0-9]|[A-Z0-9][A-Z])\s*-?\s*(\d{1,4})[A-Z]?$")


def flight_number(raw: str) -> str | None:
    """ "sq 12" and "SQ-012" as "SQ12" (an airline's two-character code and up to four
    digits); None for anything else."""
    found = _FLIGHT.match(raw.strip().upper())
    if found is None:
        return None
    return f"{found.group(1)}{int(found.group(2))}"


@dataclass(frozen=True, slots=True)
class FlightQuery:
    origin: str  # airport codes, comma separated, or a place id
    destination: str
    outbound: date
    back: date | None  # None: one way
    adults: int
    cabin: Cabin
    currency: str


@dataclass(frozen=True, slots=True)
class CalendarQuery:
    """The cheapest days to fly within a window."""

    origin: str
    destination: str
    start: date
    end: date
    trip_days: int | None  # how long a return trip is; None: one way
    adults: int
    cabin: Cabin
    currency: str


@dataclass(frozen=True, slots=True)
class ProductQuery:
    query: str


@dataclass(frozen=True, slots=True)
class StatusQuery:
    flight: str  # "SQ12"
    day: date | None


@dataclass(frozen=True, slots=True)
class FlightOption:
    airline: str  # "Singapore Airlines", or "Scoot, AirAsia" when it changes
    stops: int
    via: list[str]  # the airports it changes at
    minutes: int | None  # in all, layovers included
    price: Decimal  # for all the adults together
    departs: str | None  # local time at the origin, "2026-12-10 08:25"
    arrives: str | None  # local time at the destination
    flights: list[str]  # flight numbers, "SQ 976"


@dataclass(frozen=True, slots=True)
class PriceInsight:
    level: str | None  # Google's own words: "low", "typical" or "high"
    lowest: Decimal | None
    typical_low: Decimal | None
    typical_high: Decimal | None


@dataclass(frozen=True, slots=True)
class FlightFares:
    query: FlightQuery
    options: list[FlightOption]  # cheapest first, at most FARES_SHOWN and a nonstop
    insight: PriceInsight | None
    url: str | None  # the Google Flights page for this search
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class FareDay:
    outbound: date
    back: date | None
    price: Decimal
    cheap: bool  # Google marks the days within 5% of the lowest


@dataclass(frozen=True, slots=True)
class FareCalendar:
    query: CalendarQuery
    days: list[FareDay]  # every day Google priced, in date order
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class ProductOffer:
    title: str
    price: Decimal
    price_text: str  # as the store shows it: "S$499.00"
    currency: str | None  # when the symbol says which
    store: str | None
    rating: float | None
    link: str | None  # a public https page


@dataclass(frozen=True, slots=True)
class ProductPrices:
    query: ProductQuery
    offers: list[ProductOffer]  # cheapest first, at most OFFERS_SHOWN
    url: str | None  # the Google Shopping page for this search
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class StatusLeg:
    airport: str | None
    city: str | None
    scheduled: str | None  # local time, "2026-04-27 12:10"
    estimated: str | None  # the latest estimate, or the actual time
    terminal: str | None
    gate: str | None
    state: str | None  # "Departed", "Arrived"


@dataclass(frozen=True, slots=True)
class FlightStatus:
    query: StatusQuery
    found: bool
    day: date | None = None
    status: str | None = None
    airline: str | None = None
    route: str | None = None
    departure: StatusLeg | None = None
    arrival: StatusLeg | None = None
    departure_delay: int | None = None  # minutes; negative: early
    arrival_delay: int | None = None
    updated: str | None = None
    source: str | None = None
    source_url: str | None = None  # the tracker's page for this flight, a public https one
    # Days Google has a status for, when the day asked for isn't one of them.
    other_days: list[str] = field(default_factory=list)
    checked_at: datetime | None = None


def money(amount: Decimal, currency: str | None) -> str:
    """ "SGD 312" or "SGD 312.50": whole amounts without decimals."""
    whole = amount == amount.to_integral_value()
    text = f"{amount:,.0f}" if whole else f"{amount:,.2f}"
    return f"{currency} {text}" if currency else text


def duration(minutes: int | None) -> str:
    if minutes is None or minutes <= 0:
        return "?"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest:02d}m" if hours else f"{rest}m"


def cheapest_options(options: list[FlightOption]) -> list[FlightOption]:
    """The few cheapest, and the cheapest nonstop too if it isn't among them."""
    ordered = sorted(options, key=lambda o: (o.price, o.stops, o.minutes or 10**6))
    seen: set[tuple[Decimal, str | None, tuple[str, ...]]] = set()
    unique: list[FlightOption] = []
    for option in ordered:
        key = (option.price, option.departs, tuple(option.flights))
        if key not in seen:
            seen.add(key)
            unique.append(option)
    shown = unique[:FARES_SHOWN]
    nonstop = next((o for o in unique if o.stops == 0), None)
    if nonstop is not None and nonstop not in shown:
        shown.append(nonstop)
    return shown


def cheapest_days(calendar: FareCalendar) -> list[FareDay]:
    """The days with the lowest prices, cheapest first (earlier first among equals)."""
    return sorted(calendar.days, key=lambda d: (d.price, d.outbound))[:CALENDAR_SHOWN]


_CURRENCY_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("S$", "SGD"),
    ("SG$", "SGD"),
    ("US$", "USD"),
    ("A$", "AUD"),
    ("NZ$", "NZD"),
    ("HK$", "HKD"),
    ("C$", "CAD"),
    ("RM", "MYR"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("฿", "THB"),
    ("₩", "KRW"),
    ("₹", "INR"),
)
_CODE_PREFIX = re.compile(r"^([A-Z]{3})\b")


def currency_of(price_text: str) -> str | None:
    """The currency a store's price is in, when it says which: "S$499" is SGD and "SGD 499"
    too. A bare "$" is left unsaid (it could be any of several dollars)."""
    text = price_text.strip()
    for symbol, code in _CURRENCY_SYMBOLS:
        if text.startswith(symbol):
            return code
    found = _CODE_PREFIX.match(text)
    return found.group(1) if found else None
