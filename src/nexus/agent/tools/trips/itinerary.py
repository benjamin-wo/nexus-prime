"""Tools for a trip's itinerary, to-dos and covers."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from nexus.agent.tools.core import ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import parse_day, parse_money
from nexus.agent.tools.trips.trip import TripNameArgs, _found, _noted, _price_left_out
from nexus.application import bookings as booking_cases
from nexus.application import day_slots
from nexus.application import places as place_cases
from nexus.application import trip_access as access_cases
from nexus.application import trips as trip_cases
from nexus.application.ideas import KINDS as IDEA_KINDS
from nexus.application.places import PlacesError
from nexus.domain import itinerary
from nexus.domain.bookings import Booking, BookingDraft, BookingKind
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import (
    MenuSection,
)
from nexus.domain.money import Money
from nexus.domain.places import Place, place_id
from nexus.domain.trip_access import without_money
from nexus.domain.trips import Trip


class ItineraryArgs(TripNameArgs):
    kind: Literal["activity", "flight", "hotel", "rail"] = Field(
        description="activity for a plan or place to visit (a dinner, tour, market, day "
        "trip), else flight, hotel or rail"
    )
    name: str | None = Field(None, description="A plan's or place's name, or the hotel's name")
    day: str | None = Field(
        None,
        description="A plan's day or a hotel's check-in, 2026-12-12; leave out for a place "
        "to visit that isn't on a day yet",
    )
    category: str | None = Field(
        None, description="A plan's or place's kind: Food, Sight, Shopping, Nature, Nightlife"
    )
    time: str | None = Field(
        None,
        description="A plan's time, like 19:00, when the user said one. Leave it out "
        "otherwise: a plan added to a day without a time is given a free one (today, from "
        "now, so also leave it out for 'we're heading there now')",
    )
    ends: str | None = Field(None, description="When a plan ends, if said, like 21:30")
    after: str | None = Field(
        None,
        description="A plan already on that day this one follows ('gelato after the "
        "castle'): its name or part of it. Only for a plan on a day, with no time said",
    )
    minutes: int | None = Field(
        None,
        ge=10,
        le=600,
        description="How long a plan takes, in minutes, when you can judge it (a gelato "
        "stop 20, a castle 90); left out: by its category (a meal 60, a sight 90)",
    )
    until: str | None = Field(None, description="A hotel's check-out day")
    place: str | None = Field(
        None,
        description="Where: an address or area. For a plan that isn't a specific venue "
        "('seafood lunch', 'beach + wander'), the town or area, so it lands on the map",
    )
    link: str | None = Field(
        None, description="A booking page or menu the user gave (a public https address)"
    )
    number: str | None = Field(None, description="A flight or train number, e.g. SQ12")
    origin: str | None = Field(None, description="A flight or train: from")
    destination: str | None = Field(None, description="A flight or train: to")
    departs: str | None = Field(None, description="Departure, local, like 2026-12-10T08:25")
    arrives: str | None = Field(None, description="Arrival, local")
    provider: str | None = Field(None, description="The airline or rail operator")
    note: str | None = Field(None, description="Anything else worth keeping")
    reference: str | None = Field(None, description="The booking or confirmation number")
    booked_via: str | None = Field(
        None, description="Where it was booked: the airline, hotel, Agoda, Klook"
    )
    cost: str | None = Field(None, description="What it costs, if said")
    currency: str | None = Field(None, description="The cost's currency, if not the home one")
    google_place: str | None = Field(
        None,
        description="A plan's or hotel's Google Maps place id from find_places, when the "
        "user picked one of its results; otherwise leave out and it's matched by name",
    )


def _itinerary_details(a: ItineraryArgs) -> dict[str, object]:
    found = _kind_details(a)
    return {**found, "reference": a.reference, "booked_via": a.booked_via, "link": a.link}


def _kind_details(a: ItineraryArgs) -> dict[str, object]:
    if a.kind == "activity":
        # A place to visit with an idea's kind (Food, Sight…) is filed under that list.
        listed = a.category if not a.day and a.category in IDEA_KINDS else None
        return {"kind": "activity", "name": a.name, "day": a.day, "at": a.time,
                "ends_at": a.ends, "address": a.place, "note": a.note,
                "category": a.category, "list_name": listed}  # fmt: skip
    if a.kind == "hotel":
        return {"kind": "hotel", "hotel": a.name, "address": a.place, "check_in": a.day,
                "check_out": a.until, "note": a.note}  # fmt: skip
    return {
        "kind": a.kind,
        "provider": a.provider,
        "segments": [{"number": a.number, "from": a.origin, "to": a.destination,
                      "departs": a.departs or a.day, "arrives": a.arrives}],
        "note": a.note,
    }  # fmt: skip


async def _place_for(
    ctx: ToolContext, trip: Trip, draft: BookingDraft, chosen: str | None
) -> Place | None:
    """The Google Maps place for a new plan or hotel: the one the user picked from
    find_places, or the top search result when its name plausibly matches. A plan with
    no such venue falls back to the area it's in."""
    if ctx.places is None or draft.kind not in (BookingKind.ACTIVITY, BookingKind.HOTEL):
        return None
    if chosen:
        try:
            return await ctx.places.details(ctx.user.id, chosen)
        except (NotFound, PlacesError):
            raise InvalidInput("that Google Maps place wasn't found; use find_places") from None
    name = (draft.hotel if draft.kind is BookingKind.HOTEL else draft.name) or draft.title
    where = f" {draft.address}" if draft.address else ""
    found = await place_cases.best_match(
        ctx.places, ctx.user.id, name, place_cases.query_for(f"{name}{where}", trip.destination)
    )
    if found is None and draft.kind is BookingKind.ACTIVITY:
        # No venue by that name ("Seafood Lunch in Kamakura"): the area it's in keeps the
        # plan on the map, so the day still has travel times around it.
        return await place_cases.best_area_match(
            ctx.places, ctx.user.id, name, draft.address, trip.destination
        )
    return found


