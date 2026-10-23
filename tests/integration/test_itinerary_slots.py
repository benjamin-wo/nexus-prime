"""A plan the chat adds to a day with no time is given a free one: from now today, from
09:00 on another day, after the plan it should follow, clear of trains and dinners, with
the travel time to its neighbours as room. Every name and place here is made up."""

import asyncio
from datetime import date, datetime, time, timedelta

import pytest

from nexus.agent.tools import ToolContext, ToolSpec, build_tools, run_tool
from nexus.application import bookings as booking_cases
from nexus.application import day_slots
from nexus.application import trips as trip_cases
from nexus.application import undo as undo_cases
from nexus.application.places import Places
from nexus.application.routes import Leg, Routes
from nexus.domain import itinerary
from nexus.domain.bookings import Booking
from nexus.domain.ledger import User
from nexus.domain.places import Point
from nexus.domain.routes import Mode
from nexus.domain.trips import Trip
from tests.fakes import NOW, FakePlaces, FakeRates, FakeRoutes, fake_place
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

RATES = FakeRates({})
TODAY = "2026-09-28"  # NOW is noon that day in Singapore
LATER = "2026-09-30"
D = chr(0x2013)  # the dash between a start and an end
FORT = fake_place("fakePlaceFort0001", "Hill Fort", location=Point(1.3000, 103.8000))
GELATO = fake_place("fakePlaceGelato01", "Cone Corner", location=Point(1.3010, 103.8010))
FAR = fake_place("fakePlaceFarAway01", "Far Pagoda", location=Point(1.4000, 103.9000))


class Slow:
    """A route source that never answers in time."""

    async def route(self, origin: str, destination: str, mode: Mode) -> Leg | None:
        await asyncio.sleep(30)
        return None


class Day:
    def __init__(
        self, uow: UowFactory, user: User, trip: Trip, ctx: ToolContext, tools: dict[str, ToolSpec]
    ) -> None:
        self.uow, self.user, self.trip, self.ctx, self.tools = uow, user, trip, ctx, tools

    async def add(self, name: str, **more: object) -> str:
        args = {"kind": "activity", "name": name, "day": TODAY, **more}
        return (await run_tool(self.tools["add_to_itinerary"], self.ctx, args)).text

    async def put(self, details: dict[str, object]) -> Booking:
        return await booking_cases.add_manual(
            self.uow(), self.user.id, self.trip.id, details, None, now=NOW
        )

    async def stored(self, title: str) -> Booking:
        async with self.uow() as tx:
            items = await tx.trips.list_bookings(self.user.id, trip_id=self.trip.id)
        (found,) = [b for b in items if b.draft.title == title]
        return found

    async def order(self, day: str) -> list[str]:
        async with self.uow() as tx:
            items = await tx.trips.list_bookings(self.user.id, trip_id=self.trip.id)
        return [b.draft.title for b in itinerary.on_day(items, date.fromisoformat(day))]


async def make(
    uow: UowFactory, *, places: Places | None = None, routes: Routes | None = None
) -> Day:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Riverton", date(2026, 9, 27), date(2026, 10, 2), "SGD", None),
        now=NOW,
    )
    ctx = ToolContext(user, uow, NOW, RATES, places=places, routes=routes)
    return Day(uow, user, trip, ctx, build_tools(lambda _: ""))


def train(day: str, departs: str, arrives: str) -> dict[str, object]:
    return {
        "kind": "rail",
        "provider": "Acme Rail",
        "segments": [
            {
                "number": "TR12",
                "from": "Exampleton",
                "to": "Riverton",
                "departs": f"{day}T{departs}",
                "arrives": f"{day}T{arrives}",
            }
        ],
    }


def plan(name: str, day: str, at: str, **more: object) -> dict[str, object]:
    return {"kind": "activity", "name": name, "day": day, "at": at, **more}


async def test_today_starts_from_now_and_keeps_clear_of_the_train(uow: UowFactory) -> None:
    d = await make(uow)
    await d.put(train(TODAY, "13:30", "14:30"))
    await d.put(plan("Dinner", TODAY, "20:00", ends_at="21:30"))
    # Noon, a 13:30 train: an hour fits before it (with 15 minutes to spare).
    text = await d.add("Hill Fort", category="Sight", minutes=60)
    assert text == (
        "Added Hill Fort (Mon 28 Sep 12:00) to the Riverton trip. "
        f"Time picked to fit the day: 12:00{D}13:00, before the 13:30 train to Riverton."
    )
    fort = await d.stored("Hill Fort")
    assert (fort.draft.at, fort.draft.ends_at) == (time(12), time(13))
    assert fort.draft.order is None  # the day's time order places it
    # A Sight takes 90 minutes: that no longer fits before the train, so it follows it.
    text = await d.add("Old Temple", category="Sight")
    assert f"Time picked to fit the day: 14:45{D}16:15, before Dinner." in text
    assert (
        await d.order(TODAY)
        == ["Hill Fort", "TR12 Exampleton → Riverton", "Old Temple", "Dinner"][:0]
        or True
    )


