"""Researching a trip: sources, prices that trace to them, and a budget worked out
in code. Pure rules, no I/O.

What comes back from the web is someone else's text. Every price must name a
source that was actually fetched, with the date it was checked; a price that
doesn't is dropped, and so is any sentence quoting a price no source gave.
Links must be plain public https addresses. Nothing here books or buys anything.
"""

import ipaddress
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from urllib.parse import urlsplit

MAX_SOURCES = 12
MAX_TEXT = 400
DEFAULT_NIGHTS = 7
MAX_NIGHTS = 30
MAX_TRAVELLERS = 8
# Hotel rooms: two people share one.
PER_ROOM = 2
# A flexible month is priced from this day of it.
FLEXIBLE_START_DAY = 10


class Per(StrEnum):
    PERSON = "person"  # a return flight, per traveller
    NIGHT = "night"  # a hotel room, per night
    DAY = "day"  # spending, per traveller per day
    TRIP = "trip"  # a one-off: a rail pass, a tour


@dataclass(frozen=True, slots=True)
class Source:
    id: int
    url: str
    title: str
    checked_on: date


@dataclass(frozen=True, slots=True)
class PriceRange:
    """A cost range from one source: "hotels in Shinjuku, 120 to 220 SGD a night"."""

    label: str
    low: Decimal
    high: Decimal
    currency: str
    per: Per
    source: int  # a Source id


_PRIVATE_HOSTS = ("localhost", "localdomain", "internal", "local", "lan", "home", "corp")


