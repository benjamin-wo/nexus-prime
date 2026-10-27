"""Itinerary entries added by hand (flights, hotels, trains and plans) and notes on a
trip. Every name, number and place here is made up."""

from datetime import date, time
from uuid import uuid4

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import bookings as booking_cases
from nexus.application import trips as trip_cases
from nexus.domain import itinerary
from nexus.domain.bookings import BookingKind
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.money import Money
from tests.fakes import NOW, FakeRates
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

RATES = FakeRates({("JPY", "SGD"): {date(2026, 9, 1): "0.0090"}})


async def test_plans_flights_and_notes_added_by_hand(uow: UowFactory) -> None:
    user = await person(uow)
    other = await person(uow, 5151)
    trip = await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft(
            "Tokyo", date(2026, 12, 10), date(2026, 12, 18), "JPY", Money.of("3000", "SGD"),
            notes="Pack a power adapter.\nBooking reference: XK7Q9P\nCard 4111 1111 1111 1111",
        ),
        now=NOW,
    )  # fmt: skip
    assert trip.notes == "Pack a power adapter.\nBooking reference: XK7Q9P\nCard •••• 1111"

    dinner = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "activity", "name": "Dinner at Sushi Ten", "day": "2026-12-12", "at": "19:00",
         "address": "1-2-3 Ginza", "note": "Window seat, flight SQ638 lands at 16:00"},
        Money.of("30000", "JPY"), now=NOW,
    )  # fmt: skip
    assert dinner.draft.kind is BookingKind.ACTIVITY and dinner.draft.at == time(19, 0)
    assert dinner.draft.note == "Window seat, flight SQ638 lands at 16:00"  # a flight number stays
    flight = await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "flight", "provider": "Acme Air",
         "segments": [
             {"number": "ZZ12", "from": "SIN", "to": "NRT", "departs": "2026-12-10T08:25"}
         ]},
        None, now=NOW,
    )  # fmt: skip
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert [b.draft.title for b in view.bookings] == ["ZZ12 SIN → NRT", "Dinner at Sushi Ten"]
    assert view.booked == Money.of("270", "SGD") and view.booked_unlogged == Money.of("270", "SGD")
    lines = trip_cases.describe_view(view)
    assert "plan (Dinner at Sushi Ten, Sat 12 Dec 19:00, 1-2-3 Ginza)" in " ".join(lines)
    assert "Notes: Pack a power adapter." in lines[0]

    moved = await booking_cases.edit_booking(
        uow(), user.id, dinner.id,
        {"kind": "activity", "name": "Dinner at Sushi Ten", "day": "2026-12-13", "at": "20:00"},
        None,
    )  # fmt: skip
    assert (moved.draft.day, moved.cost) == (date(2026, 12, 13), None)

    with pytest.raises(InvalidInput, match="needs a name"):
        await booking_cases.add_manual(
            uow(), user.id, trip.id, {"kind": "activity", "day": "2026-12-12"}, None, now=NOW
        )
    with pytest.raises(InvalidInput, match="departure date"):
        await booking_cases.add_manual(
            uow(), user.id, trip.id, {"kind": "flight", "segments": []}, None, now=NOW
        )
    with pytest.raises(NotFound):
        await booking_cases.add_manual(
            uow(),
            other.id,
            trip.id,
            {"kind": "activity", "name": "x", "day": "2026-12-12"},
            None,
            now=NOW,
        )
    with pytest.raises(NotFound):
        await booking_cases.edit_booking(
            uow(), other.id, flight.id, {"kind": "activity", "name": "x", "day": "2026-12-12"}, None
        )
    await booking_cases.delete_booking(uow(), user.id, flight.id)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert [b.id for b in view.bookings] == [dinner.id]
    with pytest.raises(NotFound):
        await booking_cases.delete_booking(uow(), user.id, uuid4())


