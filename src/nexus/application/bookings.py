"""Bookings read from email, and the travel reminders that come from trips and
bookings.

A booking lands on the trip whose dates it falls in. With more than one such
trip, or none while trips are coming up, the user is asked which. Its cost is
logged like any receipt from email, through the usual confirmation; once logged,
the expense counts towards the booking's trip whatever its date or currency.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import UnitOfWork
from nexus.domain.bookings import (
    Booking,
    BookingDraft,
    booking_reminders,
    matching_trips,
    passport_reminder,
)
from nexus.domain.errors import NotFound
from nexus.domain.ledger import User, UserId
from nexus.domain.money import Money
from nexus.domain.trips import Trip, TripStatus

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

REMIND_JOB = "trips.remind"
# Trips offered when asking which trip a booking is for.
ASK_TRIPS = 3


def _today(user: User, now: datetime) -> date:
    return now.astimezone(ZoneInfo(user.timezone)).date()


@dataclass(frozen=True, slots=True)
class Saved:
    booking: Booking
    trip: Trip | None  # the trip it landed on
    ask: list[Trip]  # trips to ask about when it didn't land on one


async def save_from_email(
    tx: UnitOfWork,
    user: User,
    email_id: UUID,
    draft: BookingDraft,
    cost: Money | None,
    *,
    now: datetime,
) -> Saved | None:
    """Inside the caller's unit of work. None when this email's booking is saved
    already."""
    today = _today(user, now)
    trips = await tx.trips.list_trips(user.id)
    starts = draft.starts or today
    found = matching_trips(trips, starts, today)
    trip = found[0] if len(found) == 1 else None
    booking = Booking(
        id=uuid4(),
        user_id=user.id,
        trip_id=trip.id if trip else None,
        email_id=email_id,
        draft=draft,
        cost=cost,
        transaction_id=None,
        created_at=now,
    )
    if not await tx.trips.insert_booking(booking):
        return None
    ask: list[Trip] = []
    if trip is None:
        ahead = [t for t in trips if t.status(today) is not TripStatus.FINISHED]
        ask = sorted(found or ahead, key=lambda t: t.start)[:ASK_TRIPS]
    return Saved(booking, trip, ask)


def which_trip(saved: Saved) -> tuple[str, list[list[dict[str, str]]]]:
    """The question when a booking didn't land on one trip, and its buttons."""
    b = saved.booking
    rows = [
        [{"label": f"{t.destination} ({t.start:%d %b})", "data": f"trip:book:{b.id}:{t.id}"}]
        for t in saved.ask
    ]
    rows.append([{"label": "Not for a trip", "data": f"trip:book:{b.id}:none"}])
    return f"✈️ Which trip is this {b.draft.describe()} for?", rows


async def attach(
    uow: UnitOfWork, user_id: UserId, booking_id: UUID, trip_id: UUID | None, *, now: datetime
) -> tuple[Booking, Trip | None]:
    """Puts a booking on a trip (or none). Its logged expense moves with it."""
    async with uow:
        booking = await uow.trips.get_booking(user_id, booking_id)
        if booking is None:
            raise NotFound("no booking with that id")
        trip = None
        if trip_id is not None:
            trip = await uow.trips.get_trip(user_id, trip_id)
            if trip is None:
                raise NotFound("no trip with that id")
        if booking.transaction_id is not None:
            if booking.trip_id is not None and booking.trip_id != trip_id:
                await uow.trips.remove_link(user_id, booking.trip_id, booking.transaction_id)
            if trip_id is not None:
                await uow.trips.set_link(
                    user_id, trip_id, booking.transaction_id, included=True, at=now
                )
        await uow.trips.set_booking(
            user_id, booking_id, trip_id=trip_id, transaction_id=booking.transaction_id
        )
        await uow.commit()
    return booking, trip


async def expense_logged(
    uow: UnitOfWork, user_id: UserId, email_id: UUID, transaction_id: UUID, *, now: datetime
) -> None:
    """The user logged a booking email's cost: the expense joins the booking's trip."""
    async with uow:
        booking = await uow.trips.booking_for_email(user_id, email_id)
        if booking is None:
            return
        await uow.trips.set_booking(
            user_id, booking.id, trip_id=booking.trip_id, transaction_id=transaction_id
        )
        if booking.trip_id is not None:
            await uow.trips.set_link(
                user_id, booking.trip_id, transaction_id, included=True, at=now
            )
        await uow.commit()


async def unattached(uow: UnitOfWork, user_id: UserId) -> list[Booking]:
    async with uow:
        return await uow.trips.list_bookings(user_id, unattached=True)


async def delete_booking(uow: UnitOfWork, user_id: UserId, booking_id: UUID) -> None:
    """Forgets a booking. Its expense, if logged, stays in the ledger."""
    async with uow:
        if not await uow.trips.delete_booking(user_id, booking_id):
            raise NotFound("no booking with that id")
        await uow.commit()


# --- reminders ---------------------------------------------------------------------------


async def remind(uow: UowFactory, user: User, *, now: datetime) -> int:
    """Sends the travel reminders now due, each once: the passport and visa about a
    month before a trip abroad, online check-in about a day before a flight, and
    the hotel's address on the morning of check-in. Quiet hours apply as for any
    message."""
    local = now.astimezone(ZoneInfo(user.timezone))
    today = local.date()
    sent = 0
    async with uow() as tx:
        trips = await tx.trips.list_trips(user.id)
        bookings = await tx.trips.upcoming_bookings(user.id, today)
        due = [
            r
            for r in (passport_reminder(t, today, user.home_currency) for t in trips)
            if r is not None
        ]
        for b in bookings:
            due += booking_reminders(b, local.replace(tzinfo=None))
        for reminder in due:
            if await tx.trips.claim_reminder(user.id, reminder.key, now):
                await tx.jobs.enqueue(
                    TELEGRAM_SEND,
                    {"user_id": str(user.id), "text": reminder.text},
                    dedupe_key=f"trip.remind:{user.id}:{reminder.key}",
                    run_at=now,
                )
                sent += 1
        await tx.commit()
    return sent


async def remind_everyone(uow: UowFactory, *, now: datetime) -> int:
    async with uow() as tx:
        users = await tx.trips.travellers(now.date())
    sent = 0
    for user_id in users:
        async with uow() as tx:
            user = await tx.ledger.get_user(user_id)
        if user is None:
            continue
        try:
            sent += await remind(uow, user, now=now)
        except Exception:
            log.exception("could not send travel reminders")
    return sent