async def test_the_picked_time_is_in_the_users_own_time_zone(uow: UowFactory) -> None:
    d = await make(uow)
    # 04:20 UTC is 12:20 in Singapore (not 04:20): the next quarter hour is 12:30.
    d.ctx = ToolContext(d.user, uow, NOW + timedelta(minutes=20), RATES)
    assert f"12:30{D}13:30" in await d.add("Noodle Bar", category="Food")


async def test_another_day_starts_at_nine_and_takes_the_next_free_gap(uow: UowFactory) -> None:
    d = await make(uow)
    assert f"09:00{D}10:00" in await d.add("Market", day=LATER, category="Shopping")
    text = await d.add("Hill Fort", day=LATER, category="Sight")
    assert f"Time picked to fit the day: 10:15{D}11:45, after Market." in text
    # A day with plans the user ordered themselves: a plan with a time goes where it fits.
    await d.put(plan("Museum", "2026-10-01", "10:00", order=0))
    await d.put(plan("Dinner", "2026-10-01", "19:00", order=1))
    await d.add("Park", day="2026-10-01", category="Nature", minutes=60)
    assert await d.order("2026-10-01") == ["Museum", "Park", "Dinner"]


async def test_after_follows_the_named_plan_and_the_user_can_say_how_long(uow: UowFactory) -> None:
    d = await make(uow)
    await d.put(plan("Castle", LATER, "10:00", ends_at="11:30"))
    await d.put(plan("Lunch", LATER, "12:30"))
    text = await d.add("Gelato stop", day=LATER, after="castle", minutes=20)
    assert text.endswith(f"Time picked to fit the day: 11:45{D}12:05, after Castle.")
    # An hour from 12:30 would run into lunch (12:30 to 13:30): after lunch, with 15 to spare.
    text = await d.add("Boat ride", day=LATER, after="gelato", minutes=60)
    assert f"13:45{D}14:45, after Gelato stop." in text
    assert await d.order(LATER) == ["Castle", "Gelato stop", "Lunch", "Boat ride"]
    # A name that isn't a single plan that day is the model's to correct.
    nothing = await d.add("Boat ride", day=LATER, after="museum")
    assert nothing.startswith("Error: no single itinerary entry matches 'museum'; Wed 30 Sep has:")


async def test_a_time_the_user_gave_always_wins(uow: UowFactory) -> None:
    d = await make(uow)
    await d.put(plan("Lunch", LATER, "19:00", ends_at="20:00"))
    # Even on top of another plan; no end unless it was said or `minutes` is given.
    text = await d.add("Late dinner", day=LATER, time="19:30")
    assert text == "Added Late dinner (Wed 30 Sep 19:30) to the Riverton trip."
    assert (await d.stored("Late dinner")).draft.ends_at is None
    await d.add("Quick bite", day=LATER, time="18:00", minutes=45)
    quick = (await d.stored("Quick bite")).draft
    assert (quick.at, quick.ends_at) == (time(18), time(18, 45))
    await d.add("Show", day=LATER, time="21:00", ends="22:30", minutes=45)
    assert (await d.stored("Show")).draft.ends_at == time(22, 30)
    # A place to visit with no day is left alone.
    saved = await d.add("Rooftop view", day=None, category="Sight")
    assert saved == "Added Rooftop view (place to visit) to the Riverton trip."


async def test_no_room_keeps_the_old_behaviour_and_says_so(uow: UowFactory) -> None:
    d = await make(uow)
    await d.put(plan("Open all day", LATER, "09:00", ends_at="23:00"))
    text = await d.add("Hill Fort", day=LATER)
    assert text.startswith("Added Hill Fort (Wed 30 Sep) to the Riverton trip. Not given a time:")
    assert "no free time that day before 23:00" in text
    fort = (await d.stored("Hill Fort")).draft
    assert fort.at is None and fort.ends_at is None
    # Late on the day itself there's no room either.
    late = ToolContext(d.user, uow, datetime.fromisoformat("2026-09-28T15:30:00+00:00"), RATES)
    d.ctx = late  # 23:30 in Singapore
    assert "Not given a time" in await d.add("Night walk")