async def test_hotels_in_chat_default_to_the_trip_and_can_be_changed(uow: UowFactory) -> None:
    user = await person(uow)
    await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Osaka", date(2026, 12, 10), date(2026, 12, 14), "JPY", None),
        now=NOW,
    )
    tools = build_tools(lambda _: "")
    ctx = ToolContext(user, uow, NOW, RATES)

    async def use(name: str, args: dict[str, object]) -> str:
        return (await run_tool(tools[name], ctx, args)).text

    # No dates given: the stay is the whole trip.
    added = await use("add_to_itinerary", {"kind": "hotel", "name": "Hotel Kawa"})
    assert added == "Added Hotel Kawa (10 Dec to 14 Dec) to the Osaka trip."
    await use("add_to_itinerary", {"kind": "activity", "name": "Castle tour", "day": "2026-12-11"})
    # Only what changed changes.
    change = tools["change_itinerary_entry"]
    assert change.confirm is not None
    # Nothing to ask on one's own trip when no cost is involved: it is made at once.
    assert await change.confirm(ctx, change.parse({"item": "kawa", "until": "2026-12-13"})) == ""
    changed = await use("change_itinerary_entry", {"item": "kawa", "until": "2026-12-13"})
    assert changed == "Changed to Hotel Kawa (10 Dec to 13 Dec) on the Osaka trip."
    moved = await use("change_itinerary_entry", {"item": "castle", "time": "10:30"})
    assert moved == "Changed to Castle tour (Fri 11 Dec 10:30) on the Osaka trip."
    async with uow() as tx:
        stored = await tx.trips.list_bookings(user.id)
    (hotel,) = [b for b in stored if b.draft.kind is BookingKind.HOTEL]
    assert (hotel.draft.check_in, hotel.draft.check_out) == (date(2026, 12, 10), date(2026, 12, 13))
    missing = await use("change_itinerary_entry", {"item": "museum", "time": "09:00"})
    assert "no single itinerary entry matches 'museum'" in missing


async def test_places_to_visit_days_and_what_the_trip_still_needs(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Seoul", date(2026, 12, 7), date(2026, 12, 10), "KRW", None),
        now=NOW,
    )
    tools = build_tools(lambda _: "")
    ctx = ToolContext(user, uow, NOW, RATES)

    async def use(name: str, args: dict[str, object]) -> str:
        return (await run_tool(tools[name], ctx, args)).text

    # A place without a day is kept on the trip, not on the itinerary.
    saved = await use(
        "add_to_itinerary",
        {"kind": "activity", "name": "Namdaemun Market", "category": "Shopping", "cost": "20000",
         "currency": "KRW"},
    )  # fmt: skip
    assert saved == "Added Namdaemun Market (place to visit) to the Seoul trip."
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    (place,) = view.bookings
    assert not place.scheduled and view.booked is None  # an idea isn't booked
    lines = " ".join(trip_cases.describe_view(view))
    assert "Places to visit, not on a day yet: place to visit (Namdaemun Market" in lines
    assert "No place to stay on the itinerary yet for the night of: Mon 07 Dec" in lines
    assert "No flight or train on the itinerary yet." in lines
    assert view.ready.nights_without_stay == [date(2026, 12, d) for d in (7, 8, 9)]

    # Given a day, it's on the itinerary.
    moved = await use("change_itinerary_entry", {"item": "namdaemun", "day": "2026-12-08"})
    assert moved == "Changed to Namdaemun Market (Tue 08 Dec) on the Seoul trip."
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert view.bookings[0].scheduled

    # Days take a label, kept when the trip changes and dropped when the day goes.
    labelled = await use("label_trip_day", {"day": "2026-12-09", "label": "Busan"})
    assert labelled == "Wed 09 Dec of the Seoul trip is labelled 'Busan'."
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert "Days: Wed 09 Dec Busan." in trip_cases.describe_view(view)
    longer = trip_cases.draft_of(view.trip)
    kept = await trip_cases.update_trip(
        uow(), user, trip.id,
        trip_cases.TripDraft(longer.destination, longer.start, date(2026, 12, 11), "KRW"),
        now=NOW,
    )  # fmt: skip
    assert kept.day_labels == {date(2026, 12, 9): "Busan"}
    shorter = await trip_cases.update_trip(
        uow(), user, trip.id,
        trip_cases.TripDraft("Seoul", date(2026, 12, 7), date(2026, 12, 8), "KRW"),
        now=NOW,
    )  # fmt: skip
    assert shorter.day_labels == {}
    with pytest.raises(InvalidInput, match="isn't one of the trip's days"):
        await trip_cases.set_day_label(uow(), user, trip.id, date(2026, 12, 20), "X", now=NOW)


