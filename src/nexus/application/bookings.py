"""Bookings read from email, and the travel reminders that come from trips and
bookings.

A booking lands on the trip whose dates it falls in. With more than one such
trip, or none while trips are coming up, the user is asked which. Its cost is
logged like any receipt from email, through the usual confirmation; once logged,
the expense counts towards the booking's trip whatever its date or currency.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import UnitOfWork
from nexus.domain import itinerary
from nexus.domain.bookings import (
    Booking,
    BookingDraft,
    BookingKind,
    booking_reminders,
    matching_trips,
    passport_reminder,
)
from nexus.domain.errors import InvalidInput, NotFound
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


def _same(a: BookingDraft, b: BookingDraft) -> bool:
    """The same entry read twice (a screenshot sent again)."""
    return (
        a.kind is b.kind
        and a.starts == b.starts
        and a.title.casefold() == b.title.casefold()
        and (a.reference or "") == (b.reference or "")
    )


@dataclass(frozen=True, slots=True)
class FromScreenshot:
    saved: list[Saved]
    repeated: int  # entries already on the itinerary, not added again


async def add_from_screenshot(
    uow: UnitOfWork,
    user: User,
    entries: list[tuple[BookingDraft, Money | None]],
    *,
    trip_id: UUID | None = None,
    now: datetime,
) -> FromScreenshot:
    """Itinerary entries read from a screenshot. With ``trip_id`` (sent from a trip's
    page) all go on that trip; otherwise each lands on the trip whose dates it falls
    in, or the user is asked which, as for a booking from email. Entries already on
    the itinerary aren't added twice."""
    today = _today(user, now)
    saved: list[Saved] = []
    repeated = 0
    async with uow:
        trips = await uow.trips.list_trips(user.id)
        chosen = None
        if trip_id is not None:
            chosen = next((t for t in trips if t.id == trip_id), None)
            if chosen is None:
                raise NotFound("no trip with that id")
        existing = [b.draft for b in await uow.trips.list_bookings(user.id)]
        ahead = [t for t in trips if t.status(today) is not TripStatus.FINISHED]
        for draft, cost in entries:
            if any(_same(draft, e) for e in existing):
                repeated += 1
                continue
            if chosen:
                found = [chosen]
            elif draft.starts is None:  # a place to visit: the trip coming up, if only one
                found = ahead
            else:
                found = matching_trips(trips, draft.starts, today)
            trip = found[0] if len(found) == 1 else None
            if trip is not None and (
                len(await uow.trips.list_bookings(user.id, trip_id=trip.id)) >= MAX_BOOKINGS_A_TRIP
            ):
                raise InvalidInput(f"a trip keeps at most {MAX_BOOKINGS_A_TRIP} itinerary entries")
            booking = Booking(uuid4(), user.id, trip.id if trip else None, None, draft, cost,
                              None, now)  # fmt: skip
            await uow.trips.insert_booking(booking)
            existing.append(draft)
            ask = [] if trip else sorted(found or ahead, key=lambda t: t.start)[:ASK_TRIPS]
            saved.append(Saved(booking, trip, ask))
        await uow.commit()
    return FromScreenshot(saved, repeated)


def describe_screenshot(result: FromScreenshot) -> str:
    """What was added where, for the reply."""
    lines: list[str] = []
    by_trip: dict[str, list[Saved]] = {}
    for s in result.saved:
        if s.trip is not None:
            by_trip.setdefault(s.trip.destination, []).append(s)
    for destination, items in by_trip.items():
        lines.append(f"✈️ Added to your {destination} trip:")
        lines += [f"• {_entry_line(s.booking)}" for s in items]
    loose = [s for s in result.saved if s.trip is None]
    if loose and not any(s.ask for s in loose):
        lines.append("No trip covers these dates yet, so they're kept under Trips:")
        lines += [f"• {_entry_line(s.booking)}" for s in loose]
        lines.append(
            'Tell me where you\'re going and when ("make a Tokyo trip 10 to 18 Dec") '
            "and they'll go on it."
        )
    if result.repeated:
        lines.append(
            f"{result.repeated} {'is' if result.repeated == 1 else 'are'} already on the "
            "itinerary, so I left them."
        )
    if not lines and not loose:
        lines.append("Those are all on the itinerary already.")
    return "\n".join(lines)


def _entry_line(b: Booking) -> str:
    cost = f", {b.cost}" if b.cost else ""
    return f"{b.draft.describe()}{cost}"


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


MAX_BOOKINGS_A_TRIP = 100
MAX_LISTS_A_TRIP = 12


def _check_lists(existing: list[Booking], draft: BookingDraft) -> None:
    """A trip keeps at most MAX_LISTS_A_TRIP lists of places to visit."""
    if not draft.list_name:
        return
    names = {b.draft.list_name.casefold() for b in existing if b.draft.list_name}
    if draft.list_name.casefold() not in names and len(names) >= MAX_LISTS_A_TRIP:
        raise InvalidInput(f"a trip keeps at most {MAX_LISTS_A_TRIP} lists of places")


# Kept from the entry as it was when an edit doesn't mention them (the web form and
# the chat change only what they show or what the user named).
KEPT = ("place_id", "ends_at", "link", "list_name", "order", "follows", "stations", "lat", "lng")


