"""Where the user is, as a time zone: their current zone follows their phone, what they say
in chat and their trip, and goes back to their home zone. Pure rules, no I/O.

``User.timezone`` is the current zone (everything that reads "their day" reads it);
``User.home_timezone`` is kept to go back to. Four things can say where they are, and
``decide`` turns one of them into a change of zone (or nothing):

- the phone (the web app tells us its zone) and the user themselves (in chat, or in
  Settings) apply at once, the newest winning;
- an ongoing trip's stop applies only when neither has spoken in the last 24 hours, so
  what the user said or the phone reports is never overruled by a plan;
- when no trip is on and the trip is what moved them, they go back home.

``set_at`` is when the phone or the user last said where they are (a trip never touches
it). A phone that reports the zone they are already in just refreshes it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import ZoneSource

# A phone or chat signal this recent keeps a trip from moving the user.
WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Phone:
    """The phone says it is in this zone."""

    zone: str


@dataclass(frozen=True, slots=True)
class Chat:
    """The user says where they are: a zone, or None for "I'm back home"."""

    zone: str | None


@dataclass(frozen=True, slots=True)
class Trip:
    """What the trips say: the zone of where the ongoing trip is today, or None when
    no trip is on."""

    zone: str | None


type Signal = Phone | Chat | Trip


@dataclass(frozen=True, slots=True)
class Change:
    """What to save: the user's new current zone, what set it and ``set_at``. ``switched``
    is whether the zone itself differs from the one they had (else only the source or
    ``set_at`` moved, and nobody needs telling)."""

    zone: str
    source: ZoneSource
    set_at: datetime | None
    switched: bool


def known_zone(raw: str | None) -> str | None:
    """The IANA name if it is one this system knows, else None."""
    name = (raw or "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name).key
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


@cache
def _by_lowercase() -> dict[str, str]:
    return {name.casefold(): name for name in available_timezones()}


def zone_named(raw: str | None) -> str | None:
    """A zone the user typed or said: "Europe/Madrid", also "europe/madrid" or
    "America/Buenos Aires". None for anything that is not a zone name (a city is for the
    geocoder)."""
    name = " ".join((raw or "").split())
    if (found := known_zone(name)) is not None:
        return found
    return _by_lowercase().get(name.replace(" ", "_").casefold()) if "/" in name else None


def valid_zone(raw: str | None) -> str:
    """The IANA name, or InvalidInput if it is not a zone."""
    found = known_zone(raw)
    if found is None:
        raise InvalidInput(
            f"unknown time zone {(raw or '').strip()!r}; use a name like Europe/Madrid"
        )
    return found


def decide(
    current: str,
    home: str,
    source: ZoneSource,
    set_at: datetime | None,
    signal: Signal,
    now: datetime,
) -> Change | None:
    """What a signal does to the user's zone: a ``Change`` to save, or None when nothing
    is to be saved. Raises InvalidInput for a zone that does not exist."""
    if isinstance(signal, Trip):
        return _from_trip(current, home, source, set_at, signal, now)
    if isinstance(signal, Chat) and signal.zone is None:
        zone = home
    else:
        zone = valid_zone(signal.zone)
    if zone == home:
        kind = ZoneSource.HOME
    else:
        kind = ZoneSource.PHONE if isinstance(signal, Phone) else ZoneSource.CHAT
    # Said at this moment, so a trip waits a day; the same zone again changes nothing else.
    return Change(zone, kind, now, switched=zone != current)


def _from_trip(
    current: str,
    home: str,
    source: ZoneSource,
    set_at: datetime | None,
    signal: Trip,
    now: datetime,
) -> Change | None:
    if signal.zone is None:
        if source is not ZoneSource.TRIP:
            return None  # nothing the trip did needs undoing
        return Change(home, ZoneSource.HOME, set_at, switched=home != current)
    zone = valid_zone(signal.zone)
    if set_at is not None and now - set_at < WINDOW:
        return None  # the phone or the user spoke recently: they win
    if zone == current:
        return None
    return Change(zone, ZoneSource.HOME if zone == home else ZoneSource.TRIP, set_at, True)


# --- naming a zone ---------------------------------------------------------------------


def city_name(zone: str) -> str:
    """A friendly name for a zone: Europe/Madrid is "Madrid", America/Argentina/Buenos_Aires
    is "Buenos Aires"."""
    return zone.rsplit("/", 1)[-1].replace("_", " ")


def utc_offset(zone: str, now: datetime) -> str:
    """The zone's offset from UTC at ``now``: UTC+2, UTC-3:30, UTC+0."""
    offset = now.astimezone(ZoneInfo(zone)).utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def label(zone: str, now: datetime) -> str:
    """ "Madrid time (UTC+2)"."""
    return f"{city_name(zone)} time ({utc_offset(zone, now)})"


def clock_there(zone: str, now: datetime) -> str:
    """The time of day in the zone: 14:05."""
    return f"{now.astimezone(ZoneInfo(zone)):%H:%M}"


def switched_text(new: str, home: str, now: datetime) -> str:
    """The one message sent when the user's zone changes."""
    if new == home:
        return f"🕑 Back on {city_name(home)} time."
    return f"🕑 Switched to {label(new, now)}."