async def _itinerary_entry(
    ctx: ToolContext, a: ItineraryArgs
) -> tuple[access_cases.Found, BookingDraft, Money | None, Place | None, day_slots.Fitted]:
    found = await _found(ctx, a.trip)
    trip = found.trip
    if a.kind == "hotel" and not a.day:
        # "add my hotel, Hotel Sakura": the stay is the whole trip unless said otherwise.
        a = a.model_copy(
            update={"day": trip.start.isoformat(), "until": a.until or trip.end.isoformat()}
        )
    draft = BookingDraft.from_dict(_itinerary_details(a))
    if draft is None:
        raise InvalidInput(
            "a plan or place needs a name, a hotel its check-in day, and a flight or train "
            "its departure time"
        )
    # What an entry cost is the owner's money: a member's entry carries none.
    cost = parse_money(ctx, a.cost, a.currency) if a.cost and not found.shared else None
    place = await _place_for(ctx, trip, draft, a.google_place)
    if place is not None:
        draft = replace(draft, place_id=place.id)
    # A plan on a day with no time gets a free one; a time the user gave stays.
    fitted = await day_slots.fit_plan(
        ctx.uow,
        ctx.places,
        ctx.routes,
        ctx.user.id,
        found.owner_id,
        trip,
        draft,
        now=ctx.now.astimezone(ctx.tz),
        after=a.after,
        minutes=a.minutes,
    )
    return found, fitted.draft, cost, place, fitted


def _matched(place: Place | None, asked: str) -> str:
    """Which Google Maps place an entry matched, but only when its name differs from what
    was asked ("Ichiran" matching "Ichiran Shibuya" isn't worth saying)."""
    if place is None or place_cases.named_alike(asked, place):
        return ""
    return f" (matched {place.name} on Google Maps)"


def _plain(found: access_cases.Found, cost: str | None) -> bool:
    """Whether an itinerary change is on the user's own trip and gives no cost: such a
    change is made at once (with Undo) instead of asking first."""
    return not found.shared and not cost


