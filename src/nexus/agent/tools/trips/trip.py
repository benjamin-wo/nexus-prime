"""Tools that create, change and look at trips."""

from dataclasses import replace

from pydantic import Field

from nexus.agent.tools.core import NEW_PERSON, Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.fx import rates
from nexus.agent.tools.helpers import parse_day, parse_money
from nexus.agent.tools.splits import _check_people
from nexus.application import trip_access as access_cases
from nexus.application import trips as trip_cases
from nexus.domain import itinerary
from nexus.domain.errors import Forbidden
from nexus.domain.ledger import (
    MenuSection,
)
from nexus.domain.money import Money
from nexus.domain.trip_access import clean_name
from nexus.domain.trips import Trip, describe_trip


class TripArgs(Args):
    destination: str = Field(description="Where, as the user says it: Tokyo, Japan, Bali")
    start: str = Field(description="First day, like 2027-01-10")
    end: str = Field(description="Last day, like 2027-01-19")
    currency: str = Field(description="The currency spent there, e.g. JPY for Japan")
    budget: str | None = Field(None, description="Total budget, in the user's home currency")
    companions: list[str] = Field(default_factory=list, description="Who's going with them")
    set_aside: str | None = Field(
        None, description="Amount to put aside each payday until the trip, home currency"
    )
    notes: str | None = Field(None, description="The user's own notes for the trip")
    new_person: bool = Field(False, description=NEW_PERSON)


def _home_money(ctx: ToolContext, amount: str | None) -> Money | None:
    if amount is None or amount.strip().lower() in {"", "none", "0", "no"}:
        return None
    return parse_money(ctx, amount, None)


def _trip_draft(ctx: ToolContext, a: TripArgs) -> trip_cases.TripDraft:
    return trip_cases.TripDraft(
        destination=a.destination,
        start=parse_day(ctx, a.start).date(),
        end=parse_day(ctx, a.end).date(),
        currency=a.currency,
        budget=_home_money(ctx, a.budget),
        companions=a.companions,
        set_aside=_home_money(ctx, a.set_aside),
        notes=a.notes,
    )


def _draft_line(d: trip_cases.TripDraft) -> str:
    line = (
        f"{d.destination}, {d.start:%a %d %b %Y} to {d.end:%a %d %b %Y}, spending in {d.currency}"
    )
    if d.budget:
        line += f", budget {d.budget}"
    if d.companions:
        line += ", with " + ", ".join(d.companions)
    if d.set_aside:
        line += f", setting aside {d.set_aside} each payday"
    if d.notes:
        line += f'. Notes: "{" / ".join(d.notes.splitlines())}"'
    return line


async def _describe_create_trip(ctx: ToolContext, a: TripArgs) -> str:
    await _check_people(ctx, a.companions, a.new_person)
    return f"Add a trip: {_draft_line(_trip_draft(ctx, a))}?"


async def _create_trip(ctx: ToolContext, a: TripArgs) -> ToolResult:
    await _check_people(ctx, a.companions, a.new_person)
    trip = await trip_cases.create_trip(ctx.uow(), ctx.user, _trip_draft(ctx, a), now=ctx.now)
    return ToolResult(
        f"Trip saved: {_draft_line(trip_cases.draft_of(trip))}. Expenses in {trip.currency} "
        "on its days count towards it; the trip page is under Travel on the web app.",
        wrote=True,
    )


class TripNameArgs(Args):
    trip: str | None = Field(
        None, description="The trip's destination; leave out for the one that's on or next"
    )


async def _found(ctx: ToolContext, name: str | None) -> access_cases.Found:
    """The trip by name among the user's own and the ones they were added to. Who may do
    what on it is decided here, as for the web: see ``access_cases.find_trip``."""
    return await access_cases.find_trip(ctx.uow, ctx.user, name, now=ctx.now)


async def _mine(ctx: ToolContext, name: str | None) -> Trip:
    """A trip the user owns, for what touches money or changes the trip itself. On a
    trip they were added to, this refuses before anything is read or changed."""
    return access_cases.require_owner(await _found(ctx, name))


