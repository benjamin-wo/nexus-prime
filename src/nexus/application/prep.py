"""A trip's Prep tab: to-dos, the suggestions marked "Not needed", and cover and documents.

Like packing and the plan, these are edited by anyone on the trip, and every function
here runs as the trip's owner (see ``trip_access.open_trip``). What a cover cost is the
owner's money: a member's edit keeps the cost a cover had, and only the owner logs it.
Nexus only records a cost as an expense; it never pays for or claims on anything.
"""

from dataclasses import replace
from datetime import date, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.ports import UnitOfWork
from nexus.application.transactions import NewTransaction, create_transaction
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.ledger import Direction, Source, Transaction, User, UserId
from nexus.domain.prep import (
    KEYS,
    MAX_COVERS,
    Cover,
    CoverDraft,
    Suggestion,
    Todo,
    TripFacts,
    clean_cover,
    clean_list,
    new_todo_id,
    suggestions,
)
from nexus.domain.trips import Trip


def facts_of(trip: Trip, owner: User) -> TripFacts:
    """Abroad is spent in another currency than the owner's home one, as for packing."""
    return TripFacts(
        destination=trip.destination,
        nights=trip.days - 1,
        abroad=trip.currency != owner.home_currency,
    )


def suggestions_for(trip: Trip, owner: User, covers: list[Cover]) -> list[Suggestion]:
    return suggestions(facts_of(trip, owner), covers, trip.todos, trip.prep_dismissed)


async def _trip(uow: UnitOfWork, owner: User, trip_id: UUID) -> Trip:
    trip = await uow.trips.get_trip(owner.id, trip_id)
    if trip is None:
        raise NotFound("no trip with that id")
    return trip


# --- to-dos ----------------------------------------------------------------------------


async def set_todos(
    uow: UnitOfWork, owner: User, trip_id: UUID, todos: list[Todo], *, now: datetime
) -> Trip:
    """Replaces the trip's to-dos with the ones given (ticks and due dates included)."""
    async with uow:
        current = await _trip(uow, owner, trip_id)
        kept = clean_list(todos)
        await uow.trips.set_todos(owner.id, trip_id, kept, now)
        await uow.commit()
    return replace(current, todos=kept, updated_at=now)


async def add_todo(
    uow: UnitOfWork, owner: User, trip_id: UUID, text: str, due: date | None, *, now: datetime
) -> tuple[Trip, Todo | None]:
    """Adds one to-do. None as the second answer: it was on the list already (the same
    words, ignoring case)."""
    todo = Todo(new_todo_id(), text, due)
    if not clean_list([todo]):
        raise InvalidInput("a to-do needs some words")
    async with uow:
        current = await _trip(uow, owner, trip_id)
        kept = clean_list([*current.todos, todo])
        added = next((t for t in kept if t.id == todo.id), None)
        if added is not None:
            await uow.trips.set_todos(owner.id, trip_id, kept, now)
            await uow.commit()
            current = replace(current, todos=kept, updated_at=now)
    return current, added


async def dismiss(
    uow: UnitOfWork, owner: User, trip_id: UUID, key: str, *, now: datetime, undo: bool = False
) -> Trip:
    """ "Not needed" for a suggestion, or (``undo``) bringing it back. Safe to repeat."""
    if key not in KEYS:
        raise InvalidInput(f"there's no suggestion called {key!r}")
    async with uow:
        current = await _trip(uow, owner, trip_id)
        have = [k for k in current.prep_dismissed if k != key]
        kept = tuple(have if undo else [*have, key])
        if kept != current.prep_dismissed:
            await uow.trips.set_prep_dismissed(owner.id, trip_id, kept, now)
            await uow.commit()
        return replace(current, prep_dismissed=kept)


# --- cover and documents ---------------------------------------------------------------


async def list_covers(uow: UnitOfWork, owner_id: UserId, trip_id: UUID) -> list[Cover]:
    async with uow:
        return await uow.trips.list_covers(owner_id, trip_id)