def _chat_edit(ctx: ToolContext) -> booking_cases.ChatEdit:
    """Has an itinerary change recorded for Undo, under this turn's batch. The actor is
    the person chatting (on a shared trip, not the owner whose itinerary it is)."""
    return booking_cases.ChatEdit(ctx.batch or uuid4(), ctx.user.id, ctx.now)


async def _describe_add_to_itinerary(ctx: ToolContext, a: ItineraryArgs) -> str:
    # On one's own trip with no cost it is added at once (and can be undone). Decided
    # before the Google Maps lookup, which the add itself does.
    if _plain(await _found(ctx, a.trip), a.cost):
        return ""
    found, draft, cost, place, fitted = await _itinerary_entry(ctx, a)
    price = f", {cost}" if cost else ""
    return (
        f"Add {draft.brief()}{price} to the {found.trip.destination} trip{found.whose}?"
        f"{_matched(place, a.name or '')}{_confirm_slot(fitted)}"
        f"{_price_left_out(found, a.cost)}"
    )


def _neighbour(b: Booking, day: date) -> str:
    """An entry as it's named beside a plan's new time: 'the 15:00 train to Riverton',
    'Hill Fort'."""
    d = b.draft
    if d.kind not in (BookingKind.FLIGHT, BookingKind.RAIL):
        return d.title
    what = "train" if d.kind is BookingKind.RAIL else "flight"
    out, back = itinerary.leaving(b, day), itinerary.landing(b, day)
    if out and out[0].departs:
        to = f" to {out[0].destination}" if out[0].destination else ""
        return f"the {out[0].departs:%H:%M} {what}{to}"
    if back and back[-1].arrives:
        origin = f" from {back[-1].origin}" if back[-1].origin else ""
        return f"the {back[-1].arrives:%H:%M} {what}{origin}"
    return d.title


_NO_ROOM = "no free time that day before 23:00, so it has no time and comes last"


def _slot_note(fitted: day_slots.Fitted) -> str:
    """The time picked for a plan and where it sits among the day's entries ("13:15 to
    14:45, before the 15:00 train to Riverton"); empty when the user gave a time, or when
    there was no room."""
    day, slot = fitted.draft.day, fitted.slot
    if slot is None or day is None:
        return ""
    if fitted.after is not None and itinerary.finish(fitted.after, day) is not None:
        near = f"after {_neighbour(fitted.after, day)}"
    elif slot.next is not None:
        near = f"before {_neighbour(slot.next, day)}"
    elif slot.previous is not None:
        near = f"after {_neighbour(slot.previous, day)}"
    else:
        near = ""
    return f"{slot.start:%H:%M}\u2013{slot.end:%H:%M}" + (f", {near}" if near else "")


def _confirm_slot(fitted: day_slots.Fitted) -> str:
    if note := _slot_note(fitted):
        return f" (time picked: {note})"
    return f" ({_NO_ROOM})" if fitted.picked else ""


def _fitted_line(fitted: day_slots.Fitted) -> str:
    if note := _slot_note(fitted):
        return f" Time picked to fit the day: {note}."
    return f" Not given a time: {_NO_ROOM} (say so)." if fitted.picked else ""


async def _add_to_itinerary(ctx: ToolContext, a: ItineraryArgs) -> ToolResult:
    found, draft, cost, place, fitted = await _itinerary_entry(ctx, a)
    booking = await booking_cases.add_manual(
        ctx.uow(),
        found.owner_id,
        found.trip.id,
        draft.as_dict(),
        cost,
        now=ctx.now,
        record=_chat_edit(ctx),
    )
    await _noted(ctx, found, f"added {booking.draft.title}")
    text = (
        f"Added {draft.brief()} to the {found.trip.destination} trip{found.whose}."
        f"{_matched(place, a.name or '')}{_fitted_line(fitted)}"
    )
    if place is not None and (warning := place.warning(draft.day, draft.at)):
        text += f" Note: {warning} (Google Maps' regular hours)."
    return ToolResult(text + _price_left_out(found, a.cost), wrote=True)


class ItineraryItemArgs(TripNameArgs):
    item: str = Field(description="The entry's name or part of it, as the user says it")


