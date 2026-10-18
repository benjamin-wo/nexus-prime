"""Splitting a trip's costs with the people on it, and settling up afterwards.

Nothing here moves money, and nothing changes the ledger on its own: costs are split
when the user says so (one at a time, or all that aren't yet), what a fellow traveller
paid is only a note until the user settles up, and settling up records what the user
says happened.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import splits as split_cases
from nexus.application import trips as trip_cases
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.application.transactions import NewTransaction, create_transaction
from nexus.domain.errors import Conflict, InvalidInput, NexusError, NotFound
from nexus.domain.ledger import Direction, ShareRequest, Source, Transaction, User
from nexus.domain.money import Money
from nexus.domain.settle import (
    PaidByOther,
    PersonBalance,
    check_payment,
    clean_payment_note,
    clean_split_with,
    match_traveller,
    my_share_of,
)
from nexus.domain.trips import Trip, TripItem

type UowFactory = Callable[[], UnitOfWork]

MAX_PAYMENTS = 200


# --- the setting and "just mine" -------------------------------------------------------


async def set_split_evenly(uow: UnitOfWork, user: User, trip_id: UUID, on: bool) -> Trip:
    """Whether the trip offers to split its costs evenly with the people going."""
    async with uow:
        trip = await uow.trips.get_trip(user.id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        await uow.trips.set_split_evenly(user.id, trip_id, on)
        await uow.commit()
    return replace(trip, split_evenly=on)


async def _on_trip(uow: UnitOfWork, user: User, trip: Trip) -> set[UUID]:
    expenses = await uow.trips.trip_expenses(
        user.id, trip, user.timezone, limit=trip_cases.MAX_EXPENSES
    )
    return {e.transaction.id for e in expenses}


async def keep_mine(
    uow: UnitOfWork,
    user: User,
    trip_id: UUID,
    transaction_ids: Iterable[UUID],
    *,
    keep: bool = True,
) -> Trip:
    """Marks expenses on the trip "just mine", so they aren't offered for splitting
    again; with ``keep`` false, offers them again. NotFound for an id that isn't an
    expense on this trip."""
    wanted = list(dict.fromkeys(transaction_ids))
    async with uow:
        trip = await uow.trips.get_trip(user.id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        on_trip = await _on_trip(uow, user, trip)
        for tx_id in wanted:
            if tx_id not in on_trip:
                raise NotFound("no expense with that id on this trip")
        # Ones that have left the trip are let go.
        kept = [i for i in trip.not_split if i in on_trip and (keep or i not in wanted)]
        if keep:
            kept += [i for i in wanted if i not in kept]
        marked = tuple(kept)
        await uow.trips.set_not_split(user.id, trip_id, marked)
        await uow.commit()
    return replace(trip, not_split=marked)


# --- splitting the costs ---------------------------------------------------------------


async def unsplit_expenses(
    uow: UowFactory, rates: RateSource, user: User, trip: Trip
) -> list[TripItem]:
    """The trip's expenses nobody owes a share of yet and that weren't marked "just
    mine" (newest first). Money in, such as a repayment, is never an expense."""
    current = await trip_cases.get_trip(uow(), user.id, trip.id)  # its "just mine" now
    found = await trip_cases.spent_on(uow, rates, user, current)
    return [
        i
        for i in reversed(found.items)
        if i.transaction_id in found.unsplit and i.transaction_id not in current.not_split
    ]


@dataclass(frozen=True, slots=True)
class SplitDone:
    transaction_id: UUID
    counterparty: str | None
    amount: Money
    own_share: Money


@dataclass(frozen=True, slots=True)
class SplitSkipped:
    transaction_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class SplitOutcome:
    with_people: list[str]  # everyone else on the trip
    done: list[SplitDone]
    skipped: list[SplitSkipped]


