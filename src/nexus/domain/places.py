"""Places from Google Maps: a restaurant, sight or hotel with its rating, regular
opening hours and a few reviews. Pure data and checks, no I/O.

Only a place's id is kept (on the itinerary entry it belongs to). Everything else is
fetched when shown, as Google's terms ask. Names, summaries and reviews are other
people's text: they're cleaned here and shown to the model as quoted data only.
"""

import re
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

from nexus.domain.news import clean_text, safe_url

MAX_NAME = 120
MAX_ADDRESS = 200
MAX_SUMMARY = 300
MAX_REVIEW = 600
MAX_REVIEWS = 5
_ID = re.compile(r"^[A-Za-z0-9_-]{8,512}$")

PRICE_LEVELS = {0: "Free", 1: "Inexpensive", 2: "Moderate", 3: "Expensive", 4: "Very expensive"}


def place_id(value: object) -> str | None:
    """A Google place id if it looks like one, else None."""
    text = str(value or "").strip()
    return text if _ID.fullmatch(text) else None


def text(value: object, limit: int) -> str | None:
    cleaned = clean_text(value, limit)
    return cleaned or None


def quoted(value: object, limit: int) -> str | None:
    """Someone else's words, on one line and without angle brackets, so they can't
    close the tags they're quoted in."""
    cleaned = text(value, limit)
    return cleaned.replace("<", "(").replace(">", ")") if cleaned else None


def link(value: object) -> str | None:
    return safe_url(value)


def weekday(day: date) -> int:
    """Google's day number: 0 is Sunday."""
    return (day.weekday() + 1) % 7


@dataclass(frozen=True, slots=True)
class Period:
    """One opening in the regular week: opens on ``opens_day`` at ``opens`` and closes
    on ``closes_day`` at ``closes`` (None: it never closes)."""

    opens_day: int  # 0 Sunday … 6 Saturday
    opens: time
    closes_day: int | None
    closes: time | None


@dataclass(frozen=True, slots=True)
class Review:
    rating: int | None  # 1 to 5 stars
    text: str
    author: str | None
    author_url: str | None
    when: str | None  # "2 months ago", as Google words it


@dataclass(frozen=True, slots=True)
class Place:
    id: str
    name: str
    address: str | None = None
    kind: str | None = None  # "Ramen restaurant", "Museum"
    rating: Decimal | None = None  # out of 5
    ratings: int | None = None  # how many people rated it
    price_level: int | None = None  # 0 free … 4 very expensive
    maps_url: str | None = None
    website: str | None = None
    phone: str | None = None
    summary: str | None = None
    status: str | None = None  # OPERATIONAL, CLOSED_TEMPORARILY, CLOSED_PERMANENTLY
    periods: tuple[Period, ...] = ()
    hours: tuple[str, ...] = ()  # "Monday: 11:00 AM to 10:00 PM", as Google words it
    reviews: tuple[Review, ...] = ()
    detailed: bool = False  # fetched with hours and reviews, not just from a search

    @property
    def price(self) -> str | None:
        return PRICE_LEVELS.get(self.price_level) if self.price_level is not None else None

    @property
    def always_open(self) -> bool:
        return any(p.closes is None for p in self.periods)

    def hours_on(self, day: date) -> list[tuple[time, time | None]] | None:
        """When it opens that day in a regular week (closing after midnight shows as
        the closing time, the next day). None when the hours aren't known."""
        if not self.periods:
            return None
        if self.always_open:
            return [(time(0), None)]
        wanted = weekday(day)
        return [(p.opens, p.closes) for p in self.periods if p.opens_day == wanted]

    def warning(self, day: date | None, at: time | None = None) -> str | None:
        """Why a plan there that day (and time) might not work, from Google's regular
        hours; holidays aren't covered."""
        if self.status == "CLOSED_PERMANENTLY":
            return "Google Maps lists it as permanently closed"
        if self.status == "CLOSED_TEMPORARILY":
            return "Google Maps lists it as temporarily closed"
        if day is None:
            return None
        hours = self.hours_on(day)
        if hours is None or self.always_open:
            return None
        if not hours:
            return f"Usually closed on {day:%A}s"
        if at is None:
            return None
        for opens, closes in hours:
            if opens <= at and (closes is None or closes <= opens or at < closes):
                return None
        spans = ", ".join(f"{o:%H:%M} to {c:%H:%M}" if c else f"from {o:%H:%M}" for o, c in hours)
        return f"Open {spans} on {day:%a}s; planned for {at:%H:%M}"


def describe(place: Place, *, reviews: bool = False) -> list[str]:
    """For the model: what Google Maps says about it. Names, summaries and reviews are
    other people's words, quoted as data."""
    head = place.name
    if place.kind:
        head += f" ({place.kind})"
    facts = []
    if place.rating is not None:
        count = f" from {place.ratings:,} ratings" if place.ratings else ""
        facts.append(f"rated {place.rating}/5{count}")
    if place.price:
        facts.append(f"price {place.price.lower()}")
    if place.address:
        facts.append(place.address)
    lines = [f"{head}: {'; '.join(facts)}" if facts else head]
    if place.status and place.status != "OPERATIONAL":
        lines.append(f"Status: {place.status.replace('_', ' ').lower()}")
    if place.summary:
        lines.append(f"Summary: {place.summary}")
    if place.hours:
        lines.append("Regular hours: " + "; ".join(place.hours))
    if place.maps_url:
        lines.append(f"Google Maps: {place.maps_url}")
    if reviews and place.reviews:
        lines.append("<reviews>")
        for r in place.reviews:
            stars = f"{r.rating}★ " if r.rating else ""
            who = f" ({r.author}, {r.when})" if r.author and r.when else ""
            lines.append(f"- {stars}{r.text}{who}")
        lines.append("</reviews>")
    return lines