async def _find_item(ctx: ToolContext, a: ItineraryItemArgs) -> tuple[access_cases.Found, Booking]:
    found = await _found(ctx, a.trip)
    async with ctx.uow() as tx:
        items = await tx.trips.list_bookings(found.owner_id, trip_id=found.trip.id)
    match = itinerary.match_entry(items, a.item)
    # A member never gets what the entry cost.
    return found, without_money(match) if found.shared else match


async def _describe_remove_from_itinerary(ctx: ToolContext, a: ItineraryItemArgs) -> str:
    found, item = await _find_item(ctx, a)
    # An entry with a cost, or an expense logged from it, still asks first.
    if _plain(found, None) and item.cost is None and item.transaction_id is None:
        return ""
    return f"Remove {item.draft.brief()} from the {found.trip.destination} trip{found.whose}?"


async def _remove_from_itinerary(ctx: ToolContext, a: ItineraryItemArgs) -> ToolResult:
    found, item = await _find_item(ctx, a)
    await booking_cases.delete_booking(ctx.uow(), found.owner_id, item.id, record=_chat_edit(ctx))
    await _noted(ctx, found, f"removed {item.draft.title}")
    return ToolResult(
        f"Removed {item.draft.brief()} from the {found.trip.destination} trip{found.whose}.",
        wrote=True,
    )


class DayLabelArgs(TripNameArgs):
    day: str = Field(description="The day, 2026-12-12")
    label: str = Field(description="The label, such as a city; empty to clear it")


async def _label_day(ctx: ToolContext, a: DayLabelArgs) -> ToolResult:
    found = await _found(ctx, a.trip)
    day = parse_day(ctx, a.day).date()
    trip = await trip_cases.set_day_label(
        ctx.uow(), found.owner, found.trip.id, day, a.label, now=ctx.now
    )
    number = (day - trip.start).days + 1
    label = trip.day_labels.get(day)
    await _noted(
        ctx,
        found,
        f'named Day {number} "{label}"' if label else f"cleared the name of Day {number}",
    )
    what = f"labelled {a.label.strip()!r}" if a.label.strip() else "unlabelled"
    return ToolResult(
        f"{day:%a %d %b} of the {trip.destination} trip{found.whose} is {what}.", wrote=True
    )


class ItineraryChangeArgs(ItineraryItemArgs):
    name: str | None = Field(None, description="A new name for a plan or hotel")
    day: str | None = Field(
        None,
        description="A new day for a plan (this puts a place to visit on that day), or "
        "check-in for a hotel",
    )
    category: str | None = Field(None, description="A new kind: Food, Sight, Shopping")
    time: str | None = Field(None, description="A plan's new time, like 19:00")
    ends: str | None = Field(None, description="A plan's new end time, like 21:30")
    minutes: int | None = Field(
        None,
        ge=1,
        le=1440,
        description="How long the plan lasts, in minutes; sets the end time from the start",
    )
    until: str | None = Field(None, description="A hotel's new check-out day")
    place: str | None = Field(None, description="A new address or area")
    link: str | None = Field(None, description="A new booking page or menu (public https)")
    after: str | None = Field(
        None,
        description="Another entry on that day this plan should come right after, by name "
        "('after the temple'); 'first' to put it first",
    )
    number: str | None = Field(None, description="A new flight or train number")
    origin: str | None = Field(None, description="A flight or train's new from")
    destination: str | None = Field(None, description="A flight or train's new to")
    departs: str | None = Field(None, description="New departure, local, 2026-12-10T08:25")
    arrives: str | None = Field(None, description="New arrival, local")
    provider: str | None = Field(None, description="The airline or rail operator")
    note: str | None = Field(None, description="A new note, replacing the old one")
    reference: str | None = Field(None, description="The booking or confirmation number")
    booked_via: str | None = Field(None, description="Where it was booked")
    cost: str | None = Field(None, description="A new cost, if said")
    currency: str | None = Field(None, description="The cost's currency, if not the home one")
    google_place: str | None = Field(
        None, description="A Google Maps place id from find_places, to link it to that place"
    )