async def _noted(ctx: ToolContext, found: access_cases.Found, summary: str) -> None:
    """Notes a plan change in the trip's activity (when the trip is shared), as the web
    does, so its owner's Telegram summary fires."""
    await access_cases.record(ctx.uow(), found.opened.access, summary, now=ctx.now)


def _price_left_out(found: access_cases.Found, cost: str | None) -> str:
    """What to say when a member gave a price: costs on a shared trip are the owner's."""
    if not (found.shared and cost):
        return ""
    return f" I left the price out: only {found.owner_label} can add costs on a shared trip."


class TripChangeArgs(TripNameArgs):
    destination: str | None = None
    start: str | None = Field(None, description="New first day, like 2027-01-10")
    end: str | None = Field(None, description="New last day")
    currency: str | None = None
    budget: str | None = Field(None, description="New budget in the home currency; none clears")
    companions: list[str] | None = Field(None, description="Everyone going, replacing the list")
    set_aside: str | None = Field(None, description="New amount each payday; none stops it")
    notes: str | None = Field(
        None, description="The trip's notes in full, replacing them (include what to keep)"
    )
    new_person: bool = Field(False, description=NEW_PERSON)


_DETAILS = ("destination", "start", "end", "currency", "budget", "companions", "set_aside")


def _only_notes(a: TripChangeArgs) -> bool:
    return a.notes is not None and all(getattr(a, f) is None for f in _DETAILS)


async def _changed_trip(
    ctx: ToolContext, a: TripChangeArgs
) -> tuple[access_cases.Found, trip_cases.TripDraft]:
    found = await _found(ctx, a.trip)
    if found.shared and not _only_notes(a):
        # A member edits the plan and the notes; the dates, travellers and money are the
        # owner's.
        raise Forbidden(access_cases.refusal(found.owner_label))
    if a.companions is not None:
        await _check_people(ctx, a.companions, a.new_person)
    trip = found.trip
    d = trip_cases.draft_of(trip)
    changed = replace(
        d,
        destination=a.destination or d.destination,
        start=parse_day(ctx, a.start).date() if a.start else d.start,
        end=parse_day(ctx, a.end).date() if a.end else d.end,
        currency=a.currency or d.currency,
        budget=_home_money(ctx, a.budget) if a.budget is not None else d.budget,
        companions=a.companions if a.companions is not None else d.companions,
        set_aside=_home_money(ctx, a.set_aside) if a.set_aside is not None else d.set_aside,
        notes=a.notes if a.notes is not None else d.notes,
    )
    return found, changed


async def _describe_update_trip(ctx: ToolContext, a: TripChangeArgs) -> str:
    found, changed = await _changed_trip(ctx, a)
    if found.shared:
        return (
            f"Change the notes on the {found.trip.destination} trip{found.whose} to: "
            f'"{" / ".join((changed.notes or "").splitlines())}"?'
        )
    return f"Change the trip to: {_draft_line(changed)}?"


async def _update_trip(ctx: ToolContext, a: TripChangeArgs) -> ToolResult:
    found, changed = await _changed_trip(ctx, a)
    if found.shared:
        trip = await trip_cases.set_notes(
            ctx.uow(), found.owner, found.trip.id, changed.notes, now=ctx.now
        )
        await _noted(ctx, found, "changed the notes")
        return ToolResult(f"Notes changed on the {trip.destination} trip{found.whose}.", wrote=True)
    trip = await trip_cases.update_trip(ctx.uow(), ctx.user, found.trip.id, changed, now=ctx.now)
    return ToolResult(f"Trip updated: {_draft_line(trip_cases.draft_of(trip))}.", wrote=True)


async def _describe_delete_trip(ctx: ToolContext, a: TripNameArgs) -> str:
    trip = await _mine(ctx, a.trip)
    return (
        f"Delete the trip to {trip.destination} ({trip.start:%d %b} to {trip.end:%d %b})? "
        "Its expenses stay in the ledger."
    )


async def _delete_trip(ctx: ToolContext, a: TripNameArgs) -> ToolResult:
    trip = await _mine(ctx, a.trip)
    await trip_cases.delete_trip(ctx.uow(), ctx.user.id, trip.id)
    return ToolResult(f"Deleted the trip to {trip.destination}.", wrote=True)


