"""Splitting habits ("I always split dinners with Ann"): the use cases, tenant isolation, row-level
security, export and erasure, and the chat tools that apply them when an expense is logged.
Made-up names and amounts only."""

import asyncio
import json
import zipfile
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import CORE_TOOLS
from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import export
from nexus.application import split_habits as habit_cases
from nexus.application.ports import LedgerQuery
from nexus.application.splits import list_open_ious
from nexus.application.transactions import NewTransaction, list_ledger, log_transaction
from nexus.application.users import get_user
from nexus.domain.errors import NotFound
from nexus.domain.ledger import Direction, UserId
from nexus.domain.money import Money
from nexus.infra.db.migrations import alembic_config
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, only, tool_results
from tests.integration.test_row_security import acting, count

pytestmark = pytest.mark.integration

HALF = Decimal("0.5")


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def run(uow: UowFactory, user: UserId, tool: str, **args: Any) -> str:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW)
    return (await run_tool(build_tools(lambda _: "")[tool], ctx, args)).text


async def owed(uow: UowFactory, user: UserId) -> dict[str, Money]:
    totals: dict[str, Money] = {}
    for iou in await list_open_ious(uow(), user):
        name = iou.split.participant_name
        totals[name] = totals[name] + iou.outstanding if name in totals else iou.outstanding
    return totals


async def dinner(uow: UowFactory, user: UserId, amount: str = "60", **args: Any) -> str:
    return await run(
        uow,
        user,
        "log_expense",
        amount=amount,
        merchant="Din Tai Fung",
        best_guess_category="Dining Out",
        **args,
    )


# --- use cases ------------------------------------------------------------------------------


async def test_a_habit_is_saved_listed_and_forgotten(uow: UowFactory, alice: UserId) -> None:
    saved = await habit_cases.set_habit(uow(), alice, " Ann ", "Dining Out", HALF)
    assert (saved.person, saved.applies_to, saved.share) == ("Ann", "Dining Out", HALF)
    assert await habit_cases.list_habits(uow(), alice) == [saved]

    removed = await habit_cases.remove_habit(uow(), alice, "ann", "Dining Out")
    assert removed == [saved]
    assert await habit_cases.list_habits(uow(), alice) == []
    with pytest.raises(NotFound):
        await habit_cases.remove_habit(uow(), alice, "Ann")


async def test_saving_again_changes_the_share_instead_of_adding_another(
    uow: UowFactory, alice: UserId
) -> None:
    first = await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    again = await habit_cases.set_habit(uow(), alice, "ANN", "Dining Out", Decimal("0.4"))
    assert again.id == first.id and again.created_at == first.created_at
    [only_one] = await habit_cases.list_habits(uow(), alice)
    assert (only_one.person, only_one.share) == ("ANN", Decimal("0.4"))


async def test_a_habit_for_anything_is_one_per_person_too(uow: UowFactory, alice: UserId) -> None:
    """NULL is not distinct to a plain unique index; this one treats it as one value."""
    await habit_cases.set_habit(uow(), alice, "Ann", None, HALF)
    await habit_cases.set_habit(uow(), alice, "ann", None, Decimal("0.3"))
    await habit_cases.set_habit(uow(), alice, "Ann", "Groceries", HALF)  # another category
    habits = await habit_cases.list_habits(uow(), alice)
    assert sorted((h.applies_to or "", h.share) for h in habits) == [
        ("", Decimal("0.3")),
        ("Groceries", HALF),
    ]


async def test_forgetting_without_a_category_takes_every_habit_with_the_person(
    uow: UowFactory, alice: UserId
) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    await habit_cases.set_habit(uow(), alice, "Ann", None, HALF)
    await habit_cases.set_habit(uow(), alice, "Ben", None, HALF)
    assert len(await habit_cases.remove_habit(uow(), alice, "Ann")) == 2
    assert [h.person for h in await habit_cases.list_habits(uow(), alice)] == ["Ben"]


# --- other people's habits ------------------------------------------------------------------


