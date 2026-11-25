"""Tools that put money on a trip: expenses, splitting, what people paid and settling up."""

from collections.abc import Iterable

from pydantic import Field

from nexus.agent.tools.core import ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.fx import rates
from nexus.agent.tools.helpers import _load, parse_money, show
from nexus.agent.tools.trips.trip import TripNameArgs, _mine
from nexus.application import trip_split
from nexus.application import trips as trip_cases
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    MenuSection,
    Transaction,
)
from nexus.domain.money import Money
from nexus.domain.settle import Debt as SettleDebt
from nexus.domain.settle import PersonBalance, describe_balance
from nexus.domain.trips import Trip, TripItem


class TripExpenseArgs(TripNameArgs):
    transaction_id: str = Field(description="The expense's id, from find_transactions")


async def _trip_and_expense(ctx: ToolContext, a: TripExpenseArgs) -> tuple[Trip, Transaction]:
    trip = await _mine(ctx, a.trip)
    return trip, await _load(ctx, a.transaction_id)


async def _describe_add_to_trip(ctx: ToolContext, a: TripExpenseArgs) -> str:
    trip, tx = await _trip_and_expense(ctx, a)
    return f"Count {await show(ctx, tx)} towards {trip.destination}?"


async def _add_to_trip(ctx: ToolContext, a: TripExpenseArgs) -> ToolResult:
    trip, tx = await _trip_and_expense(ctx, a)
    await trip_cases.add_expense(ctx.uow(), ctx.user.id, trip.id, tx.id, now=ctx.now)
    return ToolResult(f"Added to the {trip.destination} trip.", wrote=True)


async def _describe_remove_from_trip(ctx: ToolContext, a: TripExpenseArgs) -> str:
    trip, tx = await _trip_and_expense(ctx, a)
    return f"Take {await show(ctx, tx)} off {trip.destination}?"


async def _remove_from_trip(ctx: ToolContext, a: TripExpenseArgs) -> ToolResult:
    trip, tx = await _trip_and_expense(ctx, a)
    await trip_cases.remove_expense(ctx.uow(), ctx.user.id, trip.id, tx.id, now=ctx.now)
    return ToolResult(f"Taken off the {trip.destination} trip; it stays in the ledger.", wrote=True)


def _sums(amounts: Iterable[Money]) -> str:
    """Totals per currency: "200000 JPY, 40.00 SGD"."""
    totals: dict[str, Money] = {}
    for m in amounts:
        totals[m.currency] = totals[m.currency] + m if m.currency in totals else m
    return ", ".join(str(t) for t in totals.values())


def _people(names: Iterable[str]) -> str:
    found = list(names)
    return found[0] if len(found) == 1 else ", ".join(found[:-1]) + " and " + found[-1]


async def _unsplit(ctx: ToolContext, a: TripNameArgs) -> tuple[Trip, list[TripItem]]:
    trip = await _mine(ctx, a.trip)
    if not trip.companions:
        raise InvalidInput(
            f"nobody else is on the {trip.destination} trip yet; add the people going first"
        )
    items = await trip_split.unsplit_expenses(ctx.uow, rates(ctx), ctx.user, trip)
    if not items:
        raise InvalidInput(f"there's nothing left to split on the {trip.destination} trip")
    return trip, items


async def _describe_split_trip(ctx: ToolContext, a: TripNameArgs) -> str:
    trip, items = await _unsplit(ctx, a)
    return (
        f"Split {len(items)} costs on the {trip.destination} trip "
        f"({_sums(i.amount for i in items)}) evenly with {_people(trip.companions)}, "
        "you taking an equal share?"
    )


async def _split_trip_costs(ctx: ToolContext, a: TripNameArgs) -> ToolResult:
    trip, _ = await _unsplit(ctx, a)
    out = await trip_split.split_trip_costs(
        ctx.uow, rates(ctx), ctx.user, trip.id, None, now=ctx.now
    )
    text = (
        f"Split {len(out.done)} costs on the {trip.destination} trip evenly with "
        f"{_people(out.with_people)}; your share is {_sums(d.own_share for d in out.done)} "
        "and the rest is owed to you."
    )
    if out.skipped:
        text += f" Left alone: {len(out.skipped)} ({'; '.join(k.reason for k in out.skipped)})."
    return ToolResult(text, wrote=bool(out.done))


class TheyPaidArgs(TripNameArgs):
    person: str = Field(description="The traveller who paid; they must be on the trip")
    amount: str = Field(description="The whole bill, e.g. '460'. Never guess it.")
    currency: str | None = Field(None, description="ISO code; omit for the home currency")
    what: str | None = Field(None, description="What it was for, like 'the ryokan'")


async def _they_paid_plan(
    ctx: ToolContext, a: TheyPaidArgs
) -> tuple[Trip, str, tuple[str, ...], Money, Money]:
    trip = await _mine(ctx, a.trip)
    amount = parse_money(ctx, a.amount, a.currency)
    payer, others, share = trip_split.preview_payment(trip, a.person, amount, None)
    return trip, payer, others, amount, share


async def _describe_they_paid(ctx: ToolContext, a: TheyPaidArgs) -> str:
    trip, payer, _, amount, share = await _they_paid_plan(ctx, a)
    what = f" for {a.what}" if a.what else ""
    return (
        f"Note that {payer} paid {amount}{what} on the {trip.destination} trip, split evenly "
        f"with everyone going? Your share, {share}, is what you owe {payer}. Nothing goes in "
        "your ledger until you settle up."
    )