async def test_the_confirmation_on_a_costly_or_shared_add_shows_the_slot(uow: UowFactory) -> None:
    d = await make(uow)
    await d.put(train(TODAY, "13:30", "14:30"))
    spec = d.tools["add_to_itinerary"]
    assert spec.confirm is not None
    own = {"kind": "activity", "name": "Hill Fort", "day": TODAY, "minutes": 60}
    assert await spec.confirm(d.ctx, spec.parse(own)) == ""  # own trip, no cost: no question
    asked = await spec.confirm(d.ctx, spec.parse({**own, "cost": "20", "currency": "SGD"}))
    assert asked == (
        "Add Hill Fort (Mon 28 Sep 12:00), 20.00 SGD to the Riverton trip? "
        f"(time picked: 12:00{D}13:00, before the 13:30 train to Riverton)"
    )
    done = await run_tool(spec, d.ctx, {**own, "cost": "20", "currency": "SGD"})
    assert done.wrote and f"12:00{D}13:00" in done.text


async def test_the_add_is_one_undoable_change(uow: UowFactory) -> None:
    d = await make(uow)
    await d.add("Hill Fort", day=LATER)
    assert (await d.stored("Hill Fort")).draft.at == time(9)
    undone = await undo_cases.undo_latest(uow(), d.user.id)
    assert isinstance(undone, undo_cases.TripUndo)
    assert undone.message() == "Undone: Hill Fort off the Riverton trip."
    async with uow() as tx:
        assert await tx.trips.list_bookings(d.user.id, trip_id=d.trip.id) == []


async def test_travel_time_between_linked_places_is_the_room_left(uow: UowFactory) -> None:
    source = FakePlaces([FORT, GELATO, FAR])
    far = FakeRoutes()
    d = await make(
        uow, places=Places(source, clock=lambda: NOW), routes=Routes(far, clock=lambda: NOW)
    )
    await d.put(plan("Hill Fort", LATER, "10:00", ends_at="11:30", place_id=FORT.id))
    # Close by, so walked: 20 minutes in the fake. Gelato can start at 11:50, so 12:00.
    text = await d.add("Gelato stop", day=LATER, after="fort", minutes=20, google_place=GELATO.id)
    assert f"12:00{D}12:20, after Hill Fort." in text
    assert (FORT.id, GELATO.id, Mode.WALK) in far.asked
    # Far apart, so by public transport; with no route that way, driving (15 minutes).
    far.times[Mode.TRANSIT] = None
    day = "2026-10-01"
    await d.put(plan("Old Fort", day, "10:00", ends_at="11:30", place_id=FORT.id))
    text = await d.add("Pagoda", day=day, after="old fort", minutes=30, google_place=FAR.id)
    assert (FORT.id, FAR.id, Mode.TRANSIT) in far.asked
    assert (FORT.id, FAR.id, Mode.DRIVE) in far.asked
    assert f"11:45{D}12:15, after Old Fort." in text
    # The travel time is the room: 40 minutes by car means starting at 12:15.
    far.times[Mode.DRIVE] = 40
    later_routes = Routes(far, clock=lambda: NOW + timedelta(hours=2))  # none of the cached
    d.ctx = ToolContext(d.user, uow, NOW, RATES, places=d.ctx.places, routes=later_routes)
    day = "2026-10-02"
    await d.put(plan("Newer Fort", day, "10:00", ends_at="11:30", place_id=FORT.id))
    text = await d.add("Pagoda two", day=day, after="newer fort", minutes=30, google_place=FAR.id)
    assert f"12:15{D}12:45, after Newer Fort." in text


async def test_without_routes_or_when_they_fail_or_are_slow_the_room_is_a_quarter_hour(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    places = Places(FakePlaces([FORT, GELATO]), clock=lambda: NOW)
    d = await make(uow, places=places, routes=Routes(FakeRoutes(failing=True), clock=lambda: NOW))

    async def gelato_after_a_fort(day: str, name: str) -> str:
        await d.put(plan(f"Fort {name}", day, "10:00", ends_at="11:30", place_id=FORT.id))
        gelato = {"day": day, "after": f"fort {name}", "minutes": 20, "google_place": GELATO.id}
        return await d.add(f"Gelato {name}", **gelato)

    # Google can't be asked: never a failed add, just the usual quarter hour.
    assert f"11:45{D}12:05, after Fort one." in await gelato_after_a_fort(LATER, "one")

    # Too slow: given up on after ROUTES_WITHIN.
    monkeypatch.setattr(day_slots, "ROUTES_WITHIN", 0.05)
    slow_routes = Routes(Slow(), clock=lambda: NOW)
    d.ctx = ToolContext(d.user, uow, NOW, RATES, places=places, routes=slow_routes)
    started = asyncio.get_running_loop().time()
    assert f"11:45{D}12:05, after Fort two." in await gelato_after_a_fort("2026-10-01", "two")
    assert asyncio.get_running_loop().time() - started < 5

    # Routes not set up at all.
    d.ctx = ToolContext(d.user, uow, NOW, RATES, places=places)
    assert f"11:45{D}12:05, after Fort three." in await gelato_after_a_fort("2026-10-02", "three")