async def test_another_users_habits_do_not_exist(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    mine = await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    assert await habit_cases.list_habits(uow(), bob) == []
    with pytest.raises(NotFound):
        await habit_cases.remove_habit(uow(), bob, "Ann", "Dining Out")
    async with uow() as tx:  # even by id
        assert await tx.ledger.delete_split_habits(bob, [mine.id]) == 0
        await tx.commit()
    assert await habit_cases.list_habits(uow(), alice) == [mine]

    # The same person is a different habit for each user.
    theirs = await habit_cases.set_habit(uow(), bob, "Ann", "Dining Out", Decimal("0.25"))
    assert theirs.id != mine.id
    assert [h.share for h in await habit_cases.list_habits(uow(), alice)] == [HALF]
    assert [h.share for h in await habit_cases.list_habits(uow(), bob)] == [Decimal("0.25")]


async def test_a_habit_never_splits_another_users_expense(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    await dinner(uow, bob)
    assert await owed(uow, bob) == {} and await owed(uow, alice) == {}


async def test_row_level_security_hides_and_protects_habits(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    mine = await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    his = await habit_cases.set_habit(uow(), bob, "Cat", None, HALF)
    async with acting(engine, alice) as db:
        assert await count(db, "SELECT count(*) FROM split_habits") == 1
    async with acting(engine, None) as db:  # a background job names nobody
        assert await count(db, "SELECT count(*) FROM split_habits") == 2

    insert = text(
        "INSERT INTO split_habits (id, user_id, person, share) VALUES (:id, :user, 'Dan', 0.5)"
    )
    async with acting(engine, bob) as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(insert, {"id": uuid4(), "user": alice})
    async with acting(engine, bob) as db:
        gone = await db.execute(text("DELETE FROM split_habits WHERE id = :h"), {"h": mine.id})
        assert gone.rowcount == 0
        changed = await db.execute(
            text("UPDATE split_habits SET share = 0.9 WHERE id = :h"), {"h": mine.id}
        )
        assert changed.rowcount == 0
    async with acting(engine, bob) as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(
                text("UPDATE split_habits SET user_id = :alice WHERE id = :h"),
                {"alice": alice, "h": his.id},
            )


async def test_the_database_keeps_shares_between_nothing_and_everything(
    admin_engine: AsyncEngine, uow: UowFactory, alice: UserId
) -> None:
    for bad in ("0", "1", "1.5"):
        with pytest.raises(DBAPIError, match="share_range"):
            async with admin_engine.begin() as db:
                await db.execute(
                    text(
                        "INSERT INTO split_habits (id, user_id, person, share) "
                        "VALUES (gen_random_uuid(), :u, 'Ann', :s)"
                    ),
                    {"u": alice, "s": Decimal(bad)},
                )


# --- export and erasure ---------------------------------------------------------------------


async def test_habits_are_exported_and_erased_with_their_owner(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    await habit_cases.set_habit(uow(), bob, "Cat", None, Decimal("0.4"))

    file = await export.build_export(
        uow, None, await get_user(uow(), alice), ledger_csv="", now=NOW
    )
    archive = zipfile.ZipFile(file)
    exported = json.loads(archive.read("split_habits.json"))["split_habits"]
    assert [(r["person"], r["applies_to"], r["share"]) for r in exported] == [
        ("Ann", "Dining Out", "0.5000")
    ]
    assert "Cat" not in archive.read("split_habits.json").decode()
    file.close()

    async with uow() as tx:
        await tx.user_data.erase(alice, chat_thread="tg:alice")
        await tx.commit()
    assert await habit_cases.list_habits(uow(), alice) == []
    assert [h.person for h in await habit_cases.list_habits(uow(), bob)] == ["Cat"]


# --- the chat tools -------------------------------------------------------------------------


async def test_set_split_habit_is_always_offered_and_saves_at_once(
    uow: UowFactory, alice: UserId
) -> None:
    assert "set_split_habit" in CORE_TOOLS
    assert build_tools(lambda _: "")["set_split_habit"].confirm is None

    model = scripted(
        call("set_split_habit", person="Ann", applies_to="dining out", share="50%"),
        say("Done, dinners with Ann are split half and half."),
    )
    reply = only(await build(uow, model).handle_text(alice, "i always split dinners with ann", "t"))
    assert reply.text.startswith("Done, dinners with Ann")
    [habit] = await habit_cases.list_habits(uow(), alice)
    assert (habit.person, habit.applies_to, habit.share) == ("Ann", "Dining Out", HALF)
    assert (
        "Saved split habit: Dining Out expenses with Ann: their share 50%" in tool_results(model)[0]
    )
    assert "already logged aren't changed" in tool_results(model)[0]


async def test_set_split_habit_reads_shares_and_refuses_unknown_categories(
    uow: UowFactory, alice: UserId
) -> None:
    saved = await run(uow, alice, "set_split_habit", person="Ben", share="1/3")
    assert "any expense with Ben: their share 33.33%" in saved
    bad = await run(uow, alice, "set_split_habit", person="Ann", applies_to="Dinners")
    assert bad.startswith("Error: unknown category 'Dinners'") and "Dining Out" in bad
    assert (await run(uow, alice, "set_split_habit", person="Ann", share="all")).startswith("Error")
    assert [h.person for h in await habit_cases.list_habits(uow(), alice)] == ["Ben"]


async def test_list_and_remove_split_habit(uow: UowFactory, alice: UserId) -> None:
    assert await run(uow, alice, "list_split_habits") == "No split habits saved."
    await run(uow, alice, "set_split_habit", person="Ann", applies_to="Dining Out")
    await run(uow, alice, "set_split_habit", person="Ann", applies_to="Groceries", share="0.4")
    listing = await run(uow, alice, "list_split_habits")
    assert "Dining Out expenses with Ann: their share 50%" in listing
    assert "Groceries expenses with Ann: their share 40%" in listing

    removed = await run(uow, alice, "remove_split_habit", person="ann", applies_to="Groceries")
    assert removed.startswith("Removed split habit: Groceries expenses with Ann")
    assert [h.applies_to for h in await habit_cases.list_habits(uow(), alice)] == ["Dining Out"]
    assert (await run(uow, alice, "remove_split_habit", person="Ben")).startswith("Error")


async def test_a_matching_habit_splits_the_expense_and_says_so(
    uow: UowFactory, alice: UserId
) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    result = await dinner(uow, alice)
    assert result.startswith("Logged: ")
    assert (
        "Split with Ann per their split habit: Ann owes 30.00 SGD. If this one wasn't shared, "
        "undo_last_change removes the split."
    ) in result
    assert await owed(uow, alice) == {"Ann": sgd("30")}


async def test_a_habit_with_several_people_splits_among_them(
    uow: UowFactory, alice: UserId
) -> None:
    third = Decimal("0.3333")
    await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", third)
    await habit_cases.set_habit(uow(), alice, "Ben", "Dining Out", third)
    result = await dinner(uow, alice, "100")
    assert (
        "Split with Ann and Ben per their split habit: Ann owes 33.33 SGD, Ben owes 33.33" in result
    )
    assert await owed(uow, alice) == {"Ann": sgd("33.33"), "Ben": sgd("33.33")}


async def test_a_habit_for_anything_applies_to_any_category(uow: UowFactory, alice: UserId) -> None:
    await habit_cases.set_habit(uow(), alice, "Ben", None, Decimal("0.25"))
    await run(uow, alice, "log_expense", amount="40", best_guess_category="Transport")
    assert await owed(uow, alice) == {"Ben": sgd("10")}


async def test_the_model_can_decline_the_habit_for_one_expense(
    uow: UowFactory, alice: UserId
) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    result = await dinner(uow, alice, "80", use_split_habit=False)
    assert result.startswith("Logged: ") and "split" not in result.lower()
    assert await owed(uow, alice) == {}
    page = await list_ledger(uow(), alice, LedgerQuery())
    assert [t.amount for t in page.items] == [sgd("80")]


async def test_an_expense_in_another_category_is_not_split(uow: UowFactory, alice: UserId) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", "Groceries", HALF)
    result = await dinner(uow, alice)
    assert result.startswith("Logged: ") and "split" not in result.lower()
    assert await owed(uow, alice) == {}


async def test_only_money_out_logged_as_an_expense_is_split(uow: UowFactory, alice: UserId) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", None, HALF)
    income = await log_transaction(
        uow(), alice, NewTransaction(Direction.IN, sgd("50"), NOW, counterparty="Ann")
    )
    assert await habit_cases.apply_to_expense(uow, alice, income, None) is None
    await run(uow, alice, "record_income", amount="50", kind="other", from_whom="Ben")
    assert await owed(uow, alice) == {}


async def test_habits_that_add_up_to_more_than_the_bill_leave_it_unsplit(
    uow: UowFactory, alice: UserId
) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", None, Decimal("0.6"))
    await habit_cases.set_habit(uow(), alice, "Ben", None, Decimal("0.6"))
    result = await dinner(uow, alice)
    assert result.startswith("Logged: ")
    assert "The split habit wasn't applied" in result and "the expense is logged unsplit" in result
    assert await owed(uow, alice) == {}


async def test_undo_removes_the_split_and_a_second_undo_removes_the_expense(
    uow: UowFactory, alice: UserId
) -> None:
    await habit_cases.set_habit(uow(), alice, "Ann", "Dining Out", HALF)
    await dinner(uow, alice)
    assert await owed(uow, alice) == {"Ann": sgd("30")}

    first = await run(uow, alice, "undo_last_change")
    assert first.startswith("Undid the last split") and "The expense itself is unchanged" in first
    assert await owed(uow, alice) == {}
    page = await list_ledger(uow(), alice, LedgerQuery(include_deleted=True))
    assert [t.amount for t in page.items if not t.is_deleted] == [sgd("60")]

    second = await run(uow, alice, "undo_last_change")
    assert second.startswith("Undid the last create")
    page = await list_ledger(uow(), alice, LedgerQuery(include_deleted=True))
    assert [t for t in page.items if not t.is_deleted] == []


async def test_the_whole_conversation_a_statement_then_an_expense_then_a_correction(
    uow: UowFactory, alice: UserId
) -> None:
    """Said once, applied by code, overridden for one night, undone for another."""
    model = scripted(
        call("set_split_habit", person="Ann", applies_to="Dining Out"),
        say("Got it."),
        call(
            "log_expense",
            amount="60",
            merchant="Din Tai Fung",
            best_guess_category="Dining Out",
        ),
        say("Logged 60, Ann owes 30."),
        call(
            "log_expense",
            amount="80",
            merchant="Paradise",
            best_guess_category="Dining Out",
            use_split_habit=False,
        ),
        say("Logged 80, all yours."),
    )
    agent = build(uow, model)
    await agent.handle_text(alice, "i always split dinners with ann", "t")
    reply = only(await agent.handle_text(alice, "dinner 60 at din tai fung", "t"))
    assert reply.text == "Logged 60, Ann owes 30."
    assert await owed(uow, alice) == {"Ann": sgd("30")}
    await agent.handle_text(alice, "my treat tonight, dinner 80 at paradise", "t")
    assert await owed(uow, alice) == {"Ann": sgd("30")}


# --- the migration --------------------------------------------------------------------------


async def test_migration_0057_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, admin_engine: AsyncEngine
) -> None:
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False

    async def has_table() -> bool:
        async with admin_engine.connect() as db:
            return bool(
                (await db.execute(text("SELECT to_regclass('public.split_habits')"))).scalar()
            )

    assert await has_table()
    await asyncio.to_thread(command.downgrade, config, "0056")
    assert not await has_table()
    await upgrade(empty_database_url)
    assert await has_table()
