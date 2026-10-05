"""Travel bookings: flights, hotels, trains and plans, read from email or a
screenshot or added by hand. Pure rules, no I/O.

What's kept is what the user needs to travel: flight and train numbers, places,
times, hotel names and addresses, dates, the cost, the booking reference and where
it was booked (an airline, Agoda, Klook). The reference is the user's own and shown
only to them. Card numbers, security codes and passport numbers are never kept.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.trips import Trip, TripStatus, clean_notes, hide_private

MAX_SEGMENTS = 6
MAX_TEXT = 120
MAX_NOTE = 300
# A booking up to this many days before a trip starts (an overnight flight out)
# still belongs to it.
EARLY_DAYS = 1
# Reminders: the passport and visa this many days before a trip abroad.
PASSPORT_DAYS = 30
# Online check-in opens about a day before a flight.
CHECK_IN_BEFORE = timedelta(hours=24)
# The hotel's address on the morning of check-in, from this hour.
HOTEL_MORNING = time(8)


class BookingKind(StrEnum):
    FLIGHT = "flight"
    HOTEL = "hotel"
    RAIL = "rail"
    ACTIVITY = "activity"  # a plan the user adds: a dinner, a tour, a day trip


_FLIGHT_NUMBER = re.compile(r"^([A-Z0-9]{2})\s?(\d{1,4})$")
_TRAIN_NUMBER = re.compile(r"^[A-Za-z ]{0,20}\d{1,5}[A-Z]?$")
MASK = "•••"


MAX_REFERENCE = 40
MAX_CATEGORY = 30


def _text(value: object, *, limit: int = MAX_TEXT) -> str | None:
    """A short, single-line string without card or passport numbers, or None."""
    if not isinstance(value, str):
        return None
    cleaned = hide_private(" ".join(value.split())[:limit].strip())
    return cleaned or None


def _reference(value: object) -> str | None:
    """A booking reference as written ("XK7Q9P", "1234567890"); never a card number."""
    found = _text(value, limit=MAX_REFERENCE)
    return None if found is None or "•" in found else found


# How a model sometimes writes a date or time despite being asked for ISO.
_DAY_FORMATS = ("%d %b %Y", "%d %B %Y", "%a %d %b %Y", "%a, %d %b %Y", "%b %d %Y", "%B %d %Y")
_TIME_FORMATS = tuple(f"{d} %H:%M" for d in _DAY_FORMATS)


def _parse(text: str, formats: tuple[str, ...]) -> datetime | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace(",", " ").split())
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        found = _parse(text, tuple(f.replace(",", "") for f in _DAY_FORMATS))
        return found.date() if found else None


def _when(value: object) -> datetime | None:
    """A local date and time as written ("2026-12-10T08:25"), without a timezone."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace(",", " ").split())
    try:
        parsed = datetime.fromisoformat(text[:16])
    except ValueError:
        found = _parse(text[:24], tuple(f.replace(",", "") for f in _TIME_FORMATS))
        if found is None:
            return None
        parsed = found
    return parsed.replace(tzinfo=None, second=0, microsecond=0)


def _note(value: object) -> str | None:
    """The user's own note: one line, without personal numbers."""
    if not isinstance(value, str):
        return None
    return clean_notes(" ".join(value.split())[:MAX_NOTE])