async def test_chat_puts_a_plan_after_another_and_says_what_clashes(uow: UowFactory) -> None:
    user = await person(uow)
    await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Osaka", date(2026, 12, 10), date(2026, 12, 14), "JPY", None),
        now=NOW,
    )
    tools = build_tools(lambda _: "")
    ctx = ToolContext(user, uow, NOW, RATES)

    async def use(name: str, args: dict[str, object]) -> str:
        return (await run_tool(tools[name], ctx, args)).text

    day = "2026-12-11"
    added = await use(
        "add_to_itinerary",
        {"kind": "activity", "name": "Tea ceremony", "day": day, "time": "14:00",
         "ends": "15:30", "link": "https://tea.example.com/book"},
    )  # fmt: skip
    assert added == "Added Tea ceremony (Fri 11 Dec 14:00) to the Osaka trip."
    await use(
        "add_to_itinerary", {"kind": "activity", "name": "Castle tour", "day": day, "time": "15:00"}
    )
    await use("add_to_itinerary", {"kind": "activity", "name": "Kaiten sushi", "day": day})
    # An idea's kind files a place to visit under that list.
    await use("add_to_itinerary", {"kind": "activity", "name": "Night market", "category": "Food"})

    change = tools["change_itinerary_entry"]
    assert change.confirm is not None
    # Putting a plan in order is no cost: no question. With a cost on the entry there is.
    assert await change.confirm(ctx, change.parse({"item": "sushi", "after": "castle"})) == ""
    asked = await change.confirm(
        ctx, change.parse({"item": "sushi", "after": "castle", "cost": "1200", "currency": "JPY"})
    )
    assert asked == (
        "Change Kaiten sushi (Fri 11 Dec 09:00\u201310:00) to Kaiten sushi (Fri 11 Dec "
        "09:00\u201310:00), 1,200 JPY, after Castle tour on the Osaka trip?"
    )
    await use("change_itinerary_entry", {"item": "sushi", "after": "castle"})
    async with uow() as tx:
        stored = await tx.trips.list_bookings(user.id)
    on_day = itinerary.on_day(stored, date(2026, 12, 11))
    assert [b.draft.title for b in on_day] == ["Tea ceremony", "Castle tour", "Kaiten sushi"]
    market = next(b for b in stored if b.draft.title == "Night market")
    assert market.draft.list_name == "Food"
    tea = next(b for b in stored if b.draft.title == "Tea ceremony")
    assert tea.draft.link == "https://tea.example.com/book"
    nowhere = await use("change_itinerary_entry", {"item": "sushi", "after": "museum"})
    assert "no single entry that day matches 'museum'" in nowhere

    status = await use("trip_status", {})
    assert "Worth a look on the itinerary (worked out in code):" in status
    assert "Fri 11 Dec: Tea ceremony (14:00 to 15:30) runs into Castle tour at 15:00" in status


