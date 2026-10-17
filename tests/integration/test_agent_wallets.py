"""The chat side of wallets: log_move and the wallet tools, driven by a scripted model
through the real graph, confirmations and database. Made-up names and amounts only."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import CORE_TOOLS
from nexus.agent.snapshot import money_snapshot
from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import wallets as wallet_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import (
    NewTransaction,
    delete_transaction,
    get_transaction,
    list_ledger,
    log_transaction,
)
from nexus.application.users import get_user
from nexus.application.wallets import add_wallet, list_wallets, log_move
from nexus.domain.ledger import Direction, UserId, Wallet
from nexus.domain.money import Money
from nexus.infra.db.tables import capability_gaps
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, ledger, only, tool_results
from tests.integration.test_tool_routing import load

pytestmark = pytest.mark.integration


def tool_call(tool: str, args: dict[str, Any]) -> AIMessage:
    """``call`` for a tool with an argument called name."""
    return AIMessage(content="", tool_calls=[{"name": tool, "args": args, "id": f"call-{tool}"}])


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def wallets_of(uow: UowFactory, user: UserId) -> dict[str, Wallet]:
    return {w.name: w for w in await list_wallets(uow(), user)}


async def with_wallets(uow: UowFactory, user: UserId) -> dict[str, Wallet]:
    await add_wallet(uow(), user, "IBKR", "investment", ["interactive brokers"])
    await add_wallet(uow(), user, "Savings", "savings")
    await add_wallet(uow(), user, "Card", "card")
    return await wallets_of(uow, user)


async def move(
    uow: UowFactory,
    user: UserId,
    amount: str,
    origin: Wallet,
    target: Wallet,
    when: Any = NOW,
) -> None:
    await log_move(
        uow(),
        user,
        amount=sgd(amount),
        from_wallet_id=origin.id,
        to_wallet_id=target.id,
        occurred_at=when,
    )


async def run(uow: UowFactory, user: UserId, tool: str, args: dict[str, Any]) -> str:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW)
    return (await run_tool(build_tools(lambda _: "")[tool], ctx, args)).text


# --- log_move ------------------------------------------------------------------------


async def test_a_move_waits_for_confirmation_then_is_logged(uow: UowFactory, alice: UserId) -> None:
    wallets = await with_wallets(uow, alice)
    model = scripted(call("log_move", amount="800", to_wallet="ibkr"), say("Logged 800 to IBKR ✅"))
    agent = build(uow, model)

    ask = only(await agent.handle_text(alice, "moved 800 to my IBKR", "tg:1:1"))
    assert ask.text == (
        "Log a move of 800.00 SGD from Spending to IBKR? It won't count as spending."
    )
    assert await ledger(uow, alice) == []  # nothing until confirmed

    done = only(await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True))
    assert done.text == "Logged 800 to IBKR ✅"
    assert [b.data for row in done.buttons for b in row] == ["act:undo"]
    assert await ledger(uow, alice) == [("move", Decimal("800"))]
    [tx] = (await list_ledger(uow(), alice, LedgerQuery())).items
    assert (tx.from_wallet_id, tx.to_wallet_id) == (
        wallets["Spending"].id,
        wallets["IBKR"].id,
    )
    assert tx.category_id is None
    result = tool_results(model)[0]
    assert result.startswith("Logged a move (not spending or income): ")
    assert "800.00 SGD → IBKR (move)" in result and "-800" not in result

    # Declining changes nothing.
    other = build(uow, scripted(call("log_move", amount="5", to_wallet="Savings")))
    ask = only(await other.handle_text(alice, "put 5 in savings", "tg:1:2"))
    declined = only(await other.resolve(alice, ask.buttons[0][1].data.split(":")[1], False))
    assert declined.text == "Okay, cancelled. Nothing was changed."
    assert await ledger(uow, alice) == [("move", Decimal("800"))]


async def test_a_move_is_not_spending_and_can_be_undone(uow: UowFactory, alice: UserId) -> None:
    await with_wallets(uow, alice)
    model = scripted(
        call("log_move", amount="800", to_wallet="IBKR"),
        say("Done."),
        call("spending_summary"),
        say("Nothing."),
        call("undo_last_change"),
        say("Undone."),
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "moved 800 to my IBKR", "tg:1:1"))
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)

    await agent.handle_text(alice, "how much did i spend?", "tg:1:2")
    assert tool_results(model)[-1] == "Nothing recorded from 2026-09-01 to 2026-09-28."
    assert await ledger(uow, alice) == [("move", Decimal("800"))]

    await agent.handle_text(alice, "undo", "tg:1:3")
    assert "Undid the last create: " in tool_results(model)[-1]
    assert "800.00 SGD → IBKR (move)" in tool_results(model)[-1]
    assert await ledger(uow, alice) == []


async def test_an_unknown_wallet_is_asked_about_not_invented(
    uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    model = scripted(
        call("log_move", amount="800", to_wallet="Tiger"),
        say("I don't have a Tiger wallet. Want me to add it as an investment wallet?"),
    )
    reply = only(await build(uow, model).handle_text(alice, "moved 800 to my Tiger", "tg:1:1"))
    assert reply.buttons == []  # no confirmation: there was nothing to confirm
    assert reply.text.endswith("add it as an investment wallet?")
    result = tool_results(model)[0]
    assert result.startswith("Error: there's no wallet called 'Tiger'.")
    assert "Spending, Card (card), IBKR (investment), Savings (savings)" in result
    assert "don't add one unless they say yes" in result
    assert await ledger(uow, alice) == []
    assert set(await wallets_of(uow, alice)) == {"Spending", "IBKR", "Savings", "Card"}


async def test_an_unknown_origin_is_asked_about_too(uow: UowFactory, alice: UserId) -> None:
    await with_wallets(uow, alice)
    model = scripted(
        call("log_move", amount="50", from_wallet="Tiger", to_wallet="IBKR"), say("Which one?")
    )
    await build(uow, model).handle_text(alice, "moved 50 from tiger to ibkr", "tg:1:1")
    assert "no wallet called 'Tiger'" in tool_results(model)[0]
    assert await ledger(uow, alice) == []


async def test_wallets_are_found_by_name_in_any_case_or_by_match_word(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    model = scripted(
        call("log_move", amount="10", to_wallet="my ibkr"),
        say("a"),
        call("log_move", amount="20", to_wallet="Interactive Brokers"),
        say("b"),
    )
    agent = build(uow, model)
    for n, expected in enumerate(("10.00", "20.00")):
        ask = only(await agent.handle_text(alice, "move", f"tg:1:{n}"))
        assert ask.text == (
            f"Log a move of {expected} SGD from Spending to IBKR? It won't count as spending."
        )
        await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    page = await list_ledger(uow(), alice, LedgerQuery())
    assert {tx.to_wallet_id for tx in page.items} == {wallets["IBKR"].id}


async def test_a_move_between_wallets_in_two_currencies(uow: UowFactory, alice: UserId) -> None:
    wallets = await with_wallets(uow, alice)
    model = scripted(
        call(
            "log_move",
            amount="1000",
            from_wallet="savings",
            to_wallet="IBKR",
            received_amount="740",
            received_currency="USD",
            date="2026-09-20",
            note="top up",
        ),
        say("Logged."),
        call("log_move", amount="300", from_wallet="Savings", to_wallet="Spending"),
        say("Logged."),
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "moved 1000 from savings to ibkr", "tg:1:1"))
    assert ask.text == (
        "Log a move of 1000.00 SGD from Savings to IBKR (740.00 USD arrives) on 20 Sep? "
        "It won't count as spending or income."
    )
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    ask = only(await agent.handle_text(alice, "took 300 out of savings", "tg:1:2"))
    assert ask.text == (
        "Log a move of 300.00 SGD from Savings to Spending? It won't count as income."
    )
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)

    by_amount = {
        tx.amount.amount: tx for tx in (await list_ledger(uow(), alice, LedgerQuery())).items
    }
    first, second = by_amount[Decimal("1000")], by_amount[Decimal("300")]
    assert first.received_amount == Money.of("740", "USD") and first.notes == "top up"
    assert (first.from_wallet_id, first.to_wallet_id) == (
        wallets["Savings"].id,
        wallets["IBKR"].id,
    )
    assert (second.from_wallet_id, second.to_wallet_id) == (
        wallets["Savings"].id,
        wallets["Spending"].id,
    )
    assert second.received_amount is None


async def test_a_move_to_the_same_wallet_or_a_bad_amount_is_refused(
    uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    assert (
        await run(uow, alice, "log_move", {"amount": "5", "to_wallet": "Spending"})
    ) == "Error: a move needs two different wallets"
    assert (await run(uow, alice, "log_move", {"amount": "lots", "to_wallet": "IBKR"})).startswith(
        "Error: "
    )
    assert (await run(uow, alice, "log_move", {"amount": "0", "to_wallet": "IBKR"})).startswith(
        "Error: "
    )
    assert await ledger(uow, alice) == []


async def test_log_move_is_in_the_core_tools_and_the_rest_arrive_with_the_skill(
    uow: UowFactory, alice: UserId
) -> None:
    assert "log_move" in CORE_TOOLS
    model = scripted(say("hi"), load("wallets"), say("Which wallet?"))
    agent = build(uow, model)
    await agent.handle_text(alice, "hello", "tg:1:1")
    assert "log_move" in model.bound[0] and "add_wallet" not in model.bound[0]
    await agent.handle_text(alice, "i want to add a wallet", "tg:1:2")
    offered = model.bound[-1]
    assert {
        "add_wallet",
        "update_wallet",
        "delete_wallet",
        "list_wallets",
        "mark_as_move",
    } <= offered
    system = str(model.seen[0][0].content)
    assert "log_move" in system and "card wallet" in system and "never invent one" in system
    assert "- wallets:" in system


# --- what the kernel refuses and lets through ----------------------------------------


async def test_telling_it_a_move_happened_reaches_the_model_but_asking_it_to_move_money_does_not(
    engine: AsyncEngine, uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    model = scripted(
        call("log_move", amount="800", to_wallet="IBKR"),
        call("log_move", amount="500", to_wallet="Savings"),
    )
    agent = build(uow, model)
    for n, text in enumerate(("I moved 800 to IBKR", "just put 500 into savings")):
        ask = only(await agent.handle_text(alice, text, f"tg:1:{n}"))
        assert ask.text.startswith("Log a move of")

    for n, text in enumerate(
        ("transfer 500 to savings for me", "move 500 to savings", "I want to move 500 to savings")
    ):
        refused = only(await agent.handle_text(alice, text, f"tg:2:{n}"))
        assert refused.text.startswith("I can't send or transfer money")
        assert "I moved 500 to savings" in refused.text  # and how to have it recorded
    assert len(model.seen) == 2  # the refusals never reached the model
    async with engine.connect() as conn:
        count = (await conn.execute(select(func.count()).select_from(capability_gaps))).scalar()
    assert count == 3
    assert await ledger(uow, alice) == []


# --- mark_as_move ------------------------------------------------------------------------


async def test_an_expense_can_be_turned_into_a_move(uow: UowFactory, alice: UserId) -> None:
    wallets = await with_wallets(uow, alice)
    tx = await log_transaction(
        uow(),
        alice,
        NewTransaction(Direction.OUT, sgd("800"), NOW, counterparty="IBKR"),
    )
    model = scripted(call("mark_as_move", transaction_id=str(tx.id), wallet="IBKR"), say("Fixed."))
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "that 800 to ibkr was a move", "tg:1:1"))
    assert ask.text == (
        "Turn 2026-09-28 · -800.00 SGD · IBKR · Other into a move from Spending to IBKR? "
        "It will stop counting as spending, and it loses its category."
    )
    assert (await get_transaction(uow(), alice, tx.id)).direction is Direction.OUT  # not yet

    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    moved = await get_transaction(uow(), alice, tx.id)
    assert moved.direction is Direction.MOVE and moved.category_id is None
    assert (moved.from_wallet_id, moved.to_wallet_id) == (
        wallets["Spending"].id,
        wallets["IBKR"].id,
    )
    assert tool_results(model)[0].startswith("Now a move: 2026-09-28 · 800.00 SGD → IBKR (move)")


async def test_money_in_can_be_turned_into_a_withdrawal_move(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.IN, sgd("300"), NOW, counterparty="Savings")
    )
    model = scripted(
        call("mark_as_move", transaction_id=str(tx.id), wallet="Savings"), say("Fixed.")
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "that was from my savings", "tg:1:1"))
    assert ask.text == (
        "Turn 2026-09-28 · +300.00 SGD · Savings · Income into a move from Savings to "
        "Spending? It will stop counting as income, and it loses its category."
    )
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    moved = await get_transaction(uow(), alice, tx.id)
    assert (moved.from_wallet_id, moved.to_wallet_id) == (
        wallets["Savings"].id,
        wallets["Spending"].id,
    )
    assert "300.00 SGD Savings → Spending (move)" in tool_results(model)[0]


async def test_mark_as_move_explains_what_it_cant_do(uow: UowFactory, alice: UserId) -> None:
    await with_wallets(uow, alice)
    tx = await log_transaction(uow(), alice, NewTransaction(Direction.OUT, sgd("50"), NOW))
    other = await log_transaction(uow(), alice, NewTransaction(Direction.OUT, sgd("60"), NOW))
    unknown = await run(
        uow, alice, "mark_as_move", {"transaction_id": str(tx.id), "wallet": "Tiger"}
    )
    assert "no wallet called 'Tiger'" in unknown
    spending = await run(
        uow, alice, "mark_as_move", {"transaction_id": str(tx.id), "wallet": "Spending"}
    )
    assert spending.startswith("Error: pick a wallet other than Spending")
    assert (
        await run(uow, alice, "mark_as_move", {"transaction_id": str(other.id), "wallet": "Card"})
    ).startswith("Now a move")
    again = await run(
        uow, alice, "mark_as_move", {"transaction_id": str(other.id), "wallet": "Card"}
    )
    assert again == "Error: this is already a move"
    assert (await get_transaction(uow(), alice, tx.id)).direction is Direction.OUT


# --- wallet management -------------------------------------------------------------------


async def test_wallets_can_be_listed_added_and_changed(uow: UowFactory, alice: UserId) -> None:
    model = scripted(
        call("list_wallets"),
        tool_call(
            "add_wallet", dict(name="Tiger", kind="investment", match_words=["tiger brokers"])
        ),
        tool_call("add_wallet", dict(name="tiger", kind="savings")),
        tool_call("add_wallet", dict(name="Rainy day", kind="savings")),
        call("update_wallet", wallet="Rainy day", new_name="Tiger"),
        call("update_wallet", wallet="rainy day", new_name="Emergency fund", kind="other"),
        say("ok"),
        call("update_wallet", wallet="Emergency fund", match_words=[]),
        call("update_wallet", wallet="Emergency fund"),
        call("update_wallet", wallet="Spending", kind="savings"),
        tool_call("add_wallet", dict(name="X", kind="spending")),
        call("list_wallets"),
        say("ok"),
    )
    agent = build(uow, model)
    await agent.handle_text(alice, "wallets", "tg:1:1")
    await agent.handle_text(alice, "more wallets", "tg:1:2")
    results = tool_results(model)
    assert results[0] == "Spending (the main account the budget watches)"
    assert results[1] == "Added the wallet Tiger (investment)."
    assert results[2] == "There's already a wallet called Tiger."
    assert results[3] == "Added the wallet Rainy day (savings)."
    assert results[4] == "Error: there's already a wallet called Tiger"
    assert results[5] == "Updated Rainy day: renamed to Emergency fund, its kind is now other."
    assert results[6] == "Updated Emergency fund: nothing to change."
    assert results[7].startswith("Error: say what to change")
    assert results[8].startswith("Error: the Spending wallet can't change kind")
    assert results[9].startswith("Error: invalid arguments for add_wallet")
    assert results[10] == (
        "Spending (the main account the budget watches)\n"
        "Emergency fund (other)\n"
        "Tiger (investment; match words: tiger brokers)"
    )


async def test_deleting_a_wallet_says_how_many_moves_are_repointed_and_removed(
    uow: UowFactory, alice: UserId
) -> None:
    w = await with_wallets(uow, alice)
    spend, ibkr, savings = w["Spending"], w["IBKR"], w["Savings"]
    await move(uow, alice, "800", spend, ibkr)
    await move(uow, alice, "100", spend, ibkr)
    await move(uow, alice, "50", ibkr, savings)
    await move(uow, alice, "60", savings, ibkr)
    await move(uow, alice, "70", savings, ibkr)
    [gone] = [
        tx
        for tx in (await list_ledger(uow(), alice, LedgerQuery())).items
        if tx.amount.amount == Decimal("70")
    ]
    await delete_transaction(uow(), alice, gone.id)  # a deleted move still names the wallet

    # What would happen is worked out without doing it.
    plan = await wallet_cases.preview_delete_wallet(uow(), alice, ibkr.id, savings.id)
    assert (plan.moved, plan.removed, plan.into) == (2, 3, savings)
    assert len(await ledger(uow, alice)) == 4

    model = scripted(
        call("delete_wallet", wallet="IBKR"),
        say("Which wallet should its moves point at?"),
        call("delete_wallet", wallet="ibkr", move_to="savings"),
        say("Deleted."),
    )
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "delete my ibkr wallet", "tg:1:1"))
    assert reply.buttons == []  # it has moves and nowhere to point them: ask, don't confirm
    result = tool_results(model)[0]
    assert result.startswith("Error: IBKR has moves, so they need another wallet to point at")
    assert "Spending, Card (card), Savings (savings)" in result

    ask = only(await agent.handle_text(alice, "into savings", "tg:1:2"))
    assert ask.text == (
        "Delete the wallet IBKR? 2 moves will point at Savings instead, and 3 moves between "
        "the two will be removed, since both ends would be Savings. This can't be undone."
    )
    assert "IBKR" in await wallets_of(uow, alice)  # nothing until confirmed

    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    assert tool_results(model)[-1] == (
        "Deleted the wallet IBKR. 2 moves now point at Savings; 3 moves between the two removed."
    )
    assert "IBKR" not in await wallets_of(uow, alice)
    left = (await list_ledger(uow(), alice, LedgerQuery(include_deleted=True))).items
    assert sorted((tx.amount.amount, tx.from_wallet_id, tx.to_wallet_id) for tx in left) == [
        (Decimal("100"), spend.id, savings.id),
        (Decimal("800"), spend.id, savings.id),
    ]


async def test_deleting_a_wallet_with_one_move_and_with_none(
    uow: UowFactory, alice: UserId
) -> None:
    w = await with_wallets(uow, alice)
    await move(uow, alice, "40", w["Spending"], w["Card"])
    model = scripted(
        call("delete_wallet", wallet="Card", move_to="Savings"),
        say("Deleted."),
        call("delete_wallet", wallet="IBKR"),
        say("Deleted."),
        call("delete_wallet", wallet="Spending", move_to="Savings"),
        call("delete_wallet", wallet="Savings", move_to="Savings"),
        call("delete_wallet", wallet="Savings", move_to="Tiger"),
        say("No."),
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "delete card", "tg:1:1"))
    assert ask.text == (
        "Delete the wallet Card? 1 move will point at Savings instead. This can't be undone."
    )
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    assert tool_results(model)[-1] == "Deleted the wallet Card. 1 move now points at Savings."

    ask = only(await agent.handle_text(alice, "delete ibkr", "tg:1:2"))
    assert ask.text == "Delete the wallet IBKR? It has no moves. This can't be undone."
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    assert tool_results(model)[-1] == "Deleted the wallet IBKR."
    assert set(await wallets_of(uow, alice)) == {"Spending", "Savings"}

    refused = only(await agent.handle_text(alice, "delete spending", "tg:1:3"))
    assert refused.text == "No."
    results = [str(m.content) for m in model.seen[-1] if m.type == "tool"][-3:]
    assert results[0].startswith("Error: the Spending wallet can't be deleted")
    assert results[1].startswith("Error: pick a different wallet")
    assert "no wallet called 'Tiger'" in results[2]


# --- finding and asking about moves ---------------------------------------------------------


async def test_moves_show_where_they_went_when_found(uow: UowFactory, alice: UserId) -> None:
    w = await with_wallets(uow, alice)
    await log_transaction(uow(), alice, NewTransaction(Direction.OUT, sgd("12"), NOW))
    await move(uow, alice, "800", w["Spending"], w["IBKR"])
    await move(uow, alice, "300", w["Savings"], w["Spending"])
    text = await run(uow, alice, "find_transactions", {"direction": "move"})
    lines = text.splitlines()
    assert len(lines) == 2
    assert any(line.startswith("2026-09-28 · 800.00 SGD → IBKR (move) [id ") for line in lines)
    assert any("· 300.00 SGD Savings → Spending (move) [id " in line for line in lines)
    assert "-800" not in text and "+300" not in text
    everything = await run(uow, alice, "find_transactions", {})
    assert "-12.00 SGD" in everything and "800.00 SGD → IBKR (move)" in everything


async def test_query_ledger_answers_how_much_went_into_a_wallet(
    uow: UowFactory, alice: UserId
) -> None:
    w = await with_wallets(uow, alice)
    await log_transaction(uow(), alice, NewTransaction(Direction.OUT, sgd("12"), NOW))
    await move(uow, alice, "800", w["Spending"], w["IBKR"], NOW - timedelta(days=100))
    await move(uow, alice, "200", w["Spending"], w["IBKR"])
    await move(uow, alice, "100", w["IBKR"], w["Spending"])
    await move(uow, alice, "500", w["Spending"], w["Savings"])
    year = {"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28"}

    into = await run(uow, alice, "query_ledger", {**year, "wallet": "ibkr"})
    assert "Moved, in SGD, 2026-01-01 to 2026-09-28: 1000.00 SGD over 2 transactions" in into
    assert "not spending or income" in into and "800.00 SGD → IBKR (move)" in into
    out_of = await run(
        uow, alice, "query_ledger", {**year, "wallet": "IBKR", "wallet_side": "out_of"}
    )
    assert "100.00 SGD over 1 transaction" in out_of and "100.00 SGD IBKR → Spending" in out_of
    either = await run(
        uow, alice, "query_ledger", {**year, "wallet": "IBKR", "wallet_side": "either"}
    )
    assert "1100.00 SGD over 3 transactions" in either
    allmoves = await run(uow, alice, "query_ledger", year)
    assert "1600.00 SGD over 4 transactions" in allmoves
    # Spending is only the expense; no move is in it.
    spent = await run(uow, alice, "query_ledger", {"start_date": "2026-01-01"})
    assert spent.startswith("Spent, in SGD, 2026-01-01 to 2026-09-28: 12.00 SGD over 1 transaction")

    unknown = await run(uow, alice, "query_ledger", {**year, "wallet": "Tiger"})
    assert "no wallet called 'Tiger'" in unknown
    wrong = await run(uow, alice, "query_ledger", {"wallet": "IBKR"})
    assert wrong == "Error: a wallet filter is for moves; ask about moves"


# --- the snapshot ------------------------------------------------------------------------------


async def test_the_snapshot_lists_wallets_and_what_was_put_away(
    uow: UowFactory, alice: UserId
) -> None:
    user = await get_user(uow(), alice)
    ctx = ToolContext(user, uow, NOW)
    plain = await money_snapshot(ctx)
    assert "Put away" not in plain and "Wallets besides" not in plain  # only Spending

    w = await with_wallets(uow, alice)
    await log_transaction(
        uow(), alice, NewTransaction(Direction.IN, sgd("5000"), NOW, counterparty="Acme")
    )
    await move(uow, alice, "800", w["Spending"], w["IBKR"])
    await move(uow, alice, "1240", w["Spending"], w["Card"])  # a card bill isn't put away
    text = await money_snapshot(ctx)
    assert (
        "Wallets besides Spending: Card (card), IBKR (investment, also interactive brokers), "
        "Savings (savings). Put away this month: 800.00 SGD (16% of income)."
    ) in text
    assert "spent 0.00 SGD in 0 transactions, received 5000.00 SGD" in text

    await move(uow, alice, "300", w["Savings"], w["Spending"])
    assert "Put away this month: 500.00 SGD (10% of income)." in await money_snapshot(ctx)


async def test_the_system_prompt_tells_a_move_from_an_expense(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("hi"))
    await build(uow, model).handle_text(alice, "hello", "tg:1:1")
    system = str(model.seen[0][0].content)
    for phrase in (
        "never spending or income",
        "paying a credit card bill from Spending",
        "transferred 50 to Alex for dinner",
        "dividend or interest paid out",
        "never invent one",
        "instruction you can't carry out",
    ):
        assert phrase in system, phrase