def _clock(value: object) -> time | None:
    """A time of day as written: "19:00", "7:30"."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return time.fromisoformat(value.strip().zfill(5)[:5])
    except ValueError:
        return None


def flight_number(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    found = _FLIGHT_NUMBER.match(value.strip().upper().replace("-", ""))
    return f"{found.group(1)}{found.group(2)}" if found else None


def train_number(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text if _TRAIN_NUMBER.match(text) else None


@dataclass(frozen=True, slots=True)
class Segment:
    """One flight or train: its number, from and to, and local times."""

    number: str | None
    origin: str | None
    destination: str | None
    departs: datetime | None
    arrives: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "from": self.origin,
            "to": self.destination,
            "departs": self.departs.isoformat(timespec="minutes") if self.departs else None,
            "arrives": self.arrives.isoformat(timespec="minutes") if self.arrives else None,
        }

    def line(self) -> str:
        route = " → ".join(p for p in (self.origin, self.destination) if p)
        parts = [p for p in (self.number, route) if p]
        if self.departs:
            parts.append(f"{self.departs:%a %d %b %H:%M}")
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class BookingDraft:
    """What was read from a booking email, cleaned and masked."""

    kind: BookingKind
    provider: str | None  # the airline, hotel or rail operator
    segments: tuple[Segment, ...]  # flights or trains, in order
    hotel: str | None
    address: str | None  # a hotel's, or where a plan happens
    check_in: date | None
    check_out: date | None
    name: str | None = None  # a plan's
    day: date | None = None  # a plan's
    at: time | None = None  # a plan's time, if it has one
    note: str | None = None  # the user's own note, on any kind
    reference: str | None = None  # the booking or confirmation number, the user's own
    booked_via: str | None = None  # where it was booked: the airline, Agoda, Klook
    category: str | None = None  # a plan's kind: Food, Sight, Shopping

    @property
    def starts(self) -> date | None:
        if self.kind is BookingKind.ACTIVITY:
            return self.day
        if self.kind is BookingKind.HOTEL:
            return self.check_in
        days = [s.departs.date() for s in self.segments if s.departs]
        return min(days) if days else None

    @property
    def ends(self) -> date | None:
        if self.kind is BookingKind.ACTIVITY:
            return self.day
        if self.kind is BookingKind.HOTEL:
            return self.check_out or self.check_in
        times = [t for s in self.segments for t in (s.arrives or s.departs,) if t is not None]
        return max(t.date() for t in times) if times else None

    @property
    def title(self) -> str:
        if self.kind is BookingKind.ACTIVITY:
            return self.name or "Plan"
        if self.kind is BookingKind.HOTEL:
            name = self.hotel or self.provider or "Hotel"
            if self.check_in and self.check_out:
                nights = (self.check_out - self.check_in).days
                return f"{name}, {nights} night{'s' if nights != 1 else ''}"
            return name
        if not self.segments:
            return self.provider or self.kind.value.capitalize()
        first, last = self.segments[0], self.segments[-1]
        route = " → ".join(p for p in (first.origin, first.destination) if p)
        number = first.number or self.provider or self.kind.value.capitalize()
        title = f"{number} {route}".strip()
        if len(self.segments) > 1:
            back = first.origin is not None and last.destination == first.origin
            title += ", return" if back else f", {len(self.segments)} legs"
        return title

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "provider": self.provider,
            "segments": [s.as_dict() for s in self.segments],
            "hotel": self.hotel,
            "address": self.address,
            "check_in": self.check_in.isoformat() if self.check_in else None,
            "check_out": self.check_out.isoformat() if self.check_out else None,
            "name": self.name,
            "day": self.day.isoformat() if self.day else None,
            "at": self.at.isoformat(timespec="minutes") if self.at else None,
            "note": self.note,
            "reference": self.reference,
            "booked_via": self.booked_via,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BookingDraft | None":
        """From what the reader gave or what was stored; anything unclear dropped.
        None when it isn't a booking with at least a date."""
        try:
            kind = BookingKind(str(data.get("kind", "")).lower())
        except ValueError:
            return None
        if kind is BookingKind.ACTIVITY:
            plan = cls(
                kind=kind,
                provider=None,
                segments=(),
                hotel=None,
                address=_text(data.get("address")),
                check_in=None,
                check_out=None,
                name=_text(data.get("name")),
                day=_day(data.get("day")),
                at=_clock(data.get("at")),
                note=_note(data.get("note")),
                reference=_reference(data.get("reference")),
                booked_via=_text(data.get("booked_via")),
                category=_text(data.get("category"), limit=MAX_CATEGORY),
            )
            # Without a day, it's a place to visit on the trip, not yet on a day.
            return plan if plan.name else None
        number = flight_number if kind is BookingKind.FLIGHT else train_number
        raw = data.get("segments")
        segments = tuple(
            Segment(
                number(s.get("number")),
                _text(s.get("from")),
                _text(s.get("to")),
                _when(s.get("departs")),
                _when(s.get("arrives")),
            )
            for s in (raw if isinstance(raw, list) else [])[:MAX_SEGMENTS]
            if isinstance(s, dict)
        )
        check_in, check_out = _day(data.get("check_in")), _day(data.get("check_out"))
        if check_in and check_out and check_out < check_in:
            check_out = None
        draft = cls(
            kind=kind,
            provider=_text(data.get("provider")),
            segments=segments if kind is not BookingKind.HOTEL else (),
            hotel=_text(data.get("hotel") or data.get("provider"))
            if kind is BookingKind.HOTEL
            else None,
            address=_text(data.get("address")) if kind is BookingKind.HOTEL else None,
            check_in=check_in if kind is BookingKind.HOTEL else None,
            check_out=check_out if kind is BookingKind.HOTEL else None,
            note=_note(data.get("note")),
            reference=_reference(data.get("reference")),
            booked_via=_text(data.get("booked_via")),
        )
        return draft if draft.starts else None

    def describe(self) -> str:
        """For the user and the model: what, when, and where it was booked with its
        reference."""
        extra = ", ".join(
            p
            for p in (
                f"booked on {self.booked_via}" if self.booked_via else None,
                f"ref {self.reference}" if self.reference else None,
            )
            if p
        )
        text = self._what()
        return f"{text[:-1]}; {extra})" if extra else text

    def _what(self) -> str:
        if self.kind is BookingKind.ACTIVITY and self.day is None:
            tag = f", {self.category}" if self.category else ""
            where = f", {self.address}" if self.address else ""
            return f"place to visit ({self.title}{tag}{where})"
        if self.kind is BookingKind.ACTIVITY:
            when = f"{self.day:%a %d %b}" if self.day else ""
            if self.at:
                when += f" {self.at:%H:%M}"
            where = f", {self.address}" if self.address else ""
            return f"plan ({self.title}, {when}{where})"
        if self.kind is BookingKind.HOTEL:
            when = ""
            if self.check_in:
                when = f", {self.check_in:%d %b}"
                if self.check_out:
                    when += f" to {self.check_out:%d %b}"
            return f"hotel booking ({self.title}{when})"
        legs = "; ".join(s.line() for s in self.segments) or self.title
        return f"{self.kind.value} booking ({legs})"


