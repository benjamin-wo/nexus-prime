"""A trip's Prep tab: to-dos, cover and documents, the suggestions and "Not needed", a
cover's cost counting with the trip's bookings and being logged once, who may see and
change what, reminders and the chat tools. Every name, number and figure here is made up."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import bookings as booking_cases
from nexus.application import prep as prep_cases
from nexus.application import transactions as tx_cases
from nexus.application import trips as trip_cases
from nexus.domain.errors import Conflict
from nexus.domain.money import Money
from nexus.domain.prep import CoverDraft, CoverKind, Todo
from nexus.infra.db.migrations import alembic_config
from tests.fakes import NOW, FakeRates
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import messages, person
from tests.integration.test_shared_trips import (
    MONEY_MESSAGE,
    TRIP,
    UNKNOWN,
    Shared,
    make_trip,
    shared,  # noqa: F401 - a fixture
)
from tests.integration.test_trips import draft
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

SG = ZoneInfo("Asia/Singapore")
INSURANCE = {
    "kind": "insurance",
    "name": "Harbour Cover",
    "reference": "TX-4471",
    "phone": "+65 6123 4567",
    "starts": "2026-12-10",
    "ends": "2026-12-18",
}


async def owner_trip(world: World, **changes: Any) -> tuple[Any, str, str]:
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    trip = await make_trip(owner, **changes)
    return owner, trip, f"/api/travel/trips/{trip}"


async def page(who: Any, path: str) -> dict[str, Any]:
    got = await who.get(path)
    assert got.status_code == 200, got.text
    body: dict[str, Any] = got.json()
    return body


# --- to-dos ----------------------------------------------------------------------------


async def test_the_to_do_list_is_replaced_whole_like_packing(world: World) -> None:
    owner, _, path = await owner_trip(world)
    assert (await page(owner, path))["todos"] == []
    put = await owner.send(
        "PUT", f"{path}/todos",
        {"todos": [
            {"text": " Get  yen ", "due": "2026-12-08"},
            {"text": "get yen"},
            {"text": ""},
            {"text": "Pay with 4111 1111 1111 1111", "done": True},
        ]},
    )  # fmt: skip
    assert put.status_code == 200, put.text
    todos = put.json()["todos"]
    assert [(t["text"], t["due"], t["done"]) for t in todos] == [
        ("Get yen", "2026-12-08", False),
        ("Pay with •••• 1111", None, True),
    ]
    assert all(len(t["id"]) == 8 for t in todos)
    assert (await page(owner, path))["todos"] == todos

    # Sending the list back with a tick keeps each to-do's id (so no reminder repeats).
    ticked = [{**todos[0], "done": True}, todos[1]]
    again = await owner.send("PUT", f"{path}/todos", {"todos": ticked})
    assert [t["id"] for t in again.json()["todos"]] == [t["id"] for t in todos]
    assert again.json()["todos"][0]["done"] is True

    too_many = {"todos": [{"text": f"thing {n}"} for n in range(51)]}
    assert (await owner.send("PUT", f"{path}/todos", too_many)).status_code == 422
    assert (
        await owner.send("PUT", f"{path}/todos", {"todos": [{"text": "x" * 81}]})
    ).status_code == 422
    assert (
        await owner.send("PUT", f"{path}/todos", {"todos": [{"text": "x", "x": 1}]})
    ).status_code == 422
    assert (await owner.send("PUT", f"{path}/todos", {"todos": []})).json()["todos"] == []
    # Editing the trip itself leaves its to-dos alone.
    await owner.send("PUT", f"{path}/todos", {"todos": [{"text": "Get yen"}]})
    edited = await owner.send("PUT", path, {**TRIP, "budget": "900"})
    assert edited.status_code == 200, edited.text
    assert [t["text"] for t in (await page(owner, path))["todos"]] == ["Get yen"]


# --- suggestions -----------------------------------------------------------------------


async def test_suggestions_come_from_the_trip_and_not_needed_is_remembered(world: World) -> None:
    owner, _, path = await owner_trip(world)

    async def keys() -> list[str]:
        return [s["key"] for s in (await page(owner, path))["prep_suggestions"]]

    first = (await page(owner, path))["prep_suggestions"]
    assert [s["key"] for s in first] == ["insurance", "visa", "passport", "money"]
    assert first[0] == {
        "key": "insurance",
        "text": "Travel insurance",
        "sub": "Medical and cancellation cover for the dates",
        "action": "add_cover",
    }
    assert first[1]["text"] == "Check entry rules for Tokyo"  # a destination with no country

    gone = await owner.send("POST", f"{path}/prep/dismiss", {"key": "insurance"})
    assert gone.status_code == 200
    assert [s["key"] for s in gone.json()["prep_suggestions"]] == ["visa", "passport", "money"]
    assert (
        await owner.send("POST", f"{path}/prep/dismiss", {"key": "insurance"})
    ).status_code == 200
    assert await keys() == ["visa", "passport", "money"]
    back = await owner.send("DELETE", f"{path}/prep/dismiss/insurance")
    assert back.status_code == 200 and back.json()["prep_suggestions"][0]["key"] == "insurance"
    assert (await owner.send("DELETE", f"{path}/prep/dismiss/insurance")).status_code == 200
    assert (
        await owner.send("POST", f"{path}/prep/dismiss", {"key": "nonsense"})
    ).status_code == 422
    assert (await owner.send("DELETE", f"{path}/prep/dismiss/nonsense")).status_code == 422

    # A to-do or a cover does the suggestion's work.
    await owner.send("PUT", f"{path}/todos", {"todos": [{"text": "Renew my passport"}]})
    assert await keys() == ["insurance", "visa", "money"]
    made = await owner.send("POST", f"{path}/covers", INSURANCE)
    assert made.status_code == 201
    assert await keys() == ["visa", "money"]
    assert (await owner.send("DELETE", f"{path}/covers/{made.json()['id']}")).status_code == 204
    assert await keys() == ["insurance", "visa", "money"]

    # At home there is nothing to suggest.
    _, _, home = await owner_trip(world, destination="Penang", currency="SGD")
    assert (await page(owner, home))["prep_suggestions"] == []


# --- cover and documents ---------------------------------------------------------------


async def test_cover_is_added_changed_and_removed(world: World) -> None:
    owner, _, path = await owner_trip(world)
    made = await owner.send("POST", f"{path}/covers", {**INSURANCE, "note": "Call first"})
    assert made.status_code == 201, made.text
    cover = made.json()
    assert cover == {
        "id": cover["id"], **INSURANCE, "cost": None, "logged": False, "note": "Call first",
    }  # fmt: skip
    assert (await page(owner, path))["covers"] == [cover]

    changed = await owner.send(
        "PUT", f"{path}/covers/{cover['id']}",
        {**INSURANCE, "name": "Harbour Cover Plus", "cost": "89", "currency": "SGD"},
    )  # fmt: skip
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Harbour Cover Plus"
    assert changed.json()["cost"] == {"amount": "89.0000", "currency": "SGD"}
    assert changed.json()["note"] is None  # an edit sends the whole cover
    # A cost with no currency is in the home one.
    plain = await owner.send(
        "POST", f"{path}/covers", {"kind": "visa", "name": "eVisa", "cost": "20"}
    )
    assert plain.json()["cost"] == {"amount": "20.0000", "currency": "SGD"}

    for bad in (
        {**INSURANCE, "reference": "4111 1111 1111 1111"},
        {**INSURANCE, "reference": "Passport E1234567"},
        {**INSURANCE, "name": "Passport copy", "reference": "E1234567"},
        {**INSURANCE, "phone": "call me"},
        {**INSURANCE, "starts": "2026-12-18", "ends": "2026-12-10"},
        {**INSURANCE, "kind": "policy"},
        {**INSURANCE, "name": ""},
        {**INSURANCE, "cost": "0"},
        {**INSURANCE, "cost": "ten"},
        {**INSURANCE, "user_id": UNKNOWN},
    ):
        assert (await owner.send("POST", f"{path}/covers", bad)).status_code == 422, bad
    assert len((await page(owner, path))["covers"]) == 2  # not one of those was kept

    assert (await owner.send("DELETE", f"{path}/covers/{cover['id']}")).status_code == 204
    assert (await owner.send("DELETE", f"{path}/covers/{cover['id']}")).status_code == 404
    assert (await owner.send("PUT", f"{path}/covers/{UNKNOWN}", INSURANCE)).status_code == 404
    assert (await owner.send("PUT", f"{path}/covers/not-an-id", INSURANCE)).status_code == 404
    assert [c["name"] for c in (await page(owner, path))["covers"]] == ["eVisa"]
    # 30 at most.
    for n in range(29):
        assert (
            await owner.send("POST", f"{path}/covers", {"kind": "other", "name": f"Doc {n}"})
        ).status_code == 201
    over = await owner.send("POST", f"{path}/covers", {"kind": "other", "name": "One more"})
    assert over.status_code == 422 and "at most 30" in over.text


# --- money -----------------------------------------------------------------------------


async def test_a_covers_cost_counts_like_a_bookings_until_it_is_logged_once(world: World) -> None:
    owner, trip, path = await owner_trip(world, budget="1000")
    booking = {"kind": "activity", "name": "Tour", "day": "2026-12-12", "cost": "100"}
    assert (await owner.send("POST", f"{path}/bookings", booking)).status_code == 201
    before = await page(owner, path)
    assert before["booked"]["amount"] == "100.0000"

    cover = (
        await owner.send("POST", f"{path}/covers", {**INSURANCE, "cost": "89", "currency": "SGD"})
    ).json()
    abroad = (
        await owner.send(
            "POST",
            f"{path}/covers",
            {"kind": "visa", "name": "eVisa", "cost": "50", "currency": "USD"},
        )
    ).json()  # USD: 50 at 1.3000 on the day it was added
    unconvertible = (
        await owner.send(
            "POST",
            f"{path}/covers",
            {"kind": "other", "name": "Letter", "cost": "9", "currency": "NOK"},
        )
    ).json()  # no rate: left out, as for a booking
    free = (await owner.send("POST", f"{path}/covers", {"kind": "other", "name": "Free"})).json()
    detail = await page(owner, path)
    assert detail["booked"]["amount"] == "254.0000"  # 100 + 89 + 65
    assert detail["booked_unlogged"]["amount"] == "254.0000"
    assert detail["to_spend"]["amount"] == "746.0000"
    assert detail["spending"]["spent"]["amount"] == "0.0000"
    assert {c["id"]: (c["cost"] is not None, c["logged"]) for c in detail["covers"]} == {
        cover["id"]: (True, False),
        abroad["id"]: (True, False),
        unconvertible["id"]: (True, False),
        free["id"]: (False, False),
    }

    # Logging records the expense once: Travel, to the cover's name, on the trip.
    logged = await owner.send("POST", f"{path}/covers/{cover['id']}/log")
    assert logged.status_code == 200, logged.text
    assert logged.json()["logged"] is True and logged.json()["cost"]["amount"] == "89.0000"
    detail = await page(owner, path)
    assert detail["booked"]["amount"] == "254.0000"  # still booked
    assert detail["booked_unlogged"]["amount"] == "165.0000"  # but 89 is spent now
    assert detail["spending"]["spent"]["amount"] == "89.0000"
    item = next(i for i in detail["items"] if i["counterparty"] == "Harbour Cover")
    assert (item["category"], item["amount"]["amount"], item["linked"]) == (
        "Travel",
        "89.0000",
        True,
    )
    assert detail["to_spend"]["amount"] == "746.0000"  # the same money, now logged
    again = await owner.send("POST", f"{path}/covers/{cover['id']}/log")
    assert again.status_code == 409
    assert len((await page(owner, path))["items"]) == 1  # no second expense

    assert (await owner.send("POST", f"{path}/covers/{free['id']}/log")).status_code == 422
    assert (await owner.send("POST", f"{path}/covers/{UNKNOWN}/log")).status_code == 404

    # Deleting the cover leaves the expense; deleting the expense makes it count (and log) again.
    assert (await owner.send("DELETE", f"{path}/covers/{cover['id']}")).status_code == 204
    assert (await page(owner, path))["spending"]["spent"]["amount"] == "89.0000"
    assert trip


async def test_a_cover_whose_expense_was_deleted_can_be_logged_again(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(uow(), user, draft(), now=NOW)
    cover = await prep_cases.add_cover(
        uow(), user, trip.id,
        CoverDraft(CoverKind.INSURANCE, "Harbour Cover", cost=Money.of("89", "SGD")), now=NOW,
    )  # fmt: skip
    first, spent = await prep_cases.log_cover(uow(), user, trip.id, cover.id, now=NOW)
    assert first.logged_transaction_id == spent.id
    assert (spent.counterparty, spent.amount) == ("Harbour Cover", Money.of("89", "SGD"))
    with pytest.raises(Conflict):
        await prep_cases.log_cover(uow(), user, trip.id, cover.id, now=NOW)
    await tx_cases.delete_transaction(uow(), user.id, spent.id)
    view = await trip_cases.trip_view(uow, FakeRates({}), user, trip.id, now=NOW)
    assert view.booked_unlogged == Money.of("89", "SGD")  # counted again
    second, other = await prep_cases.log_cover(uow(), user, trip.id, cover.id, now=NOW)
    assert second.logged_transaction_id == other.id != spent.id
    view = await trip_cases.trip_view(uow, FakeRates({}), user, trip.id, now=NOW)
    assert view.booked_unlogged == Money.zero("SGD")
    lines = trip_cases.describe_view(view)
    assert any(x.startswith("Cover costs") and "logged as an expense" in x for x in lines)


# --- who may see and change what -------------------------------------------------------


async def test_a_member_edits_to_dos_and_cover_and_never_sees_its_cost(shared: Shared) -> None:  # noqa: F811
    owner, member, outsider, path = shared.owner, shared.member, shared.outsider, shared.path
    priced = (
        await owner.send("POST", f"{path}/covers", {**INSURANCE, "cost": "89", "currency": "SGD"})
    ).json()

    # The member reads the cover, with its reference and phone and without the cost.
    seen = (await page(member, path))["covers"]
    assert seen == [{**priced, "cost": None, "logged": False}]
    assert (seen[0]["reference"], seen[0]["phone"]) == ("TX-4471", "+65 6123 4567")
    assert (await page(member, path))["booked"] is None

    # They add, change and remove to-dos and cover, as the owner's trip being edited.
    todos = await member.send(
        "PUT", f"{path}/todos", {"todos": [{"text": "Get yen", "due": "2026-12-08"}]}
    )
    assert todos.status_code == 200 and todos.json()["covers"][0]["cost"] is None
    added = await member.send("POST", f"{path}/covers", {"kind": "visa", "name": "eVisa"})
    assert added.status_code == 201 and added.json()["cost"] is None
    renamed = await member.send(
        "PUT", f"{path}/covers/{priced['id']}", {**INSURANCE, "name": "Harbour Cover Plus"}
    )
    assert renamed.status_code == 200 and renamed.json()["cost"] is None
    # ... and the owner's cost is still there.
    mine = next(c for c in (await page(owner, path))["covers"] if c["id"] == priced["id"])
    assert (mine["name"], mine["cost"]) == (
        "Harbour Cover Plus",
        {"amount": "89.0000", "currency": "SGD"},
    )
    dismissed = await member.send("POST", f"{path}/prep/dismiss", {"key": "money"})
    assert dismissed.status_code == 200 and "money" not in str(dismissed.json()["prep_suggestions"])
    assert (await member.send("DELETE", f"{path}/covers/{added.json()['id']}")).status_code == 204

    # The owner's money is not theirs to give or take: a cost, or logging it.
    for body in ({**INSURANCE, "cost": "1"}, {**INSURANCE, "currency": "USD"}):
        assert (await member.send("POST", f"{path}/covers", body)).status_code == 403
        assert (await member.send("PUT", f"{path}/covers/{priced['id']}", body)).status_code == 403
    logged = await member.send("POST", f"{path}/covers/{priced['id']}/log")
    assert (logged.status_code, logged.json()["detail"]) == (403, MONEY_MESSAGE)
    after = await page(owner, path)
    assert after["spending"]["spent"]["amount"] == "0.0000" and after["items"] == []

    # Someone with no part in the trip finds nothing, whatever they try.
    attempts: list[tuple[str, str, Any]] = [
        ("PUT", f"{path}/todos", {"todos": [{"text": "Hmm"}]}),
        ("POST", f"{path}/covers", INSURANCE),
        ("PUT", f"{path}/covers/{priced['id']}", INSURANCE),
        ("DELETE", f"{path}/covers/{priced['id']}", None),
        ("POST", f"{path}/covers/{priced['id']}/log", None),
        ("POST", f"{path}/prep/dismiss", {"key": "money"}),
        ("DELETE", f"{path}/prep/dismiss/money", None),
    ]
    for method, url, body in attempts:
        got = await outsider.send(method, url, body)
        assert got.status_code in (403, 404), (method, url, got.status_code)
        assert got.status_code == 404 or "guests" in got.text
    assert [t["text"] for t in (await page(owner, path))["todos"]] == ["Get yen"]

    # What the member changed is noted in the trip's activity, with no money in it.
    said = [a["summary"] for a in (await owner.get(f"{path}/activity")).json()]
    assert "changed the to-do list" in said
    assert "added eVisa to cover and documents" in said
    assert "changed Harbour Cover Plus in cover and documents" in said
    assert "removed eVisa from cover and documents" in said
    assert "marked a prep suggestion as not needed" in said
    assert not any("89" in line for line in said)


async def test_the_shared_link_has_neither_to_dos_nor_cover(world: World) -> None:
    owner, _, path = await owner_trip(world)
    await owner.send("PUT", f"{path}/todos", {"todos": [{"text": "Get yen"}]})
    await owner.send("POST", f"{path}/covers", {**INSURANCE, "cost": "89", "currency": "SGD"})
    token = (await owner.send("POST", f"{path}/share", {})).json()["token"]
    got = await world.browser().get(f"/api/shared/trips/{token}")
    assert got.status_code == 200
    for word in ("todo", "cover", "Get yen", "Harbour", "TX-4471", "6123", "89"):
        assert word not in got.text, word


# --- reminders -------------------------------------------------------------------------


async def test_a_to_do_is_reminded_once_the_morning_before(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(),
        user,
        draft(destination="Tokyo, Japan", start=date(2026, 12, 10), end=date(2026, 12, 18)),
        now=NOW,
    )
    await prep_cases.set_todos(
        uow(), user, trip.id,
        [
            Todo("a1", "Get yen", date(2026, 12, 8)),
            Todo("a2", "Buy a rail pass", date(2026, 12, 8), True),  # done: no reminder
            Todo("a3", "Print tickets"),  # no day: none
            Todo("a4", "Pack", date(2026, 12, 12)),
        ],
        now=NOW,
    )  # fmt: skip
    morning = datetime(2026, 12, 7, 8, 5, tzinfo=SG)
    early = datetime(2026, 12, 7, 7, 55, tzinfo=SG)
    assert await booking_cases.remind(uow, user, now=early) == 0
    assert await booking_cases.remind(uow, user, now=morning) == 1
    assert await booking_cases.remind(uow, user, now=morning + timedelta(hours=1)) == 0
    assert (
        await booking_cases.remind_everyone(uow, now=morning.astimezone(UTC) + timedelta(hours=3))
        == 0
    )
    sent = [m["text"] for m in await messages(engine)]
    assert sent == ["Tomorrow: Get yen for Tokyo, Japan"]

    # Ticking it off, or a new date, is not a repeat; the new date gets its own reminder.
    await prep_cases.set_todos(
        uow(),
        user,
        trip.id,
        [Todo("a1", "Get yen", date(2026, 12, 9)), Todo("a4", "Pack", date(2026, 12, 12))],
        now=NOW,
    )
    assert await booking_cases.remind(uow, user, now=morning + timedelta(days=1)) == 1
    day_before_pack = datetime(2026, 12, 11, 9, tzinfo=SG)
    assert await booking_cases.remind(uow, user, now=day_before_pack) == 1
    await prep_cases.set_todos(
        uow(), user, trip.id, [Todo("a1", "Get yen", date(2026, 12, 9), True)], now=NOW
    )
    assert await booking_cases.remind(uow, user, now=day_before_pack) == 0


async def test_a_finished_trips_to_dos_are_not_reminded(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(
        uow(),
        user,
        draft(start=date(2026, 10, 1), end=date(2026, 10, 3)),
        now=NOW - timedelta(days=30),
    )
    await prep_cases.set_todos(
        uow(), user, trip.id, [Todo("a1", "Return the SIM", date(2026, 11, 1))], now=NOW
    )
    assert await booking_cases.remind(uow, user, now=datetime(2026, 10, 31, 9, tzinfo=SG)) == 0


# --- the chat tools --------------------------------------------------------------------


async def test_chat_adds_to_dos_and_cover(uow: UowFactory) -> None:
    user = await person(uow)
    await trip_cases.create_trip(
        uow(),
        user,
        draft(destination="Tokyo, Japan", start=date(2026, 12, 10), end=date(2026, 12, 18)),
        now=NOW,
    )
    tools = build_tools(lambda _: "")
    ctx = ToolContext(user, uow, NOW, FakeRates({}))

    async def use(name: str, args: dict[str, object]) -> str:
        return (await run_tool(tools[name], ctx, args)).text

    # A to-do saves at once and says it will remind the day before.
    assert tools["add_trip_todo"].confirm is None
    said = await use("add_trip_todo", {"trip": "japan", "text": "Get yen", "due": "2026-12-08"})
    assert (
        said == "Added to the Tokyo, Japan trip's to-do list: Get yen, due Tue 08 Dec. "
        "I'll remind them the day before."
    )
    assert "is on the Tokyo, Japan trip's to-do list already" in await use(
        "add_trip_todo", {"text": "get YEN"}
    )
    assert "Added to the Tokyo, Japan trip's to-do list: Renew the SIM." == await use(
        "add_trip_todo", {"text": "Renew the SIM"}
    )
    # What can't be kept comes back as an error for the model to explain.
    assert (await use("add_trip_todo", {"text": "  "})).startswith("Error: a to-do needs")
    assert "dates must look like" in await use("add_trip_todo", {"text": "x", "due": "next week"})

    # A cover asks first, shows what would be kept, and says where its cost counts.
    args: dict[str, object] = {
        "trip": "japan", "kind": "insurance", "name": "Harbour Cover", "reference": "TX-4471",
        "phone": "+65 6123 4567", "cost": "89", "currency": "SGD",
    }  # fmt: skip
    confirm = tools["add_trip_cover"].confirm
    assert confirm is not None
    asked = await confirm(ctx, tools["add_trip_cover"].parse(args))
    assert asked == (
        "Add to the Tokyo, Japan trip's cover and documents: Harbour Cover "
        "(insurance, ref TX-4471, phone +65 6123 4567), 89.00 SGD?"
    )
    assert await trip_cases.list_trips(uow(), user.id) and not await prep_cases.list_covers(
        uow(), user.id, (await trip_cases.list_trips(uow(), user.id))[0].id
    )  # nothing is saved by asking
    saved = await use("add_trip_cover", args)
    assert saved.startswith(
        "Added to the Tokyo, Japan trip's cover and documents: Harbour Cover (insurance"
    )
    assert "counts under Money" in saved and "logged as an expense" in saved
    refused = await use("add_trip_cover", {**args, "reference": "4111 1111 1111 1111"})
    assert refused.startswith("Error:") and "card or passport number" in refused

    status = await use("trip_status", {"trip": "japan"})
    assert "To do: Get yen (due Tue 08 Dec); Renew the SIM." in status
    assert (
        "Cover and documents: Harbour Cover (insurance, ref TX-4471, phone +65 6123 4567)."
        in status
    )
    assert (
        "Cover costs (counted in what's booked): Harbour Cover 89.00 SGD, not logged yet." in status
    )
    assert "Booked: 89.00 SGD, of which 89.00 SGD isn't logged as an expense yet." in status


# --- the migration ---------------------------------------------------------------------


async def test_migration_0048_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(uow(), user, draft(), now=NOW)
    await prep_cases.set_todos(uow(), user, trip.id, [Todo("a1", "Get yen")], now=NOW)
    await prep_cases.add_cover(uow(), user, trip.id, CoverDraft(CoverKind.VISA, "eVisa"), now=NOW)
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0047")
    async with engine.connect() as db:
        tables: set[str] = set(
            (await db.execute(text("SELECT tablename FROM pg_tables"))).scalars()
        )
        columns: set[str] = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'trips'"
                    )
                )
            ).scalars()
        )
    assert "trip_covers" not in tables and not columns & {"todos", "prep_dismissed"}
    await upgrade(empty_database_url)
    async with engine.connect() as db:
        assert (await db.execute(text("SELECT count(*) FROM trips"))).scalar_one() == 1
        assert (await db.execute(text("SELECT count(*) FROM trip_covers"))).scalar_one() == 0
        assert (await db.execute(text("SELECT todos FROM trips"))).scalar_one() == []


async def test_cover_rows_obey_the_database_rules(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(uow(), user, draft(), now=NOW)
    cover = await prep_cases.add_cover(
        uow(),
        user,
        trip.id,
        CoverDraft(CoverKind.INSURANCE, "Harbour Cover", cost=Money.of("5", "SGD")),
        now=NOW,
    )
    for bad in (
        "UPDATE trip_covers SET cost_amount = 0",
        "UPDATE trip_covers SET cost_currency = NULL",
        "UPDATE trip_covers SET kind = 'policy'",
        "UPDATE trip_covers SET starts = '2026-12-18', ends = '2026-12-10'",
        "UPDATE trip_covers SET name = ''",
    ):
        with pytest.raises(Exception, match="violates check constraint"):
            async with engine.begin() as db:
                await db.execute(text(bad))
    # A trip's covers go with it; the expense logged for one stays.
    _, spent = await prep_cases.log_cover(uow(), user, trip.id, cover.id, now=NOW)
    await trip_cases.delete_trip(uow(), user.id, trip.id)
    async with engine.connect() as db:
        assert (await db.execute(text("SELECT count(*) FROM trip_covers"))).scalar_one() == 0
        assert (await db.execute(text("SELECT count(*) FROM transactions"))).scalar_one() == 1
    assert spent.counterparty == "Harbour Cover"