async def _changed_entry(
    ctx: ToolContext,
    a: ItineraryChangeArgs,
    opened: tuple[access_cases.Found, Booking] | None = None,
) -> tuple[access_cases.Found, Booking, BookingDraft, Money | None]:
    """The entry with only what the user changed: the rest is kept. ``opened`` is the
    trip and entry when already looked up."""
    found, item = opened or await _find_item(ctx, a)
    data = item.draft.as_dict()
    hotel = item.draft.kind is BookingKind.HOTEL
    fields = {
        "hotel" if hotel else "name": a.name,
        "check_in" if hotel else "day": a.day,
        "at": a.time,
        "ends_at": a.ends,
        "check_out": a.until,
        "address": a.place,
        "link": a.link,
        "provider": a.provider,
        "note": a.note,
        "reference": a.reference,
        "booked_via": a.booked_via,
        "category": a.category,
    }
    data.update({k: v for k, v in fields.items() if v is not None})
    if a.google_place:
        if place_id(a.google_place) is None:
            raise InvalidInput("that isn't a Google Maps place id; use find_places")
        data["place_id"] = a.google_place.strip()
    leg = {"number": a.number, "from": a.origin, "to": a.destination,
           "departs": a.departs, "arrives": a.arrives}  # fmt: skip
    if any(v is not None for v in leg.values()):
        segments = data["segments"] or [{}]
        segments[0] = {**segments[0], **{k: v for k, v in leg.items() if v is not None}}
        data["segments"] = segments
    draft = BookingDraft.from_dict(data)
    if draft is None:
        raise InvalidInput("that change leaves the entry without a date")
    if a.minutes is not None:
        draft = _lasting(a, data, draft)
    # A member's change keeps the cost the entry had (it is the owner's money).
    cost = parse_money(ctx, a.cost, a.currency) if a.cost and not found.shared else item.cost
    return found, item, draft, cost


def _lasting(a: ItineraryChangeArgs, data: dict[str, Any], draft: BookingDraft) -> BookingDraft:
    """The plan ending ``a.minutes`` after its start (the new time if one was given, else
    the one it had); an error when it has no start or ``a.ends`` says another end."""
    if draft.kind is not BookingKind.ACTIVITY or draft.day is None:
        raise InvalidInput("only a plan on a day has a length")
    if draft.at is None:
        raise InvalidInput("that plan has no start time; give its time as well")
    end = datetime.combine(date.min, draft.at) + timedelta(minutes=a.minutes or 0)
    if end.date() != date.min:
        raise InvalidInput("that would run past midnight; give a shorter length")
    if a.ends is not None and draft.ends_at != end.time():
        raise InvalidInput(
            f"ends {a.ends} and minutes {a.minutes} disagree; give one of them, or matching ones"
        )
    longer = BookingDraft.from_dict({**data, "ends_at": end.time().isoformat(timespec="minutes")})
    if longer is None:  # pragma: no cover - the draft had a date a moment ago
        raise InvalidInput("that change leaves the entry without a date")
    return longer


async def _after(
    ctx: ToolContext,
    a: ItineraryChangeArgs,
    found: access_cases.Found,
    item: Booking,
    draft: BookingDraft,
) -> tuple[bool, Booking | None]:
    """Whether the plan is to be placed in its day's order, and after which entry (None:
    first)."""
    if not a.after:
        return False, None
    if draft.kind is not BookingKind.ACTIVITY or draft.day is None:
        raise InvalidInput("only a plan on a day can be put after another entry")
    wanted = a.after.strip().casefold()
    if wanted == "first":
        return True, None
    async with ctx.uow() as tx:
        items = await tx.trips.list_bookings(found.owner_id, trip_id=found.trip.id)
    there = [b for b in itinerary.on_day(items, draft.day) if b.id != item.id]
    matches = [b for b in there if wanted in b.draft.title.casefold()]
    if len(matches) != 1:
        listed = "; ".join(b.draft.title for b in there) or "nothing else"
        raise NotFound(f"no single entry that day matches {a.after!r}; that day has: {listed}")
    return True, matches[0]


