"""Tools that research a destination and add the findings to a trip."""

from datetime import date
from uuid import UUID

from pydantic import Field

from nexus.agent.tools.core import Args, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import parse_day
from nexus.agent.tools.trips.itinerary import _chat_edit
from nexus.agent.tools.trips.trip import TripNameArgs, _home_money, _mine
from nexus.application import travel_research as trip_research
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import (
    MenuSection,
)
from nexus.domain.trips import Trip


class ResearchArgs(Args):
    destination: str = Field(description="Where: a city, region or country")
    month: str | None = Field(None, description="The month, like 2027-01, if dates aren't set")
    start: str | None = Field(None, description="First day if known, like 2027-01-10")
    end: str | None = Field(None, description="Last day if known")
    nights: int | None = Field(None, ge=1, le=30, description="How many nights, if said")
    flexible: bool = Field(True, description="Whether the dates can move")
    travellers: int = Field(1, ge=1, le=8, description="How many people are going")
    budget: str | None = Field(
        None, description="Their budget in the home currency; leave out to have it estimated"
    )
    currency: str | None = Field(None, description="The currency spent there, e.g. JPY")
    home_airport: str | None = Field(None, description="Their home airport code, e.g. SIN")
    airport: str | None = Field(None, description="The main airport there, e.g. NRT")
    notes: str | None = Field(None, description="Preferences that matter: food, pace, budget")


def _month(ctx: ToolContext, value: str | None) -> date | None:
    if not value:
        return None
    try:
        year, month = (int(p) for p in value.strip()[:7].split("-"))
        return date(year, month, 1)
    except ValueError as exc:
        raise InvalidInput(f"months look like 2027-01, not {value!r}") from exc


async def _research_trip(ctx: ToolContext, a: ResearchArgs) -> ToolResult:
    if ctx.departments is None:
        return ToolResult("Trip research isn't set up.")
    budget = _home_money(ctx, a.budget)
    task = {
        "destination": a.destination,
        "month": _month(ctx, a.month),
        "start": parse_day(ctx, a.start).date() if a.start else None,
        "end": parse_day(ctx, a.end).date() if a.end else None,
        "nights": a.nights,
        "flexible": a.flexible,
        "travellers": a.travellers,
        "budget": budget.amount if budget else None,
        "currency": a.currency.upper() if a.currency else None,
        "home_airport": a.home_airport,
        "airport": a.airport,
        "notes": a.notes,
    }
    run = await trip_research.start_research(ctx.uow, ctx.departments, ctx.user, task, now=ctx.now)
    return ToolResult(
        f"Started '{run.title}': {run.steps_total} steps (when to go, costs, where to stay, "
        "the budget from their money), usually two or three minutes. Progress shows in one "
        "Telegram message with a Cancel button; the research arrives there with a 'Make it a "
        "trip' button, and on the web app under Travel. Don't guess prices or dates meanwhile."
    )


class ResearchToTripArgs(TripNameArgs):
    research: str | None = Field(
        None,
        description="Where the research was about ('Japan'); leave out for the latest "
        "finished research (the one for this trip's destination, if there is one)",
    )
    areas: list[str] | None = Field(
        None, description="Which of the research's areas to add, by name; leave out for all"
    )


async def _research_for(ctx: ToolContext, a: ResearchToTripArgs) -> tuple[Trip, UUID, list[str]]:
    trip = await _mine(ctx, a.trip)  # ideas from a research are the owner's to add
    try:
        run_id = await trip_research.latest_research(
            ctx.uow(), ctx.user, a.research or trip.destination, now=ctx.now
        )
    except NotFound:
        if a.research:
            raise
        run_id = await trip_research.latest_research(ctx.uow(), ctx.user, None, now=ctx.now)
    result = await trip_research.research_result(ctx.uow(), ctx.user, run_id)
    names = [n for n in (a.areas or []) if n.strip()] or [x.name for x in result.areas]
    return trip, run_id, names


async def _describe_research_to_trip(ctx: ToolContext, a: ResearchToTripArgs) -> str:
    trip, _, names = await _research_for(ctx, a)
    return (
        f"Add the things to do in {', '.join(names)} from the research to the "
        f"{trip.destination} trip as ideas (up to {trip_research.IDEAS_PER_AREA} per area, "
        "each under a list named after its area)?"
    )


async def _research_to_trip(ctx: ToolContext, a: ResearchToTripArgs) -> ToolResult:
    trip, run_id, names = await _research_for(ctx, a)
    found = await trip_research.ideas_from_areas(
        ctx.uow, ctx.places, ctx.user, run_id, trip.id, names, now=ctx.now, record=_chat_edit(ctx)
    )
    text = f"Added {found.added} ideas to the {trip.destination} trip"
    if found.skipped:
        text += f" ({found.skipped} were already there)"
    text += ". They're under Ideas on the trip page, in a list per area."
    if found.stop_suggestion:
        text += (
            f" The research was for {found.stop_suggestion}, which isn't one of the trip's "
            "stops; they can add it as a stop on the trip page."
        )
    return ToolResult(text, wrote=found.added > 0)


SPECS: list[ToolSpec] = [
    ToolSpec(
        "research_trip",
        "Research a trip in the background: when to go, flight, hotel and daily costs "
        "with sources, areas to stay, getting around, and a budget card from the "
        "user's money. Ask how flexible the dates are, who's going and the budget first.",
        ResearchArgs,
        _research_trip,
    ),
    ToolSpec(
        "research_to_trip",
        "Add the things to do from a finished trip research's areas to a trip as ideas "
        "(places to visit, one list per area; ones already there are skipped). Asks the "
        "user to confirm.",
        ResearchToTripArgs,
        _research_to_trip,
        confirm=_describe_research_to_trip,
    ),
]

MENU: dict[str, MenuSection] = {
    "research_to_trip": MenuSection.TRAVEL,
    "research_trip": MenuSection.TRAVEL,
}
