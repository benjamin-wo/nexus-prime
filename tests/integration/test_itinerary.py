"""Itinerary entries added by hand (flights, hotels, trains and plans) and notes on a
trip. Every name, number and place here is made up."""

from datetime import date, time
from uuid import uuid4

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import bookings as booking_cases
from nexus.application import trips as trip_cases
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

    with pytest.raises(InvalidInput, match="name and a day"):
        await booking_cases.add_manual(
            uow(), user.id, trip.id, {"kind": "activity", "name": "x"}, None, now=NOW
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
    assert added.startswith("Added to the Osaka itinerary: hotel booking (Hotel Kawa")
    assert added.endswith("10 Dec to 14 Dec).")
    await use("add_to_itinerary", {"kind": "activity", "name": "Castle tour", "day": "2026-12-11"})
    # Only what changed changes.
    change = tools["change_itinerary_entry"]
    assert change.confirm is not None
    asked = await change.confirm(ctx, change.parse({"item": "kawa", "until": "2026-12-13"}))
    assert asked.startswith("Change hotel booking (Hotel Kawa") and "10 Dec to 13 Dec)?" in asked
    changed = await use("change_itinerary_entry", {"item": "kawa", "until": "2026-12-13"})
    assert changed.startswith("Changed on the Osaka itinerary: hotel booking (Hotel Kawa")
    assert changed.endswith("10 Dec to 13 Dec).")
    moved = await use("change_itinerary_entry", {"item": "castle", "time": "10:30"})
    assert "Castle tour, Fri 11 Dec 10:30" in moved
    async with uow() as tx:
        stored = await tx.trips.list_bookings(user.id)
    (hotel,) = [b for b in stored if b.draft.kind is BookingKind.HOTEL]
    assert (hotel.draft.check_in, hotel.draft.check_out) == (date(2026, 12, 10), date(2026, 12, 13))
    missing = await use("change_itinerary_entry", {"item": "museum", "time": "09:00"})
    assert "no single itinerary entry matches 'museum'" in missing