async def _describe_change_itinerary(ctx: ToolContext, a: ItineraryChangeArgs) -> str:
    opened = await _find_item(ctx, a)
    found, item = opened
    # An entry that has a cost or a logged expense still asks first, as does a new cost.
    if _plain(found, a.cost) and item.cost is None and item.transaction_id is None:
        return ""
    found, item, draft, cost = await _changed_entry(ctx, a, opened)
    price = f", {cost}" if cost else ""
    moving, after = await _after(ctx, a, found, item, draft)
    where = (f", after {after.draft.title}" if after else ", first that day") if moving else ""
    return (
        f"Change {item.draft.brief(span=True)} to {draft.brief(span=True)}{price}{where} on the "
        f"{found.trip.destination} trip{found.whose}?{_price_left_out(found, a.cost)}"
    )


async def _change_itinerary(ctx: ToolContext, a: ItineraryChangeArgs) -> ToolResult:
    found, item, draft, cost = await _changed_entry(ctx, a)
    moving, after = await _after(ctx, a, found, item, draft)
    edit = _chat_edit(ctx)
    changed = await booking_cases.edit_booking(
        ctx.uow(),
        found.owner_id,
        item.id,
        draft.as_dict(),
        cost,
        keep_cost=found.shared,
        record=edit,
    )
    await _noted(ctx, found, f"changed {changed.draft.title}")
    if moving:
        moved = await booking_cases.move_entry(
            ctx.uow(),
            found.owner_id,
            item.id,
            draft.day,
            after.id if after else None,
            record=edit,
        )
        if moved.draft.day is not None:
            number = (moved.draft.day - found.trip.start).days + 1
            await _noted(ctx, found, f"moved {moved.draft.title} to Day {number}")
    return ToolResult(
        f"Changed to {draft.brief(span=True)} on the {found.trip.destination} trip{found.whose}."
        + _price_left_out(found, a.cost),
        wrote=True,
    )


SPECS: list[ToolSpec] = [
    ToolSpec(
        "add_to_itinerary",
        "Add an entry to a trip's itinerary by hand: a plan (dinner, tour, day trip), a "
        "flight, a hotel stay or a train. A plan on a day with no `time` is given a free "
        "time by itself (today from now; use `after` to put it after another plan, "
        "`minutes` for how long it takes); the reply says the time it got. For a plan that "
        "isn't a specific venue, pass the town or area as `place`. Saves at once, "
        "with Undo; asks to confirm when it carries a cost or is on someone else's trip.",
        ItineraryArgs,
        _add_to_itinerary,
        confirm=_describe_add_to_itinerary,
    ),
    ToolSpec(
        "change_itinerary_entry",
        "Change an entry already on a trip's itinerary (a hotel's check-out, a plan's "
        "time, a flight's departure), keeping what isn't changed. Saves at once, with Undo; "
        "asks to confirm when it carries a cost or is on someone else's trip.",
        ItineraryChangeArgs,
        _change_itinerary,
        confirm=_describe_change_itinerary,
    ),
    ToolSpec(
        "label_trip_day",
        "Name a day of a trip, such as the city the user is in that day ('Busan'; 'we're "
        "in Kyoto on 15 Dec' labels 15 Dec 'Kyoto') or its plan ('Day trip to Nikko'). An "
        "empty label clears it.",
        DayLabelArgs,
        _label_day,
    ),
    ToolSpec(
        "remove_from_itinerary",
        "Take an entry off a trip's itinerary. Saves at once, with Undo; asks to confirm "
        "when the entry has a cost or it is on someone else's trip.",
        ItineraryItemArgs,
        _remove_from_itinerary,
        confirm=_describe_remove_from_itinerary,
    ),
]

MENU: dict[str, MenuSection] = {
    "add_to_itinerary": MenuSection.TRAVEL,
    "change_itinerary_entry": MenuSection.TRAVEL,
    "label_trip_day": MenuSection.TRAVEL,
    "remove_from_itinerary": MenuSection.TRAVEL,
}
