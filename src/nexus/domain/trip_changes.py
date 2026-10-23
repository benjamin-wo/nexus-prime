"""Itinerary changes made from chat, kept so Undo can reverse them. Pure rules, no I/O.

Each change to a trip's itinerary (an entry added, taken off or changed) is recorded with
the entry as it was, so it can be put back. The changes one chat message makes share a
batch, and Undo reverses the whole batch together.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.bookings import Booking, BookingDraft
from nexus.domain.ledger import UserId
from nexus.domain.money import Money


class ChangeKind(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    CHANGE = "change"


@dataclass(frozen=True, slots=True)
class TripChange:
    id: UUID
    user_id: UserId  # who made the change (and may undo it); the trip's owner or a member
    trip_id: UUID
    booking_id: UUID  # the entry; it may be gone by now
    kind: ChangeKind
    before: dict[str, Any] | None  # the entry as it was (remove, change)
    after: dict[str, Any] | None  # the entry as it became (add, change)
    batch: UUID | None  # the changes from one chat message
    created_at: datetime
    undone_at: datetime | None = None


def snapshot(booking: Booking) -> dict[str, Any]:
    """The whole entry, enough to make it again exactly (same id, place, order, list,
    times, cost and expense)."""
    return {
        "id": str(booking.id),
        "user_id": str(booking.user_id),
        "trip_id": str(booking.trip_id) if booking.trip_id else None,
        "email_id": str(booking.email_id) if booking.email_id else None,
        "draft": booking.draft.as_dict(),
        "amount": str(booking.cost.amount) if booking.cost else None,
        "currency": booking.cost.currency if booking.cost else None,
        "transaction_id": str(booking.transaction_id) if booking.transaction_id else None,
        "created_at": booking.created_at.isoformat(),
    }


def from_snapshot(data: dict[str, Any]) -> Booking | None:
    """The entry a snapshot kept; None when it can't be read."""
    draft = BookingDraft.from_dict(data.get("draft") or {})
    if draft is None:
        return None
    amount, currency = data.get("amount"), data.get("currency")
    return Booking(
        id=UUID(data["id"]),
        user_id=UserId(UUID(data["user_id"])),
        trip_id=UUID(data["trip_id"]) if data.get("trip_id") else None,
        email_id=UUID(data["email_id"]) if data.get("email_id") else None,
        draft=draft,
        cost=Money.of(amount, currency) if amount is not None and currency else None,
        transaction_id=UUID(data["transaction_id"]) if data.get("transaction_id") else None,
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def title_of(change: TripChange) -> str:
    """What the entry is called, from whichever side of the change kept it."""
    for side in (change.before, change.after):
        found = from_snapshot(side) if side else None
        if found is not None:
            return found.draft.title
    return "an entry"
