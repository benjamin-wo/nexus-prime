"""Tools that add to-dos and covers to a trip."""

from typing import Literal

from pydantic import Field

from nexus.agent.tools.core import ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import parse_day, parse_money
from nexus.agent.tools.trips.trip import TripNameArgs, _found, _noted, _price_left_out
from nexus.application import prep as prep_cases
from nexus.application import trip_access as access_cases
from nexus.domain.ledger import (
    MenuSection,
)
from nexus.domain.prep import CoverDraft, CoverKind, clean_cover


class TripTodoArgs(TripNameArgs):
    text: str = Field(
        description="The to-do in a few words, like 'Get yen' (at most 80 characters)"
    )
    due: str | None = Field(
        None,
        description="The day it's due, like 2026-12-08. Work 'two days before the trip' out "
        "from the trip's first day (list_trips or trip_status show its dates); leave out "
        "when no day was said",
    )


async def _add_trip_todo(ctx: ToolContext, a: TripTodoArgs) -> ToolResult:
    found = await _found(ctx, a.trip)
    due = parse_day(ctx, a.due).date() if a.due else None
    trip, added = await prep_cases.add_todo(
        ctx.uow(), found.owner, found.trip.id, a.text, due, now=ctx.now
    )
    where = f"the {trip.destination} trip's to-do list{found.whose}"
    if added is None:
        return ToolResult(f"{a.text.strip()!r} is on {where} already.")
    await _noted(ctx, found, f"added the to-do {added.text}")
    when = f", due {due:%a %d %b}. I'll remind them the day before" if due else ""
    return ToolResult(f"Added to {where}: {added.text}{when}.", wrote=True)


class TripCoverArgs(TripNameArgs):
    kind: Literal["insurance", "visa", "document", "other"] = Field(
        description="insurance for travel insurance, visa for a visa or entry permit, "
        "document for another document, else other"
    )
    name: str = Field(description="What it is called, like 'Harbour Cover' (at most 80 characters)")
    reference: str | None = Field(
        None, description="The policy, visa or document number, as the user gave it"
    )
    phone: str | None = Field(None, description="The number to call (emergency or claims)")
    cost: str | None = Field(None, description="What it cost, if said")
    currency: str | None = Field(None, description="The cost's currency, if not the home one")
    starts: str | None = Field(None, description="The first day it covers, like 2026-12-10")
    ends: str | None = Field(None, description="The last day it covers")


async def _cover_entry(ctx: ToolContext, a: TripCoverArgs) -> tuple[access_cases.Found, CoverDraft]:
    found = await _found(ctx, a.trip)
    # What a cover cost is the owner's money: a member's cover carries none.
    cost = parse_money(ctx, a.cost, a.currency) if a.cost and not found.shared else None
    draft = CoverDraft(
        kind=CoverKind(a.kind),
        name=a.name,
        reference=a.reference,
        phone=a.phone,
        starts=parse_day(ctx, a.starts).date() if a.starts else None,
        ends=parse_day(ctx, a.ends).date() if a.ends else None,
        cost=cost,
    )
    # Checked here, so the confirmation shows what would be kept (and a card or passport
    # number is refused before the user is asked).
    return found, clean_cover(draft)


async def _describe_add_trip_cover(ctx: ToolContext, a: TripCoverArgs) -> str:
    found, draft = await _cover_entry(ctx, a)
    price = f", {draft.cost}" if draft.cost else ""
    return (
        f"Add to the {found.trip.destination} trip's cover and documents{found.whose}: "
        f"{draft.describe()}{price}?{_price_left_out(found, a.cost)}"
    )


async def _add_trip_cover(ctx: ToolContext, a: TripCoverArgs) -> ToolResult:
    found, draft = await _cover_entry(ctx, a)
    cover = await prep_cases.add_cover(ctx.uow(), found.owner, found.trip.id, draft, now=ctx.now)
    await _noted(ctx, found, f"added {cover.name} to cover and documents")
    text = (
        f"Added to the {found.trip.destination} trip's cover and documents{found.whose}: "
        f"{cover.describe()}."
    )
    if cover.cost is not None:
        text += (
            f" Its cost, {cover.cost}, counts under Money with the trip's bookings, and can be "
            "logged as an expense from the trip's page once it's paid."
        )
    return ToolResult(text + _price_left_out(found, a.cost), wrote=True)


SPECS: list[ToolSpec] = [
    ToolSpec(
        "add_trip_todo",
        "Add a to-do to a trip's Prep list ('get yen', 'check my passport'), with a due "
        "date if the user gave one. A to-do with a due date is reminded the day before. "
        "Saves at once.",
        TripTodoArgs,
        _add_trip_todo,
    ),
    ToolSpec(
        "add_trip_cover",
        "Add travel insurance, a visa or another document to a trip's cover and "
        "documents: its name, reference, the number to call, the dates and what it cost. "
        "Never a card or passport number. Asks the user to confirm. Pays and claims "
        "nothing.",
        TripCoverArgs,
        _add_trip_cover,
        confirm=_describe_add_trip_cover,
    ),
]

MENU: dict[str, MenuSection] = {
    "add_trip_cover": MenuSection.TRAVEL,
    "add_trip_todo": MenuSection.TRAVEL,
}