async def test_a_plans_length_is_shown_as_a_range_and_set_in_minutes(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Osaka", date(2026, 12, 10), date(2026, 12, 14), "JPY", None),
        now=NOW,
    )
    for entry in (
        {"name": "Shop visit", "at": "10:45", "ends_at": "11:45"},
        {"name": "Sunset walk"},  # on a day, but with no start time
        {"name": "Night market", "day": None},  # a place to visit
    ):
        await booking_cases.add_manual(
            uow(), user.id, trip.id, {"kind": "activity", "day": "2026-12-11", **entry}, None,
            now=NOW,
        )  # fmt: skip
    tools = build_tools(lambda _: "")
    ctx = ToolContext(user, uow, NOW, RATES)

    async def use(args: dict[str, object]) -> str:
        return (await run_tool(tools["change_itinerary_entry"], ctx, args)).text

    async def ends(title: str) -> time | None:
        async with uow() as tx:
            stored = await tx.trips.list_bookings(user.id)
        return next(b.draft.ends_at for b in stored if b.draft.title == title)

    # The confirmation and the reply show the range, so a new length can be seen.
    change = tools["change_itinerary_entry"]
    assert change.confirm is not None
    assert await change.confirm(
        ctx, change.parse({"item": "shop", "minutes": 20, "cost": "500", "currency": "JPY"})
    ) == (
        "Change Shop visit (Fri 11 Dec 10:45\u201311:45) to Shop visit (Fri 11 Dec "
        "10:45\u201311:05), 500 JPY on the Osaka trip?"
    )
    # `minutes` sets the end from the start the plan has ...
    assert await use({"item": "shop", "minutes": 20}) == (
        "Changed to Shop visit (Fri 11 Dec 10:45\u201311:05) on the Osaka trip."
    )
    assert await ends("Shop visit") == time(11, 5)
    # ... or from the new time given with it, and agrees with a matching `ends`.
    assert await use({"item": "shop", "time": "14:00", "minutes": 30}) == (
        "Changed to Shop visit (Fri 11 Dec 14:00\u201314:30) on the Osaka trip."
    )
    assert "14:00\u201314:45" in await use({"item": "shop", "ends": "14:45", "minutes": 45})
    # A plan changed without a length keeps its range; one with no end shows only its time.
    assert "(Fri 11 Dec 15:00\u201315:30)" in await use(
        {"item": "shop", "time": "15:00", "ends": "15:30"}
    )

    # Errors change nothing.
    disagree = await use({"item": "shop", "ends": "16:00", "minutes": 20})
    assert disagree.startswith("Error: ends 16:00 and minutes 20 disagree")
    nothing = await use({"item": "sunset", "minutes": 20})
    assert nothing == "Error: that plan has no start time; give its time as well"
    assert await ends("Sunset walk") is None
    assert "give a shorter length" in await use({"item": "shop", "time": "23:50", "minutes": 20})
    assert "only a plan on a day" in await use({"item": "market", "minutes": 20})
    assert await ends("Shop visit") == time(15, 30)
    # With a time it has a start, so it works.
    assert await use({"item": "sunset", "time": "17:00", "minutes": 20}) == (
        "Changed to Sunset walk (Fri 11 Dec 17:00\u201317:20) on the Osaka trip."
    )


async def test_fields_the_tool_does_not_have_are_named_in_its_result(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Osaka", date(2026, 12, 10), date(2026, 12, 14), "JPY", None),
        now=NOW,
    )
    await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "activity", "name": "Shop visit", "day": "2026-12-11", "at": "10:45"},
        None, now=NOW,
    )  # fmt: skip
    tools = build_tools(lambda _: "")
    ctx = ToolContext(user, uow, NOW, RATES)
    change = tools["change_itinerary_entry"]

    # Dropped, not refused: the change is made, and the result says what was left out.
    odd = await run_tool(change, ctx, {"item": "shop", "time": "11:00", "length": 20, "zzz": 1})
    assert odd.wrote
    assert odd.text == (
        "Changed to Shop visit (Fri 11 Dec 11:00) on the Osaka trip. "
        "(Ignored unknown fields: length, zzz.)"
    )
    # Also on a refusal, and not at all when every field is known.
    refused = await run_tool(change, ctx, {"item": "museum", "time": "9:00", "length": 20})
    assert refused.text.startswith("Error: no single itinerary entry matches 'museum'")
    assert refused.text.endswith("(Ignored unknown fields: length.)")
    plain = await run_tool(change, ctx, {"item": "shop", "time": "11:30"})
    assert "Ignored" not in plain.text
