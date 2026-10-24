"""Trip stops: saved per trip, suggested from the hotels with their Google Maps cities
(and without them), told to the chat, and kept inside their owner's data. Every place
here is made up."""

import asyncio
from datetime import date

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import bookings as booking_cases
from nexus.application import places as place_cases
from nexus.application import trips as trip_cases
from nexus.application.places import Places
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User
from nexus.domain.trips import Stop, Trip
from nexus.infra.db.migrations import alembic_config
from tests.fakes import NOW, FakePlaces, FakeRates, fake_place
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

GION = fake_place("fakePlaceGion0001", "Gion Hotel", area="Gion", city="Kyoto")
SHINJUKU = fake_place("fakePlaceShinj001", "Shinjuku Inn", area="Shinjuku", city="Tokyo")
RATES = FakeRates({})


async def kyoto_and_tokyo(uow: UowFactory) -> tuple[User, Trip]:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(), user,
        trip_cases.TripDraft("Exampleland", date(2026, 12, 10), date(2026, 12, 20), "JPY"),
        now=NOW,
    )  # fmt: skip
    for hotel in [
        {"hotel": "Gion Hotel", "check_in": "2026-12-10", "check_out": "2026-12-14",
         "place_id": GION.id},
        {"hotel": "Bay Inn", "check_in": "2026-12-14", "check_out": "2026-12-19",
         "address": "5 Example Lane, Tokyo 100-0001"},
    ]:  # fmt: skip
        await booking_cases.add_manual(
            uow(), user.id, trip.id, {"kind": "hotel", **hotel}, None, now=NOW
        )
    return user, trip


def d(day: int) -> date:
    return date(2026, 12, day)


def with_end(draft: trip_cases.TripDraft, end: date) -> trip_cases.TripDraft:
    return trip_cases.TripDraft(draft.destination, draft.start, end, draft.currency)


def shown(stops: tuple[Stop, ...]) -> list[tuple[str, int, int]]:
    return [(s.name, s.start.day, s.end.day) for s in stops]


async def test_stops_are_saved_per_trip_and_cleared_by_setting_none(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    mine = (Stop("Kyoto", d(10), d(14)), Stop("Tokyo", d(14), d(20)))
    saved = await trip_cases.set_stops(uow(), user, trip.id, mine, now=NOW)
    assert saved.stops == mine
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert view.trip.stops == mine
    # An overlap is refused and changes nothing.
    overlapping = [Stop("A", d(10), d(15)), Stop("B", d(14), d(20))]
    with pytest.raises(InvalidInput, match="overlap"):
        await trip_cases.set_stops(uow(), user, trip.id, overlapping, now=NOW)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert view.trip.stops == mine
    assert (await trip_cases.set_stops(uow(), user, trip.id, [], now=NOW)).stops == ()


async def test_the_chat_hears_the_stops_saved_or_suggested(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    lines = trip_cases.describe_view(view)
    # Not set: what the hotels suggest (here by address, as the chat has no Google Maps).
    assert (
        "Stops (from the hotels): Exampleland Thu 10 Dec to Mon 14 Dec; "
        "Tokyo Mon 14 Dec to Sun 20 Dec." in lines
    )
    await trip_cases.set_stops(uow(), user, trip.id, [Stop("Kyoto", d(10), d(20))], now=NOW)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert "Stops: Kyoto Thu 10 Dec to Sun 20 Dec." in trip_cases.describe_view(view)


async def test_suggested_stops_use_the_hotels_area_and_manage_without_google(
    uow: UowFactory,
) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    source = FakePlaces([GION])
    places = Places(source, clock=lambda: NOW)

    found = await place_cases.suggested_stops(places, user.id, view.trip, view.bookings)
    assert shown(found) == [("Kyoto", 10, 14), ("Tokyo", 14, 20)]  # the city, not the area Gion
    assert source.looked_up == [GION.id]  # only the hotel that's linked is looked up

    # Not set up, or failing: named by address (and the destination) instead.
    plain = await place_cases.suggested_stops(None, user.id, view.trip, view.bookings)
    assert shown(plain) == [("Exampleland", 10, 14), ("Tokyo", 14, 20)]
    source.failing = True
    broken = await place_cases.suggested_stops(
        Places(source, clock=lambda: NOW), user.id, view.trip, view.bookings
    )
    assert shown(broken) == shown(plain)


async def test_a_hotel_in_shinjuku_suggests_the_stop_tokyo(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(), user, trip_cases.TripDraft("Japan", d(10), d(15), "JPY"), now=NOW
    )
    await booking_cases.add_manual(
        uow(), user.id, trip.id,
        {"kind": "hotel", "hotel": "Shinjuku Inn", "check_in": "2026-12-10",
         "check_out": "2026-12-14", "place_id": SHINJUKU.id},
        None, now=NOW,
    )  # fmt: skip
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    places = Places(FakePlaces([SHINJUKU]), clock=lambda: NOW)
    found = await place_cases.suggested_stops(places, user.id, view.trip, view.bookings)
    assert shown(found) == [("Tokyo", 10, 15)]  # not "Shinjuku"


async def test_stops_follow_a_trip_edit_while_they_fit(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    mine = (Stop("Kyoto", d(10), d(20)),)
    await trip_cases.set_stops(uow(), user, trip.id, mine, now=NOW)
    draft = trip_cases.draft_of(trip)
    longer = await trip_cases.update_trip(uow(), user, trip.id, with_end(draft, d(22)), now=NOW)
    assert longer.stops == mine
    shorter = await trip_cases.update_trip(uow(), user, trip.id, with_end(draft, d(15)), now=NOW)
    assert shorter.stops == ()  # the stop ran past the new end: back to the hotels'


async def test_another_users_trip_has_no_stops_to_see_or_set(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    mine = (Stop("Kyoto", d(10), d(20)),)
    await trip_cases.set_stops(uow(), user, trip.id, mine, now=NOW)
    stranger = await person(uow, telegram_id=9191)
    with pytest.raises(NotFound):
        await trip_cases.set_stops(uow(), stranger, trip.id, [], now=NOW)
    with pytest.raises(NotFound):
        await trip_cases.trip_view(uow, RATES, stranger, trip.id, now=NOW)
    assert await trip_cases.list_trips(uow(), stranger.id) == []
    # ...and their failed attempt changed nothing.
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert view.trip.stops == mine


async def test_the_migration_adds_stops_and_keeps_the_trips(
    engine: AsyncEngine, uow: UowFactory, empty_database_url: str, admin_engine: AsyncEngine
) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    await trip_cases.set_stops(uow(), user, trip.id, [Stop("Kyoto", d(10), d(20))], now=NOW)
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0043")
    async with admin_engine.connect() as db:
        found = await db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'trips'")
        )
        columns: set[str] = set(found.scalars())
    assert "stops" not in columns and "hop_modes" in columns
    await upgrade(empty_database_url)
    async with admin_engine.connect() as db:
        rows = (await db.execute(text("SELECT destination, stops FROM trips"))).all()
    # The trip is still there; its stops went with the column, so it follows the hotels.
    assert [(r.destination, r.stops) for r in rows] == [("Exampleland", [])]