@dataclass(frozen=True, slots=True)
class Booking:
    id: UUID
    user_id: UserId
    trip_id: UUID | None
    email_id: UUID | None  # the inbound email it was read from
    draft: BookingDraft
    cost: Money | None
    transaction_id: UUID | None  # the expense, once the user logs it
    created_at: datetime

    @property
    def starts(self) -> date:
        found = self.draft.starts
        return found if found else self.created_at.date()

    @property
    def scheduled(self) -> bool:
        """On a day of the itinerary; a place to visit without a day isn't yet."""
        return self.draft.starts is not None


def matching_trips(trips: Sequence[Trip], starts: date, today: date) -> list[Trip]:
    """Trips a booking starting on ``starts`` could belong to: ones not over whose
    dates (or the day before) include it."""
    return [
        t
        for t in trips
        if t.status(today) is not TripStatus.FINISHED
        and t.start - timedelta(days=EARLY_DAYS) <= starts <= t.end
    ]


# --- reminders ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reminder:
    key: str  # sent once per key
    text: str


def passport_reminder(trip: Trip, today: date, home: str) -> Reminder | None:
    """About a month before a trip abroad (spent in another currency)."""
    days = (trip.start - today).days
    if trip.currency == home or not (PASSPORT_DAYS - 3 <= days <= PASSPORT_DAYS):
        return None
    return Reminder(
        f"passport:{trip.id}",
        f"🛂 {trip.destination} is {days} days away. Check your passport is valid for at "
        "least six months after you're back, and whether you need a visa or an entry form.",
    )


def booking_reminders(booking: Booking, now: datetime) -> list[Reminder]:
    """Online check-in about a day before each flight, and the hotel's address on
    the morning of check-in. Times are the booking's local times, compared with
    the user's local ``now`` (no timezone)."""
    found: list[Reminder] = []
    d = booking.draft
    if d.kind is BookingKind.FLIGHT:
        for n, s in enumerate(d.segments):
            if s.departs and s.departs - CHECK_IN_BEFORE <= now < s.departs:
                found.append(
                    Reminder(
                        f"checkin:{booking.id}:{n}",
                        f"✈️ Online check-in for {s.line()} usually opens about now. Check in "
                        f"on {d.provider or 'the airline'}'s own app or site.",
                    )
                )
    if d.kind is BookingKind.HOTEL and d.check_in:
        morning = datetime.combine(d.check_in, HOTEL_MORNING)
        if morning <= now < datetime.combine(d.check_in, time(23, 59)):
            where = f": {d.address}" if d.address else ""
            found.append(
                Reminder(
                    f"hotel:{booking.id}",
                    f"🏨 Checking in today at {d.hotel or d.provider or 'your hotel'}{where}.",
                )
            )
    return found
