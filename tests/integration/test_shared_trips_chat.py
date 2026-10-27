"""Chat on shared trips: a member (a full account added to someone's trip) finds the
trip by name, sees and edits its plan through the same rules as the web, and is turned
away from anything with money in it. Every name and figure here is made up."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import ToolContext, ToolSpec, build_tools, run_tool
from nexus.application import bookings as booking_cases
from nexus.application import trip_access as access_cases
from nexus.application import trips as trip_cases
from nexus.application.places import Places
from nexus.domain.bookings import Booking, BookingKind
from nexus.domain.errors import Forbidden
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.domain.trips import Trip
from nexus.infra.db.tables import jobs, transactions
from tests.fakes import NOW, FakePlaces, FakeRates, FakeTripReader, fake_place, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

RATES = FakeRates({})
REFUSED = "Error: Only Alex can change money or the trip's details on a shared trip."
NOODLES = fake_place("fakePlaceNoodle01", "Hanok Noodle Bar")


@dataclass
class Japan:
    """Alex's Tokyo trip with a budget, set-aside and costs on it, shared with Sam.
    Rin has no part in it."""

    uow: UowFactory
    alex: User
    sam: User
    rin: User
    trip: Trip
    tools: dict[str, ToolSpec]
    places: FakePlaces

    def ctx(self, user: User) -> ToolContext:
        return ToolContext(user, self.uow, NOW, RATES, places=Places(self.places))

    async def use(self, user: User, name: str, args: Mapping[str, object] | None = None) -> str:
        return (await run_tool(self.tools[name], self.ctx(user), dict(args or {}))).text

    async def asked(self, user: User, name: str, args: Mapping[str, object]) -> str:
        spec = self.tools[name]
        assert spec.confirm is not None
        return await spec.confirm(self.ctx(user), spec.parse(dict(args)))

    async def bookings(self) -> list[Booking]:
        async with self.uow() as tx:
            return await tx.trips.list_bookings(self.alex.id, trip_id=self.trip.id)

    async def stored(self) -> Trip:
        return await trip_cases.get_trip(self.uow(), self.alex.id, self.trip.id)

    async def activity(self) -> list[str]:
        found = await access_cases.activity(self.uow(), self.alex, self.trip.id)
        return [f"{a.actor}: {a.summary}" for a in found]


@pytest.fixture
async def japan(uow: UowFactory) -> Japan:
    alex = await person(uow, 4242)
    sam = await person(uow, 4343)
    rin = await person(uow, 4444)
    trip = await trip_cases.create_trip(
        uow(),
        alex,
        trip_cases.TripDraft(
            "Tokyo, Japan",
            date(2026, 12, 10),
            date(2026, 12, 18),
            "JPY",
            Money.of("3000", "SGD"),
            ["Ann"],
            Money.of("100", "SGD"),
            notes="Bring cash",
        ),
        now=NOW,
    )
    async with uow() as tx:
        await tx.ledger.set_display_name(alex.id, "Alex")
        await tx.ledger.set_display_name(sam.id, "Sam T.")
        await tx.trips.add_member(alex.id, trip.id, sam.id, None, NOW)
        await tx.commit()
    await booking_cases.add_manual(
        uow(), alex.id, trip.id,
        {"kind": "hotel", "hotel": "Hotel Sakura", "check_in": "2026-12-10",
         "check_out": "2026-12-14"},
        Money.of("48000", "JPY"), now=NOW,
    )  # fmt: skip
    await booking_cases.add_manual(
        uow(), alex.id, trip.id,
        {"kind": "activity", "name": "Tea ceremony", "day": "2026-12-11", "at": "14:00"},
        Money.of("6000", "JPY"), now=NOW,
    )  # fmt: skip
    return Japan(uow, alex, sam, rin, trip, build_tools(lambda _: ""), FakePlaces([NOODLES]))


# --- finding the trip -----------------------------------------------------------------------


async def test_a_member_finds_the_shared_trip_with_no_money_in_it(japan: Japan) -> None:
    listed = await japan.use(japan.sam, "list_trips")
    assert "Tokyo, Japan, 10 Dec to 18 Dec 2026" in listed
    assert "[Alex's trip, shared with the user" in listed
    status = await japan.use(japan.sam, "trip_status", {"trip": "japan"})
    assert status.startswith("The Tokyo, Japan plan, shared with the user by Alex.")
    assert "Hotel Sakura" in status and "Tea ceremony" in status and "Notes: Bring cash" in status
    for money in (
        "3000", "3,000", "100 SGD", "48000", "48,000", "6000", "6,000", "Spent", "budget",
        "Booked:", "owed",
    ):  # fmt: skip
        assert money not in listed + status, money
    # The owner still gets all of it.
    own = await japan.use(japan.alex, "trip_status", {"trip": "japan"})
    assert "budget 3,000" in own and "Spent so far" in own and "Booked: " in own


async def test_an_outsider_cannot_find_or_touch_the_trip(japan: Japan) -> None:
    before = await japan.bookings()
    assert "No trips yet" in await japan.use(japan.rin, "list_trips")
    for tool, args in (
        ("trip_status", {"trip": "Tokyo"}),
        (
            "add_to_itinerary",
            {"trip": "Tokyo", "kind": "activity", "name": "X", "day": "2026-12-12"},
        ),
        ("change_itinerary_entry", {"trip": "Tokyo", "item": "tea", "time": "10:00"}),
        ("remove_from_itinerary", {"trip": "Tokyo", "item": "tea"}),
        ("label_trip_day", {"trip": "Tokyo", "day": "2026-12-12", "label": "Hmm"}),
        ("update_trip", {"trip": "Tokyo", "notes": "mine now"}),
    ):
        assert await japan.use(japan.rin, tool, args) == "Error: no trips yet", tool
    # With a trip of their own, the error lists theirs and never the shared one.
    await trip_cases.create_trip(
        japan.uow(),
        japan.rin,
        trip_cases.TripDraft("Paris", date(2027, 3, 1), date(2027, 3, 5), "EUR", None),
        now=NOW,
    )
    said = await japan.use(japan.rin, "trip_status", {"trip": "Tokyo"})
    assert said == "Error: no trip to Tokyo; trips: Paris"
    assert await japan.bookings() == before
    assert (await japan.stored()).notes == "Bring cash"
    assert await japan.activity() == []


async def test_several_matching_trips_come_back_as_a_question(japan: Japan) -> None:
    mine = await trip_cases.create_trip(
        japan.uow(),
        japan.sam,
        trip_cases.TripDraft("Kyoto, Japan", date(2027, 2, 1), date(2027, 2, 4), "JPY", None),
        now=NOW,
    )
    asked = await japan.use(japan.sam, "trip_status", {"trip": "japan"})
    assert asked.startswith("Error: 2 trips match 'japan': ")
    assert "Tokyo, Japan (10 Dec 2026 to 18 Dec 2026, Alex's)" in asked
    assert "Kyoto, Japan (01 Feb 2027 to 04 Feb 2027, yours)" in asked
    assert asked.endswith("Ask which one.")
    # Naming one picks it, and the trip each is on stays where it was.
    assert (await japan.use(japan.sam, "trip_status", {"trip": "kyoto"})).startswith(
        "Trip figures, worked out in code"
    )
    assert (await japan.use(japan.sam, "trip_status", {"trip": "tokyo"})).startswith(
        "The Tokyo, Japan plan"
    )
    # Nobody else's trip changes how the owner's own trips are found.
    assert (await japan.use(japan.alex, "trip_status", {"trip": "japan"})).startswith(
        "Trip figures"
    )
    assert mine.id != japan.trip.id


# --- editing the plan -----------------------------------------------------------------------


async def test_a_member_adds_a_plan_to_the_owners_trip_without_a_price(
    engine: AsyncEngine, japan: Japan
) -> None:
    args = {
        "trip": "Japan",
        "kind": "activity",
        "name": "Dinner at Sushi Ten",
        "day": "2026-12-12",
        "time": "19:00",
        "cost": "9000",
        "currency": "JPY",
    }
    asked = await japan.asked(japan.sam, "add_to_itinerary", args)
    assert asked.startswith(
        "Add Dinner at Sushi Ten (Sat 12 Dec 19:00) to the Tokyo, Japan trip (Alex's trip)?"
    )
    assert "9000" not in asked and "9,000" not in asked
    assert asked.endswith("I left the price out: only Alex can add costs on a shared trip.")

    done = await japan.use(japan.sam, "add_to_itinerary", args)
    assert done.startswith(
        "Added Dinner at Sushi Ten (Sat 12 Dec 19:00) to the Tokyo, Japan trip (Alex's trip)."
    )
    assert "I left the price out" in done
    (dinner,) = [b for b in await japan.bookings() if b.draft.title == "Dinner at Sushi Ten"]
    assert (dinner.user_id, dinner.trip_id) == (japan.alex.id, japan.trip.id)
    assert (dinner.cost, dinner.transaction_id) == (None, None)
    # The activity feed says who did it; the owner's Telegram summary is queued.
    assert await japan.activity() == ["Sam T.: added Dinner at Sushi Ten"]
    async with engine.connect() as db:
        queued = await db.scalar(
            select(func.count()).select_from(jobs).where(jobs.c.kind == access_cases.DIGEST_JOB)
        )
    assert queued == 1
    # Alex's trip is as it was: nothing of the owner's money moved.
    trip = await japan.stored()
    assert (trip.budget, trip.set_aside) == (Money.of("3000", "SGD"), Money.of("100", "SGD"))
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(transactions)) == 0


async def test_a_member_is_asked_first_even_with_no_cost_but_the_owner_is_not(
    japan: Japan,
) -> None:
    add = {"kind": "activity", "name": "Castle", "day": "2026-12-11"}
    change = {"item": "tea", "time": "15:30"}
    remove = {"item": "tea"}
    # On someone else's trip every change asks, and never shows what the owner paid.
    for tool, args in (
        ("add_to_itinerary", add),
        ("change_itinerary_entry", change),
        ("remove_from_itinerary", remove),
    ):
        asked = await japan.asked(japan.sam, tool, {"trip": "Japan", **args})
        assert "trip (Alex's trip)?" in asked, (tool, asked)
        assert "6000" not in asked and "6,000" not in asked
    # On the owner's own trip an add with no cost goes through unasked ...
    assert await japan.asked(japan.alex, "add_to_itinerary", add) == ""
    # ... but an entry that has a cost (the tea ceremony cost 6000) still asks.
    assert (await japan.asked(japan.alex, "remove_from_itinerary", remove)).startswith(
        "Remove Tea ceremony (Fri 11 Dec 14:00) from the Tokyo, Japan trip?"
    )
    assert (await japan.asked(japan.alex, "change_itinerary_entry", change)).startswith(
        "Change Tea ceremony (Fri 11 Dec 14:00) to Tea ceremony (Fri 11 Dec 15:30)"
    )


async def test_a_member_changes_moves_and_removes_plans_and_keeps_the_cost(japan: Japan) -> None:
    changed = await japan.use(
        japan.sam, "change_itinerary_entry", {"item": "tea", "time": "15:30", "cost": "1"}
    )
    assert changed.startswith(
        "Changed to Tea ceremony (Fri 11 Dec 15:30) on the Tokyo, Japan trip (Alex's trip)."
    )
    assert "I left the price out" in changed
    (tea,) = [b for b in await japan.bookings() if b.draft.title == "Tea ceremony"]
    assert tea.cost == Money.of("6000", "JPY")  # the owner's cost stays
    assert tea.draft.at is not None and tea.draft.at.hour == 15

    await japan.use(
        japan.sam, "add_to_itinerary", {"kind": "activity", "name": "Castle", "day": "2026-12-11"}
    )
    moved = await japan.use(japan.sam, "change_itinerary_entry", {"item": "castle", "after": "tea"})
    assert "Castle" in moved
    await japan.use(japan.sam, "label_trip_day", {"day": "2026-12-12", "label": "Nikko"})
    labelled = await japan.use(japan.sam, "label_trip_day", {"day": "2026-12-12", "label": ""})
    assert "unlabelled" in labelled
    removed = await japan.use(japan.sam, "remove_from_itinerary", {"item": "castle"})
    assert removed == "Removed Castle (Fri 11 Dec 09:00) from the Tokyo, Japan trip (Alex's trip)."
    assert [
        b.draft.title for b in await japan.bookings() if b.draft.kind is BookingKind.ACTIVITY
    ] == ["Tea ceremony"]
    assert sorted(await japan.activity()) == [  # all at the same moment
        "Sam T.: added Castle",
        "Sam T.: changed Castle",
        "Sam T.: changed Tea ceremony",
        "Sam T.: cleared the name of Day 3",
        "Sam T.: moved Castle to Day 2",
        'Sam T.: named Day 3 "Nikko"',
        "Sam T.: removed Castle",
    ]


async def test_a_member_changes_the_notes_and_nothing_else_of_the_trip(japan: Japan) -> None:
    asked = await japan.asked(japan.sam, "update_trip", {"notes": "Bring cash and an adapter"})
    assert asked == (
        'Change the notes on the Tokyo, Japan trip (Alex\'s trip) to: "Bring cash and an adapter"?'
    )
    done = await japan.use(japan.sam, "update_trip", {"notes": "Bring cash and an adapter"})
    assert done == "Notes changed on the Tokyo, Japan trip (Alex's trip)."
    trip = await japan.stored()
    assert trip.notes == "Bring cash and an adapter"
    assert (trip.budget, trip.companions, trip.start) == (
        Money.of("3000", "SGD"), ("Ann",), date(2026, 12, 10)
    )  # fmt: skip
    assert await japan.activity() == ["Sam T.: changed the notes"]

    # Notes with anything else is a change of details, which isn't theirs.
    before = await japan.stored()
    assert await japan.use(japan.sam, "update_trip", {"notes": "x", "budget": "5000"}) == REFUSED
    assert await japan.stored() == before


async def test_a_member_adds_to_dos_and_cover_to_the_owners_trip_without_a_price(
    japan: Japan,
) -> None:
    done = await japan.use(
        japan.sam, "add_trip_todo", {"trip": "japan", "text": "Get yen", "due": "2026-12-08"}
    )
    assert done == (
        "Added to the Tokyo, Japan trip's to-do list (Alex's trip): Get yen, due Tue 08 Dec. "
        "I'll remind them the day before."
    )
    args = {
        "trip": "japan", "kind": "insurance", "name": "Harbour Cover", "reference": "TX-4471",
        "phone": "+65 6123 4567", "cost": "89", "currency": "SGD",
    }  # fmt: skip
    asked = await japan.asked(japan.sam, "add_trip_cover", args)
    assert asked == (
        "Add to the Tokyo, Japan trip's cover and documents (Alex's trip): Harbour Cover "
        "(insurance, ref TX-4471, phone +65 6123 4567)? "
        "I left the price out: only Alex can add costs on a shared trip."
    )
    saved = await japan.use(japan.sam, "add_trip_cover", args)
    assert "counts under Money" not in saved and "89" not in saved
    assert saved.endswith("I left the price out: only Alex can add costs on a shared trip.")
    async with japan.uow() as tx:
        [cover] = await tx.trips.list_covers(japan.alex.id, japan.trip.id)
    assert (cover.user_id, cover.cost, cover.logged_transaction_id) == (japan.alex.id, None, None)
    assert [t.text for t in (await japan.stored()).todos] == ["Get yen"]
    assert sorted(await japan.activity()) == [
        "Sam T.: added Harbour Cover to cover and documents",
        "Sam T.: added the to-do Get yen",
    ]
    # The member's view of the trip lists both, with no price; the owner's counts the cost.
    status = await japan.use(japan.sam, "trip_status", {"trip": "japan"})
    assert "To do: Get yen (due Tue 08 Dec)." in status
    assert "Cover and documents: Harbour Cover (insurance, ref TX-4471" in status
    assert "89" not in status
    # Someone with no part in the trip finds no trip.
    for tool, other in (
        ("add_trip_todo", {"trip": "Tokyo", "text": "Mine now"}),
        ("add_trip_cover", {"trip": "Tokyo", "kind": "visa", "name": "Mine now"}),
    ):
        assert await japan.use(japan.rin, tool, other) == "Error: no trips yet"
    assert len((await japan.stored()).todos) == 1


async def test_a_member_searches_for_places_near_the_owners_trip(japan: Japan) -> None:
    found = await japan.use(japan.sam, "find_places", {"query": "noodles", "day": "2"})
    assert japan.places.searches == ["noodles, Tokyo, Japan"]
    assert found.startswith("Searched in Tokyo, Japan")
    assert "Hanok Noodle Bar" in found
    info = await japan.use(japan.sam, "place_info", {"trip": "japan", "place": "fakePlaceNoodle01"})
    assert "Hanok Noodle Bar" in info


async def test_the_owners_own_chat_edits_are_noted_too_without_a_summary(
    engine: AsyncEngine, japan: Japan
) -> None:
    await japan.use(
        japan.alex,
        "add_to_itinerary",
        {
            "kind": "activity",
            "name": "Ramen",
            "day": "2026-12-12",
            "cost": "1200",
            "currency": "JPY",
        },
    )
    (ramen,) = [b for b in await japan.bookings() if b.draft.title == "Ramen"]
    assert ramen.cost == Money.of("1200", "JPY")
    assert await japan.activity() == ["Alex: added Ramen"]
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(jobs).where(jobs.c.kind == access_cases.DIGEST_JOB)
            )
            == 0
        )


# --- money -------------------------------------------------------------------------------


MONEY: list[tuple[str, dict[str, object]]] = [
    ("update_trip", {"budget": "5000"}),
    ("update_trip", {"destination": "Osaka"}),
    ("update_trip", {"start": "2026-12-12"}),
    ("update_trip", {"companions": ["Ann", "Sam"]}),
    ("update_trip", {"set_aside": "400"}),
    ("delete_trip", {}),
    ("add_to_trip", {"transaction_id": "00000000-0000-4000-8000-000000000000"}),
    ("remove_from_trip", {"transaction_id": "00000000-0000-4000-8000-000000000000"}),
    ("split_trip_costs", {}),
    ("they_paid", {"person": "Ann", "amount": "460"}),
    ("settle_up", {}),
    ("settle_up", {"person": "Ann"}),
    ("research_to_trip", {}),
]


@pytest.mark.parametrize(("tool", "args"), MONEY)
async def test_money_and_trip_details_are_refused_to_a_member(
    engine: AsyncEngine, japan: Japan, tool: str, args: dict[str, object]
) -> None:
    trip, bookings = await japan.stored(), await japan.bookings()
    async with engine.connect() as db:
        rows = await db.scalar(select(func.count()).select_from(transactions))
    said = await japan.use(japan.sam, tool, {"trip": "Japan", **args})
    assert said == REFUSED
    spec = japan.tools[tool]
    looking = (tool, args) == ("settle_up", {})  # nothing to confirm, so it refuses on running
    if spec.confirm is not None and not looking:
        with pytest.raises(Forbidden, match="Only Alex can change money"):
            await japan.asked(japan.sam, tool, {"trip": "Japan", **args})
    # Neither the trip, its entries nor either person's ledger was touched.
    assert await japan.stored() == trip and await japan.bookings() == bookings
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(transactions)) == rows
    assert await japan.activity() == []
    assert await trip_cases.list_trips(japan.uow(), japan.sam.id) == []


async def test_the_owner_still_changes_money_on_a_shared_trip(japan: Japan) -> None:
    done = await japan.use(japan.alex, "update_trip", {"trip": "Japan", "budget": "5000"})
    assert done.startswith("Trip updated: Tokyo, Japan")
    assert (await japan.stored()).budget == Money.of("5000", "SGD")


# --- screenshots ----------------------------------------------------------------------------


async def test_a_screenshot_captioned_with_the_shared_trip_lands_there_without_prices(
    uow: UowFactory, japan: Japan
) -> None:
    reader = FakeTripReader()
    agent = build(uow, scripted(), trips=reader)
    replies = await agent.handle_photo(
        japan.sam.id, b"png", "image/png", "add these to our Japan trip", "p1"
    )
    assert replies[0].text.splitlines()[0] == "✈️ Added to your Tokyo, Japan trip:"
    assert "64500" not in replies[0].text and "64,500" not in replies[0].text
    assert "JPY" not in replies[0].text
    assert replies[-1].text == (
        "That's Alex's trip, so I left out any prices: only Alex can add costs."
    )
    added = [b for b in await japan.bookings() if b.draft.title != "Tea ceremony"]
    kumo = next(b for b in added if "Kumo" in b.draft.title)
    assert (kumo.user_id, kumo.trip_id, kumo.cost) == (japan.alex.id, japan.trip.id, None)
    assert await japan.activity() == ["Sam T.: read a screenshot onto the itinerary"]
    # Sam's own account holds nothing from it.
    async with uow() as tx:
        assert await tx.trips.list_bookings(japan.sam.id) == []


async def test_a_screenshot_with_no_shared_trip_named_goes_where_it_always_did(
    uow: UowFactory, japan: Japan
) -> None:
    agent = build(uow, scripted(), trips=FakeTripReader())
    reply = only(await agent.handle_photo(japan.sam.id, b"png", "image/png", "my itinerary", "p2"))
    assert reply.text.startswith("No trip covers these dates yet")
    assert await japan.activity() == []
    async with uow() as tx:
        assert len(await tx.trips.list_bookings(japan.sam.id)) == 4  # Sam's own, loose


async def test_someone_not_on_the_trip_cannot_aim_a_screenshot_at_it(
    uow: UowFactory, japan: Japan
) -> None:
    agent = build(uow, scripted(), trips=FakeTripReader())
    reply = only(
        await agent.handle_photo(japan.rin.id, b"png", "image/png", "for the Japan trip", "p3")
    )
    assert reply.text.startswith("No trip covers these dates yet")
    assert len(await japan.bookings()) == 2
