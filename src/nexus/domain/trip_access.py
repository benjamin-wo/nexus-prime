"""Who may do what on a shared trip.

A trip has one owner. The owner can invite people to it; each person who joins is a
member and can edit the trip's plan (days, places, stops, packing, notes) but never
sees or changes its money. Money means the budget, set-aside, spending, who owes what
and what anything cost; those stay between the owner and the owner's ledger.
"""

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
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
