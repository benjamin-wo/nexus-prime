"""Finding by stop or day, and research areas saved as ideas on a trip: the search's
scope, the ideas a research adds (matched to Google Maps when it clearly is the place,
skipped when already there), what the chat does with both, and whose trips are
untouched. Every place and name here is made up."""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import bookings as booking_cases
from nexus.application import places as place_cases
from nexus.application import travel_research as research
from nexus.application import trips as trip_cases
from nexus.application import undo as undo_cases
from nexus.application.ideas import IdeaFinder
from nexus.application.places import Places
from nexus.application.web_search import WebAnswer
from nexus.domain.bookings import BookingKind
from nexus.domain.departments import Run, RunStatus
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User, UserId
from nexus.domain.places import Circle, Point
from nexus.domain.trips import Stop, Trip
from tests.fakes import NOW, FakePlaces, FakeRates, fake_place, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

RATES = FakeRates({})
GION = fake_place(
    "fakePlaceGion0001", "Gion Hotel", location=Point(35.0, 135.0), area="Gion", city="Kyoto"
)
SHRINE = fake_place(
    "fakePlaceShrine01", "Yasaka Shrine", location=Point(35.004, 135.002), area="Gion"
)
GARDEN = fake_place("fakePlaceGarden001", "Gyoen Garden", area="Shinjuku", city="Tokyo")


async def kyoto_and_tokyo(uow: UowFactory, user: User | None = None) -> tuple[User, Trip]:
    user = user or await person(uow)
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


async def plan(uow: UowFactory, user: User, trip: Trip, name: str, **extra: object) -> None:
    await booking_cases.add_manual(
        uow(), user.id, trip.id, {"kind": "activity", "name": name, **extra}, None, now=NOW
    )


async def finished_research(
    uow: UowFactory,
    user_id: UserId,
    destination: str = "Tokyo",
    areas: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Shinjuku", ("Gyoen Garden", "Omoide Yokocho", "Golden Gai", "Kabukicho", "Fifth")),
        ("Asakusa", ("Senso-ji", "Nakamise Street")),
    ),
    when: date = date(2026, 12, 10),
) -> UUID:
    """A finished research run, as the departments leave it."""
    result = research.ResearchResult(
        destination=destination, start=when, end=when + timedelta(days=7), nights=7,
        travellers=2, currency="JPY", home_currency="SGD", when_summary="Cold and clear.",
        when=[], prices=[],
        areas=[
            research.AreaOut(name=n, why="Central.", things=list(t), source=1) for n, t in areas
        ],
        getting_around="An IC card.", getting_around_source=None, sources=[],
        estimate_low=None, estimate_high=None, estimate_lines=[], budget=None,
        paydays_left=0, set_aside=None, fits=None,
    )  # fmt: skip
    run = Run(
        id=uuid4(), user_id=user_id, department="travel", kind=research.KIND,
        title=f"Research: {destination}", status=RunStatus.DONE, task={}, outputs={},
        steps_done=4, steps_total=4, progress="done", spent=Decimal(0), created_at=NOW,
        updated_at=NOW, result=result.model_dump(mode="json"), finished_at=NOW,
    )  # fmt: skip
    async with uow() as tx:
        await tx.runs.insert_run(run)
        await tx.commit()
    return run.id


async def ideas_of(
    uow: UowFactory, user: User, trip: Trip
) -> dict[str, tuple[str | None, str | None]]:
    """The trip's places to visit: name -> (list, Google place id)."""
    async with uow() as tx:
        items = await tx.trips.list_bookings(user.id, trip_id=trip.id)
    return {
        b.draft.title: (b.draft.list_name, b.draft.place_id)
        for b in items
        if not b.scheduled and b.draft.name
    }


# --- where a search looks ---------------------------------------------------------------