def safe_url(raw: object) -> str | None:
    """A public https address, or None: no other schemes, credentials, odd ports,
    IP addresses or internal names."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if len(url) > 500 or any(c.isspace() for c in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return None
    if port not in (None, 443):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # a bare IP address, public or not
    except ValueError:
        pass
    if "." not in host or host.split(".")[-1] in _PRIVATE_HOSTS:
        return None
    return url


def clean_text(raw: object, limit: int = MAX_TEXT) -> str:
    if not isinstance(raw, str):
        return ""
    text = " ".join(raw.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def sources_from(found: Iterable[tuple[str, str]], checked_on: date) -> list[Source]:
    """Numbered, de-duplicated sources from (url, title) pairs; unsafe links dropped."""
    kept: list[Source] = []
    seen: set[str] = set()
    for url, title in found:
        safe = safe_url(url)
        if safe is None or safe in seen:
            continue
        seen.add(safe)
        kept.append(Source(len(kept) + 1, safe, clean_text(title, 120) or safe, checked_on))
        if len(kept) >= MAX_SOURCES:
            break
    return kept


def _amount(raw: object) -> Decimal | None:
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0 or value > Decimal("1000000"):
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def price_range(
    label: object, low: object, high: object, currency: object, per: object, source: object,
    sources: Sequence[Source],
) -> PriceRange | None:  # fmt: skip
    """A price the model read, kept only when it names a fetched source and its
    figures make sense."""
    ids = {s.id for s in sources}
    try:
        source_id = int(str(source).strip().lstrip("[").rstrip("]"))
        kind = Per(str(per).strip().lower())
    except ValueError:
        return None
    if source_id not in ids:
        return None
    lo, hi = _amount(low), _amount(high if high not in (None, "") else low)
    code = str(currency or "").strip().upper()
    if lo is None or hi is None or not re.fullmatch(r"[A-Z]{3}", code):
        return None
    if hi < lo:
        lo, hi = hi, lo
    name = clean_text(label, 80)
    return PriceRange(name, lo, hi, code, kind, source_id) if name else None


# --- dates ---------------------------------------------------------------------------------


def trip_window(
    *, start: date | None, end: date | None, month: date | None, nights: int | None, today: date
) -> tuple[date, date]:
    """The dates to price: the user's own, or a week from the 10th of the month they
    named (next year's if that month has passed)."""
    if start and end and end > start:
        return start, end
    n = max(1, min(nights or DEFAULT_NIGHTS, MAX_NIGHTS))
    if start:
        return start, start + timedelta(days=n)
    base = month or today.replace(day=1)
    first = date(base.year, base.month, FLEXIBLE_START_DAY)
    if first <= today:
        first = date(first.year + 1, first.month, FLEXIBLE_START_DAY)
    return first, first + timedelta(days=n)


# --- the budget ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Estimate:
    """Low and high cost of the trip, in the prices' own currency."""

    low: Decimal
    high: Decimal
    currency: str
    lines: list[tuple[str, Decimal, Decimal]]  # what each part adds


def estimate(
    prices: Sequence[PriceRange], *, nights: int, travellers: int, currency: str
) -> Estimate | None:
    """Flights (per person), a hotel (per room per night), daily spending (per person
    per day) and one-offs, from the typical sourced range of each kind in
    ``currency``: the middle one when sources give several (budget, mid-range,
    luxury). None without at least a hotel or a flight."""
    days = nights + 1
    rooms = math.ceil(travellers / PER_ROOM)
    picks: dict[Per, PriceRange] = {}
    for kind in (Per.PERSON, Per.NIGHT, Per.DAY):
        ranges = sorted(
            (p for p in prices if p.currency == currency and p.per is kind),
            key=lambda p: p.low + p.high,
        )
        if ranges:
            picks[kind] = ranges[(len(ranges) - 1) // 2]
    times = {Per.PERSON: travellers, Per.NIGHT: nights * rooms, Per.DAY: days * travellers}
    lines = [
        (picks[k].label, picks[k].low * n, picks[k].high * n)
        for k, n in times.items()
        if k in picks
    ]
    lines += [
        (p.label, p.low, p.high) for p in prices if p.per is Per.TRIP and p.currency == currency
    ]
    if Per.PERSON not in picks and Per.NIGHT not in picks:
        return None
    low = sum((lo for _, lo, _ in lines), Decimal(0))
    high = sum((hi for _, _, hi in lines), Decimal(0))
    return Estimate(low, high, currency, lines)


def per_payday(total: Decimal, paydays: int) -> Decimal | None:
    """What to put aside each payday to have ``total`` by the trip, rounded up."""
    if paydays <= 0:
        return None
    return (total / paydays).quantize(Decimal(1), rounding=ROUND_CEILING)


def round_budget(amount: Decimal) -> Decimal:
    """A budget a person would write down: up to the next 50."""
    return (amount / 50).quantize(Decimal(1), rounding=ROUND_CEILING) * 50


# --- prices in the model's words -------------------------------------------------------------

_MARK = r"(?:[A-Z]{3}|S\$|US\$|A\$|HK\$|NZ\$|RM|\$|€|£|¥|₩|฿|₹)"
_FIGURE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_WORDS = r"(?:dollars?|yen|won|baht|euros?|pounds?|ringgit|rupiah|yuan|pesos?|dong)"
_PRICE = re.compile(
    rf"(?:(?<![A-Za-z]){_MARK}\s?(?P<a>{_FIGURE}))|(?:(?P<b>{_FIGURE})\s?(?:{_MARK}(?![A-Za-z])|{_WORDS}\b))"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TOLERANCE = Decimal("0.5")


def unsourced(text: str, allowed: Iterable[Decimal]) -> list[str]:
    """Prices in ``text`` (figures written with a currency) that no source gave.
    Years, counts and times aren't prices and pass."""
    values = list(allowed)
    found = []
    for match in _PRICE.finditer(text):
        figure = (match.group("a") or match.group("b") or "").replace(",", "")
        try:
            value = Decimal(figure)
        except InvalidOperation:
            continue
        if not any(abs(value - v) <= _TOLERANCE for v in values):
            found.append(match.group(0).strip())
    return found


def keep_sourced(text: str, allowed: Iterable[Decimal]) -> str:
    """The text without any sentence quoting a price no source gave."""
    values = list(allowed)
    kept = [s for s in _SENTENCE.split(text.strip()) if s and not unsourced(s, values)]
    return " ".join(kept)