async def split_trip_costs(
    uow: UowFactory,
    rates: RateSource,
    user: User,
    trip_id: UUID,
    transaction_ids: Iterable[UUID] | None = None,
    *,
    now: datetime,
) -> SplitOutcome:
    """Splits the trip's costs evenly with everyone else on it (the user included in
    the shares), through ``split_bill``, so "owes you", budgets and "your share" all
    follow. ``transaction_ids`` are the ones to split; none means every cost not split
    yet (not the ones marked "just mine"). One that was split meanwhile, isn't on the
    trip or can't be split is skipped and reported, never changed."""
    trip = await trip_cases.get_trip(uow(), user.id, trip_id)
    if not trip.companions:
        raise InvalidInput("add the people you're travelling with to the trip first")
    found = await trip_cases.spent_on(uow, rates, user, trip)
    items = {i.transaction_id: i for i in found.items}
    if transaction_ids is None:
        wanted = [i.transaction_id for i in reversed(found.items)]
        wanted = [i for i in wanted if i in found.unsplit and i not in trip.not_split]
    else:
        wanted = list(dict.fromkeys(transaction_ids))
    people = [ShareRequest(name) for name in trip.companions]

    done: list[SplitDone] = []
    skipped: list[SplitSkipped] = []
    for tx_id in wanted:
        if tx_id not in found.ids:
            skipped.append(SplitSkipped(tx_id, "not an expense on this trip"))
            continue
        try:
            result = await split_cases.split_bill(uow(), user.id, tx_id, people, if_unsplit=True)
        except NexusError as exc:
            skipped.append(SplitSkipped(tx_id, str(exc)))
            continue
        item = items.get(tx_id)
        done.append(
            SplitDone(
                tx_id,
                result.transaction.counterparty if item is None else item.counterparty,
                result.transaction.amount,
                result.own_share,
            )
        )
    if done and trip.not_split:
        # Split on purpose: no longer "just mine".
        split_ids = {d.transaction_id for d in done}
        async with uow() as tx:
            await tx.trips.set_not_split(
                user.id, trip_id, tuple(i for i in trip.not_split if i not in split_ids)
            )
            await tx.commit()
    return SplitOutcome(list(trip.companions), done, skipped)


# --- what other people paid ------------------------------------------------------------


def _payer(trip: Trip, person: str) -> str:
    found = match_traveller(trip.companions, person)
    if found is None:
        raise InvalidInput(
            f"{person.strip()} isn't on this trip; add them to the trip's travellers first"
        )
    return found


def preview_payment(
    trip: Trip, person: str, amount: Money, split_with: list[str] | None
) -> tuple[str, tuple[str, ...], Money]:
    """Who paid (as the trip spells them), who else shares the bill, and the user's
    equal share of it; the same checks as adding the payment, changing nothing."""
    payer = _payer(trip, person)
    others = clean_split_with(trip.companions, payer, split_with)
    return payer, others, my_share_of(check_payment(amount), 2 + len(others))