async def test_the_scope_follows_the_stops_the_hotels_suggest(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    await plan(uow, user, trip, "Yasaka Shrine", day="2026-12-12", place_id=SHRINE.id)
    places = Places(FakePlaces([GION, SHRINE]))

    async def scope(**ask: Any) -> place_cases.SearchScope:
        return (await place_cases.search_scope(uow(), places, user.id, trip.id, **ask))[1]

    assert await scope() == place_cases.SearchScope("Exampleland")
    # "Kyoto" is the city of the first hotel's Google Maps place; "Tokyo" is read from
    # the second hotel's address.
    assert (await scope(stop="kyoto")).place == "Kyoto"
    assert (await scope(stop="Tokyo")).near is None
    with pytest.raises(InvalidInput, match="isn't one of the trip's stops"):
        await scope(stop="Osaka")
    day = await scope(day=date(2026, 12, 12))
    assert day.place == "Gion, Kyoto"
    assert day.near == Circle(Point(35.004, 135.002), 2000)
    with pytest.raises(InvalidInput, match="outside the trip"):
        await scope(day=date(2026, 12, 25))
    # Without Google Maps the circle can't be worked out; the stop still names the place.
    plain = (await place_cases.search_scope(uow(), None, user.id, trip.id, day=date(2026, 12, 12)))[
        1
    ]
    assert (plain.place, plain.near) == ("Exampleland", None)
    with pytest.raises(NotFound):
        await place_cases.search_scope(uow(), places, user.id, uuid4())


async def test_the_users_own_stops_are_the_ones_to_name(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    await trip_cases.set_stops(
        uow(), user, trip.id, [Stop("Arashiyama", date(2026, 12, 10), date(2026, 12, 20))], now=NOW
    )
    places = Places(FakePlaces([GION]))
    found = await place_cases.search_scope(uow(), places, user.id, trip.id, stop="arashiyama")
    assert found[1].place == "Arashiyama"
    with pytest.raises(InvalidInput):
        await place_cases.search_scope(uow(), places, user.id, trip.id, stop="Kyoto")


# --- research areas into a trip -----------------------------------------------------------


async def test_areas_become_ideas_under_a_list_each_and_matched_to_google_maps(
    uow: UowFactory,
) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    run = await finished_research(uow, user.id)
    source = FakePlaces([GARDEN])
    places = Places(source)
    found = await research.ideas_from_areas(
        uow, places, user, run, trip.id, ["Shinjuku", "asakusa"], now=NOW
    )
    # Four things at most from each area: Shinjuku's fifth is left out.
    assert (found.added, found.skipped) == (6, 0)
    saved = await ideas_of(uow, user, trip)
    assert saved == {
        "Gyoen Garden": ("Shinjuku", GARDEN.id),  # the top result shares its name
        "Omoide Yokocho": ("Shinjuku", None),  # nothing clearly matches: by name only
        "Golden Gai": ("Shinjuku", None),
        "Kabukicho": ("Shinjuku", None),
        "Senso-ji": ("Asakusa", None),
        "Nakamise Street": ("Asakusa", None),
    }
    assert "Gyoen Garden Shinjuku, Tokyo" in source.searches  # narrowed by the area and place
    # None has a day or a pin: Google's coordinates are never stored.
    async with uow() as tx:
        items = await tx.trips.list_bookings(user.id, trip_id=trip.id)
    ideas = [b for b in items if b.draft.list_name]
    assert all(b.draft.day is None and b.draft.lat is None for b in ideas)

    # Again: everything is already there, so nothing is added twice.
    again = await research.ideas_from_areas(uow, places, user, run, trip.id, ["Shinjuku"], now=NOW)
    assert (again.added, again.skipped) == (0, 4)
    assert len(await ideas_of(uow, user, trip)) == 6


async def test_things_already_on_the_trip_are_skipped_whatever_their_case_or_spacing(
    uow: UowFactory,
) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    await plan(uow, user, trip, "gyoen  GARDEN")  # an idea
    await plan(uow, user, trip, "Senso-Ji", day="2026-12-15")  # already planned for a day
    run = await finished_research(uow, user.id)
    found = await research.ideas_from_areas(
        uow, None, user, run, trip.id, ["Shinjuku", "Asakusa"], now=NOW
    )
    assert (found.added, found.skipped) == (4, 2)
    assert set(await ideas_of(uow, user, trip)) == {
        "gyoen GARDEN", "Omoide Yokocho", "Golden Gai", "Kabukicho", "Nakamise Street",
    }  # fmt: skip


async def test_ideas_are_saved_by_name_when_google_maps_fails_or_is_not_set_up(
    uow: UowFactory,
) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    run = await finished_research(uow, user.id)
    down = FakePlaces([GARDEN], failing=True)
    found = await research.ideas_from_areas(
        uow, Places(down), user, run, trip.id, ["Asakusa"], now=NOW
    )
    assert (found.added, found.skipped) == (2, 0)
    assert set((await ideas_of(uow, user, trip)).values()) == {("Asakusa", None)}
    # A user who hit the Google Maps cap gets their ideas too.
    capped = Places(FakePlaces([GARDEN]), limits=((1, timedelta(days=1)),))
    more = await research.ideas_from_areas(uow, capped, user, run, trip.id, ["Shinjuku"], now=NOW)
    assert more.added == 4
    off = await research.ideas_from_areas(uow, None, user, run, trip.id, ["Shinjuku"], now=NOW)
    assert (off.added, off.skipped) == (0, 4)


async def test_a_stop_is_suggested_when_the_research_place_is_not_one(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    places = Places(FakePlaces([GION]))
    osaka = await finished_research(uow, user.id, "Osaka", (("Namba", ("Dotonbori",)),))
    found = await research.ideas_from_areas(uow, places, user, osaka, trip.id, ["Namba"], now=NOW)
    assert (found.added, found.stop_suggestion) == (1, "Osaka")
    # Tokyo is a stop already (named by the address of the second hotel), as is "Kyoto, Japan".
    tokyo = await finished_research(uow, user.id, "Tokyo, Japan")
    again = await research.ideas_from_areas(uow, places, user, tokyo, trip.id, ["Asakusa"], now=NOW)
    assert again.stop_suggestion is None
    kyoto = await finished_research(uow, user.id, "Kyoto, Japan", (("Gion", ("Hanamikoji",)),))
    assert (
        await research.ideas_from_areas(uow, places, user, kyoto, trip.id, ["Gion"], now=NOW)
    ).stop_suggestion is None
    # The research of the trip's own destination is never offered back as a stop.
    own = await finished_research(uow, user.id, "Exampleland")
    assert (
        await research.ideas_from_areas(uow, places, user, own, trip.id, ["Asakusa"], now=NOW)
    ).stop_suggestion is None


async def test_ideas_from_areas_refuses_what_is_not_the_users_or_not_valid(
    uow: UowFactory,
) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    other = await person(uow, 5151)
    run = await finished_research(uow, user.id)
    theirs = await finished_research(uow, other.id)
    _, their_trip = await kyoto_and_tokyo(uow, other)

    async def add(who: User, run_id: UUID, trip_id: UUID, areas: list[str]) -> Any:
        return await research.ideas_from_areas(uow, None, who, run_id, trip_id, areas, now=NOW)

    with pytest.raises(NotFound):  # someone else's trip
        await add(user, run, their_trip.id, ["Shinjuku"])
    with pytest.raises(NotFound):  # someone else's research
        await add(user, theirs, trip.id, ["Shinjuku"])
    with pytest.raises(NotFound):
        await add(user, uuid4(), trip.id, ["Shinjuku"])
    with pytest.raises(
        InvalidInput, match=r"no area called 'Ginza' \(its areas: Shinjuku, Asakusa\)"
    ):
        await add(user, run, trip.id, ["Ginza"])
    with pytest.raises(InvalidInput, match="at least one area"):
        await add(user, run, trip.id, [" "])
    over = await trip_cases.create_trip(
        uow(), user,
        trip_cases.TripDraft("Old trip", date(2026, 8, 1), date(2026, 8, 5), "JPY"),
        now=NOW,
    )  # fmt: skip
    with pytest.raises(InvalidInput, match="trip is over"):
        await add(user, run, over.id, ["Shinjuku"])
    # Nothing was added anywhere by the refusals.
    assert await ideas_of(uow, user, trip) == {} and await ideas_of(uow, other, their_trip) == {}
    # An ongoing trip is fine.
    ongoing = await trip_cases.create_trip(
        uow(), user,
        trip_cases.TripDraft("Here now", date(2026, 9, 27), date(2026, 10, 2), "JPY"),
        now=NOW,
    )  # fmt: skip
    assert (await add(user, run, ongoing.id, ["Asakusa"])).added == 2


async def test_a_full_trip_takes_no_more_ideas(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    for n in range(booking_cases.MAX_BOOKINGS_A_TRIP - 2):
        await plan(uow, user, trip, f"Filler {n}")
    run = await finished_research(uow, user.id)
    with pytest.raises(InvalidInput, match="at most 100 itinerary entries"):
        await research.ideas_from_areas(uow, None, user, run, trip.id, ["Shinjuku"], now=NOW)
    assert len([k for k in await ideas_of(uow, user, trip) if not k.startswith("Filler")]) == 0


# --- the chat ------------------------------------------------------------------------------


@dataclass
class Web:
    asked: list[str] = field(default_factory=list)

    async def ask(self, question: str) -> WebAnswer:
        self.asked.append(question)
        page = "Hanok Noodle Bar pulls noodles by hand."
        return WebAnswer("", [("https://food.example.com/x", "Noodles")], Decimal(0), [page])


async def test_finding_in_a_stop_or_near_a_day_from_chat(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    await plan(uow, user, trip, "Yasaka Shrine", day="2026-12-12", place_id=SHRINE.id)
    source = FakePlaces([GION, SHRINE])
    web = Web()
    ideas = IdeaFinder(
        web,
        scripted(*[say("IDEA | Hanok Noodle Bar | Gion | Food | Hand-pulled. | 1")] * 3),
        places=Places(source), clock=lambda: NOW,
    )  # fmt: skip
    ctx = ToolContext(user, uow, NOW, RATES, places=Places(source), ideas=ideas)
    tools = build_tools(lambda _: "")

    async def use(name: str, args: dict[str, object]) -> str:
        return (await run_tool(tools[name], ctx, args)).text

    plain = await use("find_places", {"query": "ramen"})
    assert source.searches[-1] == "ramen, Exampleland" and source.near[-1] is None
    assert not plain.startswith("Searched in")

    in_tokyo = await use("find_places", {"query": "ramen", "stop": "Tokyo"})
    assert source.searches[-1] == "ramen, Tokyo" and source.near[-1] is None
    assert in_tokyo.startswith("Searched in Tokyo.\n")

    near = await use("find_places", {"query": "ramen", "day": "3"})  # day 3 is 12 Dec
    assert source.searches[-1] == "ramen, Gion, Kyoto"
    assert source.near[-1] == Circle(Point(35.004, 135.002), 2000)
    assert near.startswith("Searched in Gion, Kyoto, leaning towards that day's planned places.")
    dated = await use("find_places", {"query": "ramen", "day": "2026-12-12"})
    assert dated == near
    assert source.searches.count("ramen, Gion, Kyoto") == 1  # the second came from the cache

    # A city that isn't one of the trip's stops is searched as itself, not refused.
    elsewhere = await use("find_places", {"query": "ramen", "stop": "Osaka"})
    assert not elsewhere.startswith("Error") and source.searches[-1] == "ramen, Osaka"
    assert (await use("find_places", {"query": "x", "day": "40"})).startswith("Error:")

    text = await use("find_ideas", {"query": "noodles", "stop": "Kyoto"})
    assert len(web.asked) == 1 and web.asked[0].startswith("Best noodles in Kyoto: ")
    assert text.startswith("Ideas for noodles in Kyoto, from travel guides")

    # A stop the query ends with is taken as the stop; one that isn't a stop is searched as asked.
    moved = await use("find_ideas", {"query": "noodles in Kyoto"})
    assert " in Kyoto, from travel guides" in moved
    unmoved = await use("find_ideas", {"query": "noodles in Osaka"})
    assert not unmoved.startswith("Error") and "Exampleland, from travel guides" in unmoved


async def test_research_to_trip_from_chat_confirms_then_adds(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    ctx = ToolContext(user, uow, NOW, RATES, places=Places(FakePlaces([GARDEN])))
    tools = build_tools(lambda _: "")
    spec = tools["research_to_trip"]
    assert spec.confirm is not None

    nothing = await run_tool(spec, ctx, {"trip": "Exampleland"})
    assert nothing.text == "Error: no finished trip research from the last month"
    await finished_research(uow, user.id)
    asked = await spec.confirm(ctx, spec.parse({}))
    assert asked == (
        "Add the things to do in Shinjuku, Asakusa from the research to the Exampleland trip "
        "as ideas (up to 4 per area, each under a list named after its area)?"
    )
    one = await run_tool(spec, ctx, {"areas": ["asakusa"]})
    assert one.wrote and one.text.startswith("Added 2 ideas to the Exampleland trip.")
    assert "Tokyo" not in one.text  # the research place is a stop already
    both = await run_tool(spec, ctx, {})
    assert both.text.startswith("Added 4 ideas to the Exampleland trip (2 were already there).")
    assert set(v[0] for v in (await ideas_of(uow, user, trip)).values()) == {"Shinjuku", "Asakusa"}

    # Another user's research is not found; neither is an unknown area or a research place.
    other = await person(uow, 5151)
    await finished_research(uow, other.id, "Rome", (("Trastevere", ("Pantheon",)),))
    assert (await run_tool(spec, ctx, {"research": "Rome"})).text.startswith("Error: no finished")
    assert (await run_tool(spec, ctx, {"areas": ["Ginza"]})).text.startswith("Error: the research")
    await finished_research(uow, user.id, "Osaka", (("Namba", ("Dotonbori",)),))
    stopless = await run_tool(spec, ctx, {"research": "Osaka"})
    assert "Osaka, which isn't one of the trip's stops" in stopless.text


async def test_undo_takes_the_ideas_a_chat_research_added_off_the_trip(uow: UowFactory) -> None:
    user, trip = await kyoto_and_tokyo(uow)
    await plan(uow, user, trip, "Tea house")
    ctx = replace(
        ToolContext(user, uow, NOW, RATES, places=Places(FakePlaces([GARDEN]))), batch=uuid4()
    )
    await finished_research(uow, user.id)
    added = await run_tool(build_tools(lambda _: "")["research_to_trip"], ctx, {})
    assert added.wrote and added.text.startswith("Added 6 ideas")
    assert len(await ideas_of(uow, user, trip)) >= 1

    undone = await undo_cases.undo_latest(uow(), user.id)
    assert isinstance(undone, undo_cases.TripUndo) and len(undone.items) == 6
    async with uow() as tx:
        left = await tx.trips.list_bookings(user.id, trip_id=trip.id)
    assert sorted(b.draft.title for b in left if b.draft.kind is BookingKind.ACTIVITY) == [
        "Tea house"
    ]
