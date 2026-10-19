"""Who may do what on a shared trip.

A trip has one owner. The owner can invite people to it; each person who joins is a
member and can edit the trip's plan (days, places, stops, packing, notes) but never
sees or changes its money. Money means the budget, set-aside, spending, who owes what
and what anything cost; those stay between the owner and the owner's ledger.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from nexus.domain.bookings import Booking
from nexus.domain.ledger import UserId
from nexus.domain.trips import Trip

INVITE_TTL = timedelta(days=7)
# A trip's invite links that can be used right now, and its members.
MAX_OPEN_INVITES = 10
MAX_MEMBERS = 10
MAX_SUMMARY = 200
# The owner hears about other people's changes to a trip at most this often, in one
# message that lists up to DIGEST_LINES of them.
DIGEST_EVERY = timedelta(minutes=30)
DIGEST_LINES = 5
MAX_NAME = 40
# What a person sees in place of a name nobody has set.
UNKNOWN_NAME = "Someone"

# Control characters and the invisible ones that make a name look like another's or flip
# the line around it: soft hyphen, the Arabic letter mark, Mongolian vowel separator,
# zero-width and direction marks, line/paragraph separators, embeddings and isolates, word
# joiner and the invisible operators, the byte order mark, annotation characters and tags.
_CONTROL = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u061c\u180e\u200b-\u200f\u2028-\u202e\u2060-\u206f"
    "\ufeff\ufff9-\ufffb\U000e0000-\U000e007f]"
)


class TripRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class TripAccess:
    """What one person may do on one trip. ``trip_id`` is None only for a booking that
    is on no trip, which only its owner can reach."""

    owner_id: UserId
    actor_id: UserId
    role: TripRole
    trip_id: UUID | None = None

    @property
    def is_owner(self) -> bool:
        return self.role is TripRole.OWNER

    @property
    def sees_money(self) -> bool:
        return self.is_owner


@dataclass(frozen=True, slots=True)
class TripMember:
    user_id: UserId
    name: str
    role: TripRole
    added_at: datetime | None  # None for the owner


@dataclass(frozen=True, slots=True)
class TripInvite:
    id: UUID
    token_hash: str
    trip_id: UUID
    owner_id: UserId
    created_at: datetime
    expires_at: datetime
    # Whether someone with no account may be given a guest one by this link: only when
    # the app's owner made it.
    may_create_guest: bool = False
    redeemed_at: datetime | None = None
    redeemed_by: UserId | None = None
    revoked_at: datetime | None = None

    def usable(self, now: datetime) -> bool:
        return self.redeemed_at is None and self.revoked_at is None and now < self.expires_at


@dataclass(frozen=True, slots=True)
class Activity:
    actor: str
    summary: str
    at: datetime


@dataclass(frozen=True, slots=True)
class DigestState:
    """Where a trip's Telegram summary of other people's changes stands."""

    owner_id: UserId
    destination: str
    last_at: datetime | None  # what the last summary covered up to; None before the first


def digest_key(trip_id: UUID, last_at: datetime | None) -> str:
    """The dedupe key of a trip's next summary. Every edit made before it goes out
    shares the key (so they make one job); once it has gone, ``last_at`` moves and the
    next edit gets a new one."""
    since = last_at.astimezone(UTC).isoformat() if last_at else "first"
    return f"trip.activity_digest:{trip_id}:{since}"


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def digest_text(destination: str, changes: Sequence[Activity]) -> str | None:
    """One message about what other people changed, oldest first: "Alex and Sam changed
    Tokyo: added Dinner at Sushi Ten, moved Senso-ji to Day 2". The same change twice
    counts once; past five, the rest are counted ("and 3 more"). None for no changes."""
    names = list(dict.fromkeys(c.actor for c in changes))
    lines = list(dict.fromkeys(c.summary for c in changes))
    if not names or not lines:
        return None
    shown = ", ".join(lines[:DIGEST_LINES])
    if len(lines) > DIGEST_LINES:
        shown += f" and {len(lines) - DIGEST_LINES} more"
    return f"{_join(names)} changed {destination}: {shown}"


def clean_name(*parts: str | None) -> str | None:
    """A name to show for a person: the parts joined, without control or direction
    characters, and short. None when nothing is left."""
    words = [" ".join(_CONTROL.sub(" ", p).split()) for p in parts if p]
    text = " ".join(w for w in words if w)[:MAX_NAME].strip()
    return text or None


def clean_summary(raw: str) -> str:
    """One line of activity, short enough to show."""
    text = " ".join(_CONTROL.sub(" ", raw).split())
    if len(text) > MAX_SUMMARY:
        text = text[: MAX_SUMMARY - 1].rstrip() + "…"
    return text


def without_money(booking: Booking) -> Booking:
    """A booking as a member sees it: what it cost and the expense it was logged as
    are left off. References stay."""
    return replace(booking, cost=None, transaction_id=None)


def without_trip_money(trip: Trip) -> Trip:
    """A trip as a member sees it: no budget, set-aside or planned amounts, and nothing
    of how its costs are split (the setting, or the expense ids kept out of it)."""
    return replace(trip, budget=None, set_aside=None, planned={}, split_evenly=True, not_split=())
