"""Undo reverses itinerary changes made from chat as well as ledger writes: whichever is
newest, a whole chat message's changes together, never another user's. Every name and
figure here is made up."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import AgentDeps, AgentGraph
from nexus.agent.service import UNDO, AgentService, Reply
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import bookings as booking_cases
from nexus.application import transactions as tx_cases
from nexus.application import trips as trip_cases
from nexus.application import undo as undo_cases
from nexus.application.bookings import ChatEdit
from nexus.application.clock import utcnow
from nexus.application.ports import LedgerQuery
from nexus.domain.bookings import Booking
from nexus.domain.errors import NothingToUndo
from nexus.domain.ledger import Direction, User, UserId
from nexus.domain.money import Money
from nexus.domain.trip_changes import ChangeKind, from_snapshot, snapshot
from nexus.domain.trips import Trip
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import trip_changes
from tests.fakes import NOW, FakeRates, ScriptedModel, say, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

RATES = FakeRates({})
DAY = "2026-12-12"


async def spain(uow: UowFactory, user: User) -> Trip:
    return await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft(
            "Spain", date(2026, 12, 10), date(2026, 12, 18), "EUR", Money.of("3000", "SGD")
        ),
        now=NOW,
    )


def plan(name: str, **more: object) -> dict[str, object]:
    return {"kind": "activity", "name": name, "day": DAY, **more}


def chat(user: User, batch: UUID | None = None) -> ChatEdit:
    return ChatEdit(batch or uuid4(), user.id, utcnow())


async def bookings(uow: UowFactory, user: User, trip: Trip) -> list[Booking]:
    async with uow() as tx:
        return await tx.trips.list_bookings(user.id, trip_id=trip.id)


async def titles(uow: UowFactory, user: User, trip: Trip) -> list[str]:
    return sorted(b.draft.title for b in await bookings(uow, user, trip))


async def undo(uow: UowFactory, user: User) -> undo_cases.TripUndo:
    result = await undo_cases.undo_latest(uow(), user.id)
    assert isinstance(result, undo_cases.TripUndo)
    return result


async def log_expense(uow: UowFactory, user: User, merchant: str) -> None:
    await tx_cases.log_transaction(
        uow(),
        user.id,
        tx_cases.NewTransaction(Direction.OUT, Money.of("5", "SGD"), NOW, counterparty=merchant),
    )


async def ledger_count(uow: UowFactory, user: User) -> int:
    page = await tx_cases.list_ledger(uow(), user.id, LedgerQuery())
    return page.total


# --- one change at a time ---------------------------------------------------------------


async def test_undo_takes_back_an_added_entry(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Hilltop Castle"), None, now=NOW, record=chat(user)
    )
    done = await undo(uow, user)
    assert done.message() == "Undone: Hilltop Castle off the Spain trip."
    assert await titles(uow, user, trip) == []
    with pytest.raises(NothingToUndo):  # an undo is not itself undoable
        await undo_cases.undo_latest(uow(), user.id)


async def test_undo_puts_a_removed_entry_back_exactly_as_it_was(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    lunch = await booking_cases.add_manual(
        uow(),
        user.id,
        trip.id,
        plan(
            "Casa Verde",
            at="13:00",
            ends_at="14:30",
            address="Carrer Major 1",
            link="https://casaverde.example/menu",
            list_name="Eat",
            category="Food",
            order=2,
            place_id="fakePlaceCasaverde1",
        ),
        Money.of("40", "EUR"),
        now=NOW,
    )
    expense = await tx_cases.log_transaction(
        uow(), user.id, tx_cases.NewTransaction(Direction.OUT, Money.of("40", "EUR"), NOW)
    )
    async with uow() as tx:
        await tx.trips.set_booking(user.id, lunch.id, trip_id=trip.id, transaction_id=expense.id)
        await tx.commit()
    async with uow() as tx:
        before = await tx.trips.get_booking(user.id, lunch.id)
    assert before is not None and before.transaction_id == expense.id

    await booking_cases.delete_booking(uow(), user.id, lunch.id, record=chat(user))
    assert await titles(uow, user, trip) == []
    assert (await undo(uow, user)).message() == "Undone: Casa Verde back on the Spain trip."
    (back,) = await bookings(uow, user, trip)
    assert back == before  # same id, place, order, list, times, cost and expense
    assert back.draft.place_id == "fakePlaceCasaverde1" and back.draft.order == 2
    assert back.draft.ends_at == time(14, 30) and back.cost == Money.of("40", "EUR")


async def test_undo_changes_an_entry_back(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    dinner = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Dinner", at="20:00", list_name="Eat"), None, now=NOW
    )
    changed = await booking_cases.edit_booking(
        uow(), user.id, dinner.id, plan("Late dinner", at="22:00"), Money.of("30", "EUR"),
        record=chat(user),
    )  # fmt: skip
    assert changed.draft.title == "Late dinner" and changed.draft.list_name == "Eat"
    assert (await undo(uow, user)).message() == "Undone: Dinner back as it was on the Spain trip."
    (back,) = await bookings(uow, user, trip)
    assert back == dinner


async def test_a_change_made_by_the_web_is_not_recorded(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await log_expense(uow, user, "Coffee")
    castle = await booking_cases.add_manual(uow(), user.id, trip.id, plan("Castle"), None, now=NOW)
    await booking_cases.edit_booking(uow(), user.id, castle.id, plan("Castle", at="10:00"), None)
    await booking_cases.delete_booking(uow(), user.id, castle.id)
    async with engine.connect() as db:
        assert (await db.execute(select(func.count()).select_from(trip_changes))).scalar() == 0
    # So Undo still takes back the ledger entry, as before.
    result = await undo_cases.undo_latest(uow(), user.id)
    assert isinstance(result, tx_cases.UndoResult) and result.transaction.counterparty == "Coffee"
    assert await ledger_count(uow, user) == 0


# --- a chat message is one undo ---------------------------------------------------------


async def test_everything_one_message_changed_is_undone_together(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Casa Verde", at="13:00"), None, now=NOW
    )
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Gelato", at="16:00"), None, now=NOW
    )
    tools = build_tools(lambda _: "")
    ctx = replace(ToolContext(user, uow, NOW, RATES), batch=uuid4())

    async def use(name: str, args: dict[str, object]) -> str:
        return (await run_tool(tools[name], ctx, args)).text

    # "Casa Verde off, castle on, Rosa Ices on, gelato later" in one message.
    await use("remove_from_itinerary", {"item": "verde"})
    await use("add_to_itinerary", {"kind": "activity", "name": "Hilltop Castle", "day": DAY})
    await use("add_to_itinerary", {"kind": "activity", "name": "Rosa Ices", "day": DAY})
    await use("change_itinerary_entry", {"item": "gelato", "time": "17:30"})
    assert await titles(uow, user, trip) == sorted(["Hilltop Castle", "Rosa Ices", "Gelato"])

    assert (await undo(uow, user)).message() == (
        "Undone: Hilltop Castle and Rosa Ices off the Spain trip, Casa Verde back on, "
        "Gelato back as it was."
    )
    stored = await bookings(uow, user, trip)
    assert sorted(b.draft.title for b in stored) == ["Casa Verde", "Gelato"]
    assert {b.draft.title: b.draft.at for b in stored} == {
        "Gelato": time(16, 0),
        "Casa Verde": time(13, 0),
    }
    with pytest.raises(NothingToUndo):
        await undo_cases.undo_latest(uow(), user.id)


async def test_a_message_that_moves_a_plan_is_undone_with_the_plans_it_renumbered(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    first = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Museum", order=0), None, now=NOW
    )
    second = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Market", order=1), None, now=NOW
    )
    third = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Beach", order=2), None, now=NOW
    )
    edit = chat(user)
    await booking_cases.move_entry(uow(), user.id, third.id, date(2026, 12, 12), None, record=edit)
    order = {b.draft.title: b.draft.order for b in await bookings(uow, user, trip)}
    assert order == {"Beach": 0, "Museum": 1, "Market": 2}
    await undo(uow, user)
    now = {b.id: b for b in await bookings(uow, user, trip)}
    assert now[first.id] == first and now[second.id] == second and now[third.id] == third


async def test_each_chat_turn_is_its_own_undo(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    model = scripted(_adds("Hill Fort", "Rosa Ices"), say("Added."), _adds("Gelato"), say("Added."))
    agent = _agent(uow, model, _ticking())
    await _says(agent, user, "castle and rosa ices", "tg:1:1")
    await _says(agent, user, "gelato too", "tg:1:2")
    assert await titles(uow, user, trip) == sorted(["Hill Fort", "Rosa Ices", "Gelato"])

    undone = await agent.quick_action(user.id, "undo")
    assert [r.text for r in undone] == ["Undone: Gelato off the Spain trip."]
    undone = await agent.quick_action(user.id, "undo")
    assert [r.text for r in undone] == ["Undone: Hill Fort and Rosa Ices off the Spain trip."]
    assert await titles(uow, user, trip) == []
    nothing = await agent.quick_action(user.id, "undo")
    assert [r.text for r in nothing] == ["There is nothing to undo."]


# --- changes on one's own trip are made at once ------------------------------------------


def _call(name: str, args: dict[str, object]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c-{uuid4()}"}])


def _asks(replies: list[Reply]) -> bool:
    return any(b.data.startswith("hitl:") for r in replies for row in r.buttons for b in row)


async def test_own_trip_changes_without_a_cost_happen_at_once_with_undo(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Casa Verde", at="12:30"), None, now=NOW
    )
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Gelato", at="16:00"), None, now=NOW
    )
    model = scripted(
        _call("add_to_itinerary", plan("Hilltop Castle")),
        say("Added."),
        _call("change_itinerary_entry", {"item": "gelato", "time": "17:30"}),
        say("Moved."),
        _call("remove_from_itinerary", {"item": "verde"}),
        say("Removed."),
    )
    agent = _agent(uow, model, _ticking())

    added = await agent.handle_text(user.id, "add the castle", "tg:1:1")
    assert not _asks(added) and added[-1].buttons[-1] == [UNDO]
    assert await titles(uow, user, trip) == sorted(["Hilltop Castle", "Gelato", "Casa Verde"])
    changed = await agent.handle_text(user.id, "gelato later", "tg:1:2")
    assert not _asks(changed) and changed[-1].buttons[-1] == [UNDO]
    removed = await agent.handle_text(user.id, "drop l'autentic", "tg:1:3")
    assert not _asks(removed) and removed[-1].buttons[-1] == [UNDO]
    assert await titles(uow, user, trip) == sorted(["Hilltop Castle", "Gelato"])

    undone = await agent.quick_action(user.id, "undo")
    assert [r.text for r in undone] == ["Undone: Casa Verde back on the Spain trip."]
    undone = await agent.quick_action(user.id, "undo")
    assert [r.text for r in undone] == ["Undone: Gelato back as it was on the Spain trip."]
    undone = await agent.quick_action(user.id, "undo")
    assert [r.text for r in undone] == ["Undone: Hilltop Castle off the Spain trip."]
    stored = {b.draft.title: b.draft.at for b in await bookings(uow, user, trip)}
    assert stored == {"Gelato": time(16, 0), "Casa Verde": time(12, 30)}


async def test_a_cost_or_a_shared_trip_still_asks_first(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    paid = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Tapas tour"), Money.of("40", "EUR"), now=NOW
    )
    model = scripted(
        _call(
            "add_to_itinerary",
            plan("Dinner", cost="30", currency="EUR", place="12 Carrer Example"),
        ),
        _call("change_itinerary_entry", {"item": "tapas", "time": "20:00"}),
        _call("remove_from_itinerary", {"item": "tapas"}),
    )
    agent = _agent(uow, model, _ticking())
    for n, (ask, said) in enumerate(
        (
            ("Add Dinner (Sat 12 Dec), ", "dinner, 30 euros"),
            ("Change Tapas tour (Sat 12 Dec) to Tapas tour (Sat 12 Dec 20:00)", "tapas later"),
            ("Remove Tapas tour (Sat 12 Dec) from the Spain trip?", "drop the tapas"),
        ),
        start=1,
    ):
        replies = await agent.handle_text(user.id, said, f"tg:2:{n}")
        assert _asks(replies) and ask in replies[0].text, replies[0].text
        assert "Carrer" not in replies[0].text  # no street address
        await agent.resolve(user.id, replies[0].buttons[0][0].data.split(":")[1], False)
    assert await titles(uow, user, trip) == ["Tapas tour"]
    assert (await bookings(uow, user, trip))[0].id == paid.id


# --- ledger and itinerary, newest first -------------------------------------------------


async def test_undo_walks_back_through_ledger_and_itinerary_by_time(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await log_expense(uow, user, "Coffee")
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Castle"), None, now=NOW, record=chat(user)
    )
    await log_expense(uow, user, "Taxi")
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Beach"), None, now=NOW, record=chat(user)
    )

    assert (await undo(uow, user)).message() == "Undone: Beach off the Spain trip."
    taxi = await undo_cases.undo_latest(uow(), user.id)
    assert isinstance(taxi, tx_cases.UndoResult) and taxi.transaction.counterparty == "Taxi"
    assert await titles(uow, user, trip) == ["Castle"]
    assert (await undo(uow, user)).message() == "Undone: Castle off the Spain trip."
    coffee = await undo_cases.undo_latest(uow(), user.id)
    assert isinstance(coffee, tx_cases.UndoResult) and coffee.transaction.counterparty == "Coffee"
    with pytest.raises(NothingToUndo):
        await undo_cases.undo_latest(uow(), user.id)


async def test_tapping_undo_after_an_itinerary_change_leaves_the_ledger_alone(
    uow: UowFactory,
) -> None:
    """The bug: Undo after "take Casa Verde off" used to delete the latest expense."""
    user = await person(uow)
    trip = await spain(uow, user)
    await log_expense(uow, user, "Coffee")
    lunch = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Casa Verde"), None, now=NOW
    )
    await booking_cases.delete_booking(uow(), user.id, lunch.id, record=chat(user))
    await undo(uow, user)
    assert await titles(uow, user, trip) == ["Casa Verde"]
    assert await ledger_count(uow, user) == 1


# --- when it can't be put back ----------------------------------------------------------


async def test_what_cannot_be_put_back_is_skipped_and_said(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    batch = uuid4()
    castle = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Castle"), None, now=NOW, record=chat(user, batch)
    )
    beach = await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Beach"), None, now=NOW, record=chat(user, batch)
    )
    await booking_cases.edit_booking(
        uow(), user.id, beach.id, plan("Beach", at="09:00"), None, record=chat(user, batch)
    )
    await booking_cases.delete_booking(uow(), user.id, castle.id)  # later, from the web
    await booking_cases.delete_booking(uow(), user.id, beach.id)  # and this one too

    done = await undo(uow, user)
    assert done.message() == (
        "Nothing was undone. Couldn't undo Castle (it was removed since); "
        "Beach (it was removed since)."
    )
    # They're used up: Undo moves on rather than getting stuck on them.
    with pytest.raises(NothingToUndo):
        await undo_cases.undo_latest(uow(), user.id)


async def test_an_email_booking_saved_again_is_not_put_back_twice(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    castle = await booking_cases.add_manual(uow(), user.id, trip.id, plan("Castle"), None, now=NOW)
    await booking_cases.delete_booking(uow(), user.id, castle.id, record=chat(user))
    async with uow() as tx:  # something put it back by hand with the same id
        await tx.trips.insert_booking(castle)
        await tx.commit()
    done = await undo(uow, user)
    assert done.message() == "Nothing was undone. Couldn't undo Castle (it's back already)."
    assert await titles(uow, user, trip) == ["Castle"]


# --- whose changes ----------------------------------------------------------------------


async def test_another_users_undo_never_touches_mine(uow: UowFactory) -> None:
    mine = await person(uow, 4242)
    theirs = await person(uow, 5151)
    trip = await spain(uow, mine)
    await booking_cases.add_manual(
        uow(), mine.id, trip.id, plan("Castle"), None, now=NOW, record=chat(mine)
    )
    with pytest.raises(NothingToUndo):  # no itinerary change of theirs, nothing in their ledger
        await undo_cases.undo_latest(uow(), theirs.id)
    # Their own ledger entry is what their Undo takes back, though my change is newer.
    await log_expense(uow, theirs, "Their coffee")
    result = await undo_cases.undo_latest(uow(), theirs.id)
    assert isinstance(result, tx_cases.UndoResult)
    assert await titles(uow, mine, trip) == ["Castle"]
    # And a change of mine can't be reached through their id even by batch.
    async with uow() as tx:
        change = await tx.trips.latest_open_change(mine.id)
        assert change is not None and change.batch is not None
        assert await tx.trips.open_batch(theirs.id, change.batch) == []
        assert await tx.trips.latest_open_change(theirs.id) is None
    assert (await undo(uow, mine)).message() == "Undone: Castle off the Spain trip."


async def test_a_member_undoes_their_own_change_to_the_owners_trip(uow: UowFactory) -> None:
    owner = await person(uow, 4242)
    member = await person(uow, 4343)
    trip = await spain(uow, owner)
    async with uow() as tx:
        await tx.trips.add_member(owner.id, trip.id, member.id, None, NOW)
        await tx.commit()
    lunch = await booking_cases.add_manual(uow(), owner.id, trip.id, plan("Lunch"), None, now=NOW)
    await booking_cases.delete_booking(uow(), owner.id, lunch.id, record=chat(member))
    with pytest.raises(NothingToUndo):  # it was the member's change, not the owner's
        await undo_cases.undo_latest(uow(), owner.id)
    assert (await undo(uow, member)).message() == "Undone: Lunch back on the Spain trip."
    assert await titles(uow, owner, trip) == ["Lunch"]  # on the owner's itinerary

    await booking_cases.delete_booking(uow(), owner.id, lunch.id, record=chat(member))
    async with uow() as tx:  # the member leaves the trip before undoing
        await tx.trips.remove_member(owner.id, trip.id, member.id)
        await tx.commit()
    done = await undo(uow, member)
    assert (
        done.message() == "Nothing was undone. Couldn't undo Lunch (you're no longer on that trip)."
    )
    assert await titles(uow, owner, trip) == []


async def test_deleting_the_trip_or_the_user_takes_the_record_with_it(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Castle"), None, now=NOW, record=chat(user)
    )
    await trip_cases.delete_trip(uow(), user.id, trip.id)
    async with engine.connect() as db:
        assert (await db.execute(select(func.count()).select_from(trip_changes))).scalar() == 0
    with pytest.raises(NothingToUndo):
        await undo_cases.undo_latest(uow(), user.id)


def test_a_snapshot_keeps_the_whole_entry() -> None:
    from nexus.domain.bookings import BookingDraft

    draft = BookingDraft.from_dict(
        plan("Castle", at="10:00", ends_at="11:00", order=3, place_id="fakePlaceCastle01")
    )
    assert draft is not None
    booking = Booking(
        uuid4(), UserId(UUID(int=1)), uuid4(), None, draft, Money.of("12.50", "EUR"), uuid4(),
        datetime(2026, 9, 28, 4, 0, tzinfo=UTC),
    )  # fmt: skip
    assert from_snapshot(snapshot(booking)) == booking
    assert from_snapshot({"draft": {"kind": "nonsense"}}) is None
    assert {k.value for k in ChangeKind} == {"add", "remove", "change"}


# --- the agent's own tool and the button ------------------------------------------------


async def test_the_undo_tool_reverses_an_itinerary_change_too(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    tools = build_tools(lambda _: "")
    ctx = ToolContext(user, uow, NOW, RATES)
    await run_tool(
        tools["add_to_itinerary"], ctx, {"kind": "activity", "name": "Castle", "day": DAY}
    )
    undone = await run_tool(tools["undo_last_change"], ctx, {})
    assert undone.text == "Undone: Castle off the Spain trip." and undone.wrote
    assert await titles(uow, user, trip) == []


# --- the migration ----------------------------------------------------------------------


async def test_migration_0054_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Castle"), None, now=NOW, record=chat(user)
    )
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0053")
    async with engine.connect() as db:
        tables: set[str] = set(
            (await db.execute(text("SELECT tablename FROM pg_tables"))).scalars()
        )
    assert "trip_changes" not in tables and "trip_bookings" in tables
    await upgrade(empty_database_url)
    async with uow() as tx:  # the table is back, empty, and works
        assert await tx.trips.latest_open_change(user.id) is None
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Beach"), None, now=NOW, record=chat(user)
    )
    assert (await undo(uow, user)).message() == "Undone: Beach off the Spain trip."


# --- helpers for the chat turns ---------------------------------------------------------


def _ticking() -> Callable[[], datetime]:
    """A clock that moves a second on every look, so changes are told apart by time."""
    now = [NOW]

    def clock() -> datetime:
        now[0] += timedelta(seconds=1)
        return now[0]

    return clock


def _agent(uow: UowFactory, model: ScriptedModel, clock: Callable[[], datetime]) -> AgentService:
    skills = SkillLibrary.load()

    async def health() -> str:
        return "All systems fine."

    graph = AgentGraph(
        AgentDeps(
            uow=uow,
            tools=build_tools(skills.body),
            primary=model,
            fallbacks=(),
            skill_index=skills.index(),
            skill_tools=skills.tools(),
            health=health,
            clock=clock,
        )
    ).compile(InMemorySaver())
    return AgentService(graph, uow, None, clock)


def _adds(*names: str) -> AIMessage:
    """One model step that adds several plans at once."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "add_to_itinerary",
                "args": {"kind": "activity", "name": name, "day": DAY},
                "id": f"call-{uuid4()}",
            }
            for name in names
        ],
    )


async def _says(agent: AgentService, user: User, text: str, ref: str) -> list[Reply]:
    """What the user types, confirming whatever the agent asks first."""
    replies = await agent.handle_text(user.id, text, ref)
    while replies[0].buttons and replies[0].buttons[0][0].data.startswith("hitl:"):
        replies = await agent.resolve(user.id, replies[0].buttons[0][0].data.split(":")[1], True)
    return replies