async def add_paid_by_other(
    uow: UnitOfWork,
    user: User,
    trip_id: UUID,
    *,
    person: str,
    amount: Money,
    note: str | None,
    paid_on: date,
    split_with: list[str] | None,
    now: datetime,
) -> PaidByOther:
    """Notes that a fellow traveller paid ``amount`` for the trip and the user shares
    it. ``split_with`` is the other travellers sharing it (none given: everyone on the
    trip). The user's share is an equal part; it is owed to the payer, and nothing is
    in the ledger until the user settles up."""
    async with uow:
        trip = await uow.trips.get_trip(user.id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        if len(await uow.trips.list_payments(user.id, trip_id)) >= MAX_PAYMENTS:
            raise InvalidInput(f"keep at most {MAX_PAYMENTS} payments on a trip")
        payer, others, _ = preview_payment(trip, person, amount, split_with)
        payment = PaidByOther(
            id=uuid4(),
            user_id=user.id,
            trip_id=trip_id,
            person=payer,
            amount=amount,
            note=clean_payment_note(note),
            paid_on=paid_on,
            split_with=others,
            settled_at=None,
            created_at=now,
        )
        await uow.trips.insert_payment(payment)
        await uow.commit()
    return payment


async def edit_paid_by_other(
    uow: UnitOfWork,
    user: User,
    trip_id: UUID,
    payment_id: UUID,
    *,
    person: str,
    amount: Money,
    note: str | None,
    paid_on: date,
    split_with: list[str] | None,
) -> PaidByOther:
    """Changes a payment that isn't settled yet."""
    async with uow:
        trip = await uow.trips.get_trip(user.id, trip_id)
        current = await uow.trips.get_payment(user.id, trip_id, payment_id, for_update=True)
        if trip is None or current is None:
            raise NotFound("no payment with that id on this trip")
        if current.settled:
            raise Conflict("this payment is already settled")
        payer = _payer(trip, person)
        payment = replace(
            current,
            person=payer,
            amount=check_payment(amount),
            note=clean_payment_note(note),
            paid_on=paid_on,
            split_with=clean_split_with(trip.companions, payer, split_with),
        )
        await uow.trips.update_payment(payment)
        await uow.commit()
    return payment


async def delete_paid_by_other(
    uow: UnitOfWork, user: User, trip_id: UUID, payment_id: UUID
) -> None:
    async with uow:
        if await uow.trips.get_trip(user.id, trip_id) is None:
            raise NotFound("no trip with that id")
        if not await uow.trips.delete_payment(user.id, trip_id, payment_id):
            raise NotFound("no payment with that id on this trip")
        await uow.commit()


# --- settling up -----------------------------------------------------------------------


async def balances(
    uow: UowFactory, rates: RateSource, user: User, trip_id: UUID, *, now: datetime
) -> tuple[Trip, list[PersonBalance]]:
    """Where the user stands with each person on the trip."""
    trip = await trip_cases.get_trip(uow(), user.id, trip_id)
    today = trip_cases.local_today(user, now)
    found = await trip_cases.spent_on(uow, rates, user, trip)
    _, people = await trip_cases.balances_for(uow, rates, user, trip, found, today)
    return trip, people


def find_balance(people: list[PersonBalance], name: str) -> PersonBalance:
    """The person's balance, the name matched as it is everywhere. InvalidInput when
    they have nothing open on the trip."""
    person = match_traveller([b.name for b in people], name)
    found = next((b for b in people if b.name == person), None)
    if found is None:
        raise InvalidInput(f"nothing to settle with {name.strip()} on this trip")
    return found


@dataclass(frozen=True, slots=True)
class Settled:
    person: str
    ious_repaid: int  # their shares of the user's bills, now marked paid back
    payments_settled: int  # what they paid for the trip, now settled
    income: list[Transaction]  # money in recorded for the shares they paid back
    expenses: list[Transaction]  # money out recorded for the user's share of their payments


async def settle_person(
    uow: UowFactory,
    rates: RateSource,
    user: User,
    trip_id: UUID,
    name: str,
    *,
    log: bool,
    now: datetime,
) -> Settled:
    """Records that the user and one person are square for this trip: their open IOUs
    on the trip's expenses are marked paid back (as ``mark_repaid`` always does, which
    records the money in) and what they paid for the trip is marked settled. With
    ``log`` the user's share of each thing they paid is also recorded as an expense,
    dated the day it was paid, counted towards the trip and never offered for
    splitting. Nothing moves money: it records what the user says happened. Safe to
    repeat: what is already settled is left alone."""
    trip, people = await balances(uow, rates, user, trip_id, now=now)
    balance = find_balance(people, name)
    tz = ZoneInfo(user.timezone)

    expenses: list[Transaction] = []
    settled_payments = 0
    for debt in balance.you_owe:
        async with uow() as tx:
            payment = await tx.trips.get_payment(user.id, trip_id, debt.ref, for_update=True)
            if payment is None or payment.settled:
                continue
            if log:
                spent = await create_transaction(
                    tx.ledger,
                    user.id,
                    NewTransaction(
                        direction=Direction.OUT,
                        amount=payment.my_share,
                        occurred_at=datetime.combine(payment.paid_on, time(12, 0), tzinfo=tz),
                        counterparty=payment.person,
                        category_id=next(
                            (
                                c.id
                                for c in await tx.ledger.list_categories(user.id)
                                if c.name.casefold() == "travel"
                            ),
                            None,
                        ),
                        notes=f"Your share of {payment.note or 'a trip cost'} ({trip.destination})",
                        source=Source.MANUAL,
                    ),
                    now=now,
                )
                await tx.trips.set_link(user.id, trip_id, spent.id, included=True, at=now)
                current = await tx.trips.get_trip(user.id, trip_id)
                if current is not None:
                    await tx.trips.set_not_split(user.id, trip_id, (*current.not_split, spent.id))
                expenses.append(spent)
            await tx.trips.set_payment_settled(user.id, trip_id, payment.id, now)
            await tx.commit()
            settled_payments += 1

    income: list[Transaction] = []
    for debt in balance.owes_you:
        try:
            repaid = await split_cases.mark_repaid(uow, user.id, debt.ref, now=now)
        except NotFound:  # paid back meanwhile
            continue
        income.append(repaid.transaction)
    return Settled(balance.name, len(income), settled_payments, income, expenses)