async def _they_paid(ctx: ToolContext, a: TheyPaidArgs) -> ToolResult:
    trip, payer, _, amount, share = await _they_paid_plan(ctx, a)
    payment = await trip_split.add_paid_by_other(
        ctx.uow(),
        ctx.user,
        trip.id,
        person=payer,
        amount=amount,
        note=a.what,
        paid_on=ctx.today(),
        split_with=None,
        now=ctx.now,
    )
    return ToolResult(
        f"Noted: {payer} paid {payment.amount}"
        + (f" for {payment.note}" if payment.note else "")
        + f" on the {trip.destination} trip, split {payment.sharers} ways. "
        f"You owe {payer} {share}.",
        wrote=True,
    )


class SettleUpArgs(TripNameArgs):
    person: str | None = Field(
        None,
        description=(
            'The person to settle up with, as the user named them: "settle up with Ann" is '
            'person="Ann". Leave out only for a question like "who owes who", which just '
            "shows the balances"
        ),
    )
    log: bool = Field(
        True,
        description="Also record the user's share of what the person paid as an expense",
    )


def _debt_line(d: SettleDebt) -> str:
    what = f" for {d.label}" if d.label else ""
    return f"{d.amount}{what} ({d.on:%d %b})"


def _balance_lines(people: list[PersonBalance]) -> list[str]:
    lines: list[str] = []
    for b in people:
        lines.append(f"{describe_balance(b)}.")
        if b.owes_you:
            lines.append(f"  Owes the user: {'; '.join(_debt_line(d) for d in b.owes_you)}")
        if b.you_owe:
            lines.append(f"  The user owes: {'; '.join(_debt_line(d) for d in b.you_owe)}")
    return lines


async def _describe_settle_up(ctx: ToolContext, a: SettleUpArgs) -> str:
    if not a.person:
        return ""  # just looking: nothing to confirm
    trip = await _mine(ctx, a.trip)
    _, people = await trip_split.balances(ctx.uow, rates(ctx), ctx.user, trip.id, now=ctx.now)
    b = trip_split.find_balance(people, a.person)
    steps = []
    if b.owes_you:
        steps.append(
            f"mark {b.name}'s {_sums(d.amount for d in b.owes_you)} as paid back "
            "(recorded as money in)"
        )
    if b.you_owe:
        owing = _sums(d.amount for d in b.you_owe)
        steps.append(
            f"settle what {b.name} paid (your share {owing}"
            + (", recorded as an expense" if a.log else ", not recorded")
            + ")"
        )
    return (
        f"Settle up with {b.name} for the {trip.destination} trip ({describe_balance(b)})? "
        f"This will {' and '.join(steps)}. It records what happened; it moves no money."
    )


async def _settle_up(ctx: ToolContext, a: SettleUpArgs) -> ToolResult:
    trip = await _mine(ctx, a.trip)
    if not a.person:
        _, people = await trip_split.balances(ctx.uow, rates(ctx), ctx.user, trip.id, now=ctx.now)
        if not people:
            return ToolResult(f"Nobody owes anything for the {trip.destination} trip.")
        return ToolResult(
            f"Who owes who for the {trip.destination} trip, worked out in code (quote as is):\n"
            + "\n".join(_balance_lines(people))
        )
    done = await trip_split.settle_person(
        ctx.uow, rates(ctx), ctx.user, trip.id, a.person, log=a.log, now=ctx.now
    )
    parts = []
    if done.income:
        parts.append(f"recorded {_sums(t.amount for t in done.income)} received")
    if done.expenses:
        parts.append(f"recorded {_sums(t.amount for t in done.expenses)} as your share")
    extra = f" ({', '.join(parts)})" if parts else ""
    return ToolResult(
        f"Settled up with {done.person} for the {trip.destination} trip{extra}.", wrote=True
    )


SPECS: list[ToolSpec] = [
    ToolSpec(
        "add_to_trip",
        "Count an expense towards a trip though its date or currency don't match "
        "(flights booked months before). Asks the user to confirm.",
        TripExpenseArgs,
        _add_to_trip,
        confirm=_describe_add_to_trip,
    ),
    ToolSpec(
        "remove_from_trip",
        "Stop counting an expense towards a trip. Asks the user to confirm.",
        TripExpenseArgs,
        _remove_from_trip,
        confirm=_describe_remove_from_trip,
    ),
    ToolSpec(
        "split_trip_costs",
        "Split every cost on a trip that isn't split yet evenly with the people going "
        "(the user takes an equal share; each other person owes theirs). Asks the user "
        "to confirm.",
        TripNameArgs,
        _split_trip_costs,
        confirm=_describe_split_trip,
    ),
    ToolSpec(
        "they_paid",
        "Note that another traveller paid for something on a trip that everyone shares "
        '("Alex paid 460 for the ryokan"). The user\'s equal share becomes what they owe '
        "that person. Nothing is recorded in the ledger until the user settles up. Asks "
        "the user to confirm.",
        TheyPaidArgs,
        _they_paid,
        confirm=_describe_they_paid,
    ),
    ToolSpec(
        "settle_up",
        "Who owes who for a trip, each person netted (what they owe the user less what "
        "the user owes them). With a person, record that the user and that person have "
        "settled up: their IOUs on the trip are marked paid back and what they paid is "
        "settled. Always pass the person when the user says to settle up with someone "
        '("settle up with Ann for Japan"): it shows the balance and asks the user to '
        'confirm, so look nothing up first. Leave it out for "who owes who". Moves no '
        "money.",
        SettleUpArgs,
        _settle_up,
        confirm=_describe_settle_up,
    ),
]

MENU: dict[str, MenuSection] = {
    "add_to_trip": MenuSection.TRAVEL,
    "remove_from_trip": MenuSection.TRAVEL,
    "settle_up": MenuSection.TRAVEL,
    "split_trip_costs": MenuSection.TRAVEL,
    "they_paid": MenuSection.TRAVEL,
}