async def _list_trips(ctx: ToolContext, _: NoArgs) -> ToolResult:
    trips = await trip_cases.list_trips(ctx.uow(), ctx.user.id)
    shared = await access_cases.shared_trips(ctx.uow(), ctx.user.id)
    if not trips and not shared:
        return ToolResult(
            'No trips yet. The user can say "I\'m going to Tokyo 10-20 Jan, budget 3000".'
        )
    today = ctx.today()
    lines = [f"- {describe_trip(t, today)}" for t in trips]
    # Trips they were added to: the plan only, so no budget or any money is in these.
    lines += [
        f"- {describe_trip(t, today)} [{_owner(name)}'s trip, shared with the user: they "
        "can change its plan, not its money or details]"
        for t, name in shared
    ]
    return ToolResult("Trips:\n" + "\n".join(lines))


def _owner(name: str | None) -> str:
    return clean_name(name) or "someone"


async def _trip_status(ctx: ToolContext, a: TripNameArgs) -> ToolResult:
    found = await _found(ctx, a.trip)
    trip = found.trip
    if found.shared:
        # The plan as a member sees it: nothing is worked out from the owner's ledger.
        plan = await access_cases.plan_view(
            ctx.uow(), found.owner_id, trip.id, ctx.user, now=ctx.now
        )
        lines = access_cases.describe_plan(plan)
        bookings = plan.bookings
        head = (
            f"The {trip.destination} plan, shared with the user by {found.owner_label}. It has "
            f"no money in it, and only {found.owner_label} can see or change that "
            "(quote it as it is):"
        )
    else:
        view = await trip_cases.trip_view(ctx.uow, rates(ctx), ctx.user, trip.id, now=ctx.now)
        lines = trip_cases.describe_view(view)
        bookings = view.bookings
        head = "Trip figures, worked out in code (quote them as they are):"
    watch = [
        f"{day:%a %d %b}: {note.text}"
        for day in itinerary.days_of(bookings)
        for note in itinerary.day_notes(
            itinerary.on_day(bookings, day), day, in_trip=trip.start <= day <= trip.end
        )
    ]
    if watch:
        lines += ["Worth a look on the itinerary (worked out in code):", *watch]
    return ToolResult(head + "\n" + "\n".join(lines))


SPECS: list[ToolSpec] = [
    ToolSpec(
        "create_trip",
        "Save a trip the user is planning or on: destination, dates, the currency "
        "spent there, and optionally a budget, who's going and an amount to set aside "
        "each payday. Asks the user to confirm.",
        TripArgs,
        _create_trip,
        confirm=_describe_create_trip,
    ),
    ToolSpec(
        "update_trip",
        "Change a saved trip's dates, budget, companions, currency, set-aside or notes. "
        "On a trip the user was added to, only the notes can be changed. Asks the user "
        "to confirm.",
        TripChangeArgs,
        _update_trip,
        confirm=_describe_update_trip,
    ),
    ToolSpec(
        "delete_trip",
        "Delete a saved trip (its expenses stay). Asks the user to confirm.",
        TripNameArgs,
        _delete_trip,
        confirm=_describe_delete_trip,
    ),
    ToolSpec(
        "list_trips",
        "The user's trips, past and coming up, and the trips others have shared with them.",
        NoArgs,
        _list_trips,
    ),
    ToolSpec(
        "trip_status",
        "One trip's money: spent so far, left in the budget, per day, by category, "
        "money set aside, costs not split yet, what others paid, and who owes who "
        "(netted) for it. For a trip someone else shared with the user, the plan only, "
        "with no money.",
        TripNameArgs,
        _trip_status,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"list_trips", "trip_status"})

MENU: dict[str, MenuSection] = {
    "create_trip": MenuSection.TRAVEL,
    "delete_trip": MenuSection.TRAVEL,
    "list_trips": MenuSection.TRAVEL,
    "trip_status": MenuSection.TRAVEL,
    "update_trip": MenuSection.TRAVEL,
}