async def add_cover(
    uow: UnitOfWork, owner: User, trip_id: UUID, draft: CoverDraft, *, now: datetime
) -> Cover:
    clean = clean_cover(draft)
    async with uow:
        await _trip(uow, owner, trip_id)
        if len(await uow.trips.list_covers(owner.id, trip_id)) >= MAX_COVERS:
            raise InvalidInput(f"a trip keeps at most {MAX_COVERS} covers and documents")
        cover = Cover(uuid4(), owner.id, trip_id, clean, None, now, now)
        await uow.trips.insert_cover(cover)
        await uow.commit()
    return cover


async def edit_cover(
    uow: UnitOfWork,
    owner: User,
    trip_id: UUID,
    cover_id: UUID,
    draft: CoverDraft,
    *,
    now: datetime,
    keep_cost: bool = False,
) -> Cover:
    """Changes a cover. With ``keep_cost`` (a member's edit) it keeps the cost it had,
    whatever ``draft`` says."""
    clean = clean_cover(draft)
    async with uow:
        current = await uow.trips.get_cover(owner.id, trip_id, cover_id, for_update=True)
        if current is None:
            raise NotFound("no cover with that id")
        if keep_cost:
            clean = replace(clean, cost=current.draft.cost)
        changed = replace(current, draft=clean, updated_at=now)
        await uow.trips.update_cover(changed)
        await uow.commit()
    return changed


async def delete_cover(uow: UnitOfWork, owner: User, trip_id: UUID, cover_id: UUID) -> Cover:
    """Forgets a cover. Its expense, if logged, stays in the ledger."""
    async with uow:
        current = await uow.trips.get_cover(owner.id, trip_id, cover_id)
        if current is None or not await uow.trips.delete_cover(owner.id, trip_id, cover_id):
            raise NotFound("no cover with that id")
        await uow.commit()
    return current


async def log_cover(
    uow: UnitOfWork, owner: User, trip_id: UUID, cover_id: UUID, *, now: datetime
) -> tuple[Cover, Transaction]:
    """Records the cover's cost as an expense (Travel, to the cover's name), counted
    towards the trip like a booking's logged cost. Nothing is paid: this only records
    what the owner says was spent. Refused, with Conflict, when it is logged already (an
    expense deleted since can be logged again)."""
    async with uow:
        trip = await _trip(uow, owner, trip_id)
        cover = await uow.trips.get_cover(owner.id, trip_id, cover_id, for_update=True)
        if cover is None:
            raise NotFound("no cover with that id")
        cost = cover.draft.cost
        if cost is None:
            raise InvalidInput("this cover has no cost to log")
        if cover.logged_transaction_id is not None:
            logged = await uow.ledger.get_transaction(owner.id, cover.logged_transaction_id)
            if logged is not None and not logged.is_deleted:
                raise Conflict("this cost is already logged as an expense")
        travel = next(
            (
                c.id
                for c in await uow.ledger.list_categories(owner.id)
                if c.name.casefold() == "travel"
            ),
            None,
        )
        tz = ZoneInfo(owner.timezone)
        spent = await create_transaction(
            uow.ledger,
            owner.id,
            NewTransaction(
                direction=Direction.OUT,
                amount=cost,
                occurred_at=datetime.combine(now.astimezone(tz).date(), time(12, 0), tzinfo=tz),
                counterparty=cover.draft.name,
                category_id=travel,
                notes=f"{cover.draft.kind.value.capitalize()} for the {trip.destination} trip",
                source=Source.MANUAL,
            ),
            now=now,
        )
        await uow.trips.set_link(owner.id, trip_id, spent.id, included=True, at=now)
        logged_cover = replace(cover, logged_transaction_id=spent.id, updated_at=now)
        await uow.trips.update_cover(logged_cover)
        await uow.commit()
    return logged_cover, spent