def _draft(details: dict[str, object], kept: BookingDraft | None = None) -> BookingDraft:
    data = dict(details)
    if kept is not None and kept.kind.value == data.get("kind"):
        before = kept.as_dict()
        for key in KEPT:
            data.setdefault(key, before[key])
    found = BookingDraft.from_dict(data)
    if found is None:
        kind = str(details.get("kind", ""))
        if kind == "activity":
            raise InvalidInput("a plan or place needs a name")
        if kind == "hotel":
            raise InvalidInput("a hotel needs a check-in date")
        if kind in ("flight", "rail"):
            raise InvalidInput("a flight or train needs its departure date and time")
        raise InvalidInput("that's not a flight, hotel, train or plan")
    if details.get("ends_at") and found.ends_at is None:
        raise InvalidInput("an end time is a time after the start, like 10:00 to 12:30")
    if details.get("link") and found.link is None:
        raise InvalidInput("a link must be a public https address")
    return found


async def add_manual(
    uow: UnitOfWork,
    user_id: UserId,
    trip_id: UUID,
    details: dict[str, object],
    cost: Money | None,
    *,
    now: datetime,
) -> Booking:
    """An itinerary entry the user adds by hand: a flight, hotel, train or plan."""
    draft = _draft(details)
    if cost is not None and not cost.is_positive:
        raise InvalidInput("a cost must be more than zero")
    async with uow:
        trip = await uow.trips.get_trip(user_id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        existing = await uow.trips.list_bookings(user_id, trip_id=trip_id)
        if len(existing) >= MAX_BOOKINGS_A_TRIP:
            raise InvalidInput(f"a trip keeps at most {MAX_BOOKINGS_A_TRIP} itinerary entries")
        _check_lists(existing, draft)
        booking = Booking(uuid4(), user_id, trip_id, None, draft, cost, None, now)
        await uow.trips.insert_booking(booking)
        await uow.commit()
    return booking


async def add_ideas(
    uow: UnitOfWork,
    user_id: UserId,
    trip_id: UUID,
    drafts: Sequence[BookingDraft],
    *,
    now: datetime,
) -> int:
    """Places to visit added to a trip together, all or none (the trip's caps on
    entries and lists apply to the whole set)."""
    async with uow:
        trip = await uow.trips.get_trip(user_id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        existing = await uow.trips.list_bookings(user_id, trip_id=trip_id)
        if len(existing) + len(drafts) > MAX_BOOKINGS_A_TRIP:
            raise InvalidInput(f"a trip keeps at most {MAX_BOOKINGS_A_TRIP} itinerary entries")
        for draft in drafts:
            _check_lists(existing, draft)
            booking = Booking(uuid4(), user_id, trip_id, None, draft, None, None, now)
            await uow.trips.insert_booking(booking)
            existing.append(booking)
        await uow.commit()
    return len(drafts)


async def edit_booking(
    uow: UnitOfWork,
    user_id: UserId,
    booking_id: UUID,
    details: dict[str, object],
    cost: Money | None,
) -> Booking:
    """Changes an entry's details, by hand or read from email (a corrected time).
    What the change doesn't mention (its Google Maps place, end time, link, list and
    place in the day) is kept; a plan moved to another day goes where its time fits."""
    if cost is not None and not cost.is_positive:
        raise InvalidInput("a cost must be more than zero")
    async with uow:
        current = await uow.trips.get_booking(user_id, booking_id)
        if current is None:
            raise NotFound("no booking with that id")
        draft = _draft(details, current.draft)
        if draft.day != current.draft.day:
            draft = replace(draft, order=None, follows=None)
        if current.trip_id is not None and draft.list_name != current.draft.list_name:
            _check_lists(await uow.trips.list_bookings(user_id, trip_id=current.trip_id), draft)
        changed = replace(current, draft=draft, cost=cost)
        await uow.trips.update_booking(changed)
        await uow.commit()
    return changed


async def move_entry(
    uow: UnitOfWork,
    user_id: UserId,
    booking_id: UUID,
    day: date | None,
    after: UUID | None,
) -> Booking:
    """Moves a plan or place to visit: onto ``day`` (None: back to places to visit),
    right after the entry ``after`` there (None: first). Flights, trains and hotel
    nights stay where their booking puts them. The day's plans are numbered afresh in
    their new order."""
    async with uow:
        moving = await uow.trips.get_booking(user_id, booking_id)
        if moving is None or moving.trip_id is None:
            raise NotFound("no itinerary entry with that id")
        if moving.draft.kind is not BookingKind.ACTIVITY:
            raise InvalidInput("flights, trains and hotel nights stay where their booking is")
        others = [
            b
            for b in await uow.trips.list_bookings(user_id, trip_id=moving.trip_id)
            if b.id != moving.id
        ]
        there = itinerary.on_day(others, day) if day else itinerary.places_to_visit(others)
        place = 0
        if after is not None:
            ids = [b.id for b in there]
            if after not in ids:
                raise NotFound("that entry isn't on that day")
            place = sum(
                1 for b in there[: ids.index(after) + 1] if b.draft.kind is BookingKind.ACTIVITY
            )
        plans = [b for b in there if b.draft.kind is BookingKind.ACTIVITY]
        # A plan with no time keeps its spot among the day's timed entries too.
        before = there[: [b.id for b in there].index(after) + 1] if after is not None else []
        follows = itinerary.follows_at(before, day) if day and moving.draft.at is None else None
        moved = replace(moving, draft=replace(moving.draft, day=day, follows=follows))
        plans.insert(place, moved)
        numbers = itinerary.renumber(plans)
        for b in plans:
            if b.id != moved.id and b.draft.order == numbers[b.id]:
                continue
            await uow.trips.update_booking(replace(b, draft=replace(b.draft, order=numbers[b.id])))
        await uow.commit()
    return replace(moved, draft=replace(moved.draft, order=numbers[moved.id]))


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
