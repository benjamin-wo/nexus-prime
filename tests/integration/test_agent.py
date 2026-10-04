"""Agent trajectories: a scripted model drives the real graph, tools and database."""

from datetime import timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import BaseMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import MAX_STEPS, AgentDeps, AgentGraph
from nexus.agent.holdings_reader import HoldingsReader
from nexus.agent.receipts import ReceiptDraft, ReceiptReader
from nexus.agent.service import AgentService, Reply
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application import bills as bill_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application.category_rules import list_rules
from nexus.application.departments import Departments
from nexus.application.ports import LedgerQuery, ReceiptStore
from nexus.application.splits import list_open_ious, split_bill
from nexus.application.transactions import NewTransaction, list_ledger, log_transaction
from nexus.application.users import get_user
from nexus.domain.ledger import Direction, ShareRequest, Source, UserId
from nexus.domain.money import Money
from nexus.domain.planning import Cadence
from nexus.infra.db.tables import capability_gaps
from tests.fakes import NOW, FakeReceipts, ScriptedModel, call, say, scripted
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration


def build(
    uow: UowFactory,
    model: ScriptedModel,
    receipts: ReceiptReader | None = None,
    archive: ReceiptStore | None = None,
    holdings: HoldingsReader | None = None,
    departments: Departments | None = None,
) -> AgentService:
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
            clock=lambda: NOW,
            departments=departments,
        )
    ).compile(InMemorySaver())
    return AgentService(graph, uow, receipts, lambda: NOW, archive, holdings=holdings)


async def ledger(uow: UowFactory, user: UserId, **query: object) -> list[tuple[str, Decimal]]:
    page = await list_ledger(uow(), user, LedgerQuery(**query))  # type: ignore[arg-type]
    return [(t.direction.value, t.amount.amount) for t in page.items]


def tool_results(model: ScriptedModel) -> list[str]:
    last: list[BaseMessage] = model.seen[-1]
    return [str(m.content) for m in last if isinstance(m, ToolMessage)]


def only(replies: list[Reply]) -> Reply:
    assert len(replies) == 1
    return replies[0]


async def test_logs_an_expense_and_offers_undo(uow: UowFactory, alice: UserId) -> None:
    model = scripted(
        call("log_expense", amount="5.50", merchant="Starbucks", category="Dining Out"),
        say("Logged 5.50 at Starbucks."),
    )
    reply = only(await build(uow, model).handle_text(alice, "starbucks 5.50", "tg:1:1"))
    assert reply.text == "Logged 5.50 at Starbucks."
    assert [b.data for row in reply.buttons for b in row] == ["act:undo"]
    assert await ledger(uow, alice) == [("out", Decimal("5.5"))]
    assert "Logged: 2026-09-28 · -5.50 SGD · Starbucks · Dining Out" in tool_results(model)[0]


async def test_model_cannot_act_for_another_user(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    model = scripted(call("log_expense", amount="99", user_id=str(bob)), say("Done."))
    await build(uow, model).handle_text(alice, "log 99 for bob", "tg:1:1")
    assert await ledger(uow, alice) == [("out", Decimal("99"))]
    assert await ledger(uow, bob) == []


async def test_model_cannot_call_hidden_tools(uow: UowFactory, alice: UserId) -> None:
    model = scripted(
        call("log_receipt_expense", amount="10", external_id="x"), say("I couldn't do that.")
    )
    await build(uow, model).handle_text(alice, "log a receipt", "tg:1:1")
    assert await ledger(uow, alice) == []
    assert "no tool called 'log_receipt_expense'" in tool_results(model)[0]


async def test_bad_arguments_come_back_as_errors(uow: UowFactory, alice: UserId) -> None:
    model = scripted(
        call("log_expense", amount="lots"),
        call("log_expense", amount="5", category="Nonsense"),
        say("Which category?"),
    )
    reply = only(await build(uow, model).handle_text(alice, "coffee", "tg:1:1"))
    assert reply.text == "Which category?" and reply.buttons == []
    results = tool_results(model)
    assert results[0].startswith("Error: invalid amount")
    assert "unknown category 'Nonsense'" in results[1]
    assert await ledger(uow, alice) == []


async def test_delete_waits_for_confirmation(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("12", "SGD"), NOW, counterparty="Grab")
    )
    model = scripted(call("delete_transaction", transaction_id=str(tx.id)), say("Deleted it."))
    agent = build(uow, model)

    reply = only(await agent.handle_text(alice, "delete the grab ride", "tg:1:1"))
    assert reply.text == "Delete 2026-09-28 · -12.00 SGD · Grab · Other?"
    confirm, cancel = reply.buttons[0]
    assert confirm.label == "Confirm" and cancel.label == "Cancel"
    assert await ledger(uow, alice) == [("out", Decimal("12"))]  # nothing yet

    stale = confirm.data.split(":")[1]
    assert (await agent.resolve(alice, "not-" + stale, True))[0].text.startswith(
        "That confirmation"
    )

    done = only(await agent.resolve(alice, stale, True))
    assert done.text == "Deleted it."
    assert await ledger(uow, alice) == []
    # The same button can't be pressed twice.
    assert (await agent.resolve(alice, stale, True))[0].text.startswith("That confirmation")


async def test_declining_changes_nothing(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("12", "SGD"), NOW)
    )
    agent = build(uow, scripted(call("delete_transaction", transaction_id=str(tx.id))))
    reply = only(await agent.handle_text(alice, "delete it", "tg:1:1"))
    pending = reply.buttons[0][1].data.split(":")[1]
    declined = only(await agent.resolve(alice, pending, False))
    assert declined.text == "Okay, cancelled. Nothing was changed."
    assert await ledger(uow, alice) == [("out", Decimal("12"))]


async def test_a_new_message_declines_a_waiting_confirmation(
    uow: UowFactory, alice: UserId
) -> None:
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("12", "SGD"), NOW)
    )
    model = scripted(call("delete_transaction", transaction_id=str(tx.id)), say("Sure, what?"))
    agent = build(uow, model)
    await agent.handle_text(alice, "delete it", "tg:1:1")
    reply = only(await agent.handle_text(alice, "actually wait", "tg:1:2"))
    assert reply.text == "Sure, what?"
    assert await ledger(uow, alice) == [("out", Decimal("12"))]

    agent2 = build(uow, scripted(call("delete_transaction", transaction_id=str(tx.id))))
    await agent2.handle_text(alice, "delete it", "tg:1:3")
    assert only(await agent2.handle_text(alice, "cancel", "tg:1:4")).text.startswith("Cancelled")
    assert await ledger(uow, alice) == [("out", Decimal("12"))]


async def test_split_confirmation_shows_shares(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(
        uow(),
        alice,
        NewTransaction(Direction.OUT, Money.of("90", "SGD"), NOW, counterparty="Dinner"),
    )
    model = scripted(
        call(
            "split_bill",
            transaction_id=str(tx.id),
            participants=[{"name": "Ann"}, {"name": "Ben"}],
        ),
        say("Split done."),
    )
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "split dinner with ann and ben", "tg:1:1"))
    assert reply.text == (
        "Split 2026-09-28 · -90.00 SGD · Dinner · Other: Ann owes 30.00 SGD, Ben owes 30.00 SGD; "
        "your share 30.00 SGD?"
    )
    await agent.resolve(alice, reply.buttons[0][0].data.split(":")[1], True)
    assert len(await list_open_ious(uow(), alice)) == 2


async def test_repayment_settles_iou_without_the_model(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("60", "SGD"), NOW)
    )
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann")])  # Ann owes 30
    model = scripted()  # any model call fails the test
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "Ann paid me back 20", "tg:1:9"))
    assert reply.text == "Recorded 20.00 SGD from Ann. Ann still owes 10.00 SGD."
    assert reply.buttons[0][0].data == "act:undo"
    # A redelivered message is not recorded twice.
    again = only(await agent.handle_text(alice, "Ann paid me back 20", "tg:1:9"))
    assert again.text == "That was already recorded."
    assert model.seen == []


async def test_salary_is_recorded_deterministically(uow: UowFactory, alice: UserId) -> None:
    reply = only(await build(uow, scripted()).handle_text(alice, "salary 4,200", "tg:1:1"))
    assert reply.text == "Recorded 4200.00 SGD salary."
    page = await list_ledger(uow(), alice, LedgerQuery(direction=Direction.IN))
    assert page.items[0].notes == "Salary"
    assert page.items[0].amount == Money.of("4200", "SGD")


async def test_salary_with_the_amount_first_and_a_day(uow: UowFactory, alice: UserId) -> None:
    model = scripted()
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "9397 as salary yesterday", "tg:1:1"))
    assert reply.text == "Recorded 9397.00 SGD salary."
    assert model.seen == []  # recorded without the model
    [tx] = (await list_ledger(uow(), alice, LedgerQuery(direction=Direction.IN))).items
    assert tx.amount == Money.of("9397", "SGD") and tx.notes == "Salary"
    assert tx.occurred_at == NOW - timedelta(days=1)


async def test_income_the_patterns_miss_goes_to_the_model_and_asks_first(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(
        call("record_income", amount="2000", kind="other", note="bonus", date="yesterday"),
        say("Recorded."),
    )
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "work gave me a 2k bonus yesterday", "tg:1:1"))
    assert reply.text == "Record 2000.00 SGD income (bonus) on 27 Sep?"
    assert await ledger(uow, alice) == []  # nothing until the user confirms
    await agent.resolve(alice, reply.buttons[0][0].data.split(":")[1], True)
    [tx] = (await list_ledger(uow(), alice, LedgerQuery(direction=Direction.IN))).items
    assert (tx.amount, tx.notes) == (Money.of("2000", "SGD"), "bonus")
    assert tx.occurred_at.date() == (NOW - timedelta(days=1)).date()


async def test_a_confirmed_repayment_settles_the_iou(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("60", "SGD"), NOW)
    )
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann")])  # Ann owes 30
    model = scripted(
        call("record_income", amount="30", kind="repayment", from_whom="Ann"),
        say("Done."),
    )
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "ann sorted out her half of dinner", "tg:1:1"))
    assert reply.text == "Record 30.00 SGD paid back by Ann on 28 Sep?"
    await agent.resolve(alice, reply.buttons[0][0].data.split(":")[1], True)
    assert "Recorded 30.00 SGD from Ann. Ann is all settled." in tool_results(model)
    assert await list_open_ious(uow(), alice) == []


async def test_a_declined_income_records_nothing(uow: UowFactory, alice: UserId) -> None:
    model = scripted(call("record_income", amount="9397", kind="salary"), say("OK."))
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "paid today, 9397 landed", "tg:1:1"))
    assert reply.text == "Record 9397.00 SGD salary on 28 Sep?"
    await agent.resolve(alice, reply.buttons[0][0].data.split(":")[1], False)
    assert await ledger(uow, alice) == []


async def test_unclear_income_gets_a_question_not_a_guess(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("Was that Ann paying you back, or a gift?"))
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "20 came in from Ann", "tg:1:1"))
    assert reply.text == "Was that Ann paying you back, or a gift?"
    assert await ledger(uow, alice) == []
    system = str(model.seen[-1][0].content)
    assert "ask one short question first" in system and "income skill" in system


async def test_money_movement_is_refused_and_logged(
    engine: AsyncEngine, uow: UowFactory, alice: UserId
) -> None:
    model = scripted()
    reply = only(await build(uow, model).handle_text(alice, "transfer 50 to Ann", "tg:1:1"))
    assert reply.text.startswith("I can't send or transfer money")
    assert model.seen == []
    async with engine.connect() as conn:
        count = (await conn.execute(select(func.count()).select_from(capability_gaps))).scalar()
    assert count == 1


async def test_self_diagnosis_uses_health_check(uow: UowFactory, alice: UserId) -> None:
    reply = only(await build(uow, scripted()).handle_text(alice, "are you working?", "tg:1:1"))
    assert reply.text == "All systems fine."


async def test_step_limit_stops_runaway_tool_loops(uow: UowFactory, alice: UserId) -> None:
    model = scripted(*[call("list_categories") for _ in range(MAX_STEPS)])
    reply = only(await build(uow, model).handle_text(alice, "loop", "tg:1:1"))
    assert "too many steps" in reply.text
    assert len(model.seen) == MAX_STEPS


async def test_model_outage_is_reported_honestly(uow: UowFactory, alice: UserId) -> None:
    model = scripted(RuntimeError("503"))
    reply = only(await build(uow, model).handle_text(alice, "coffee 4", "tg:1:1"))
    assert reply.text == "Sorry, I can't reach the AI model right now. Nothing was changed."
    assert await ledger(uow, alice) == []


async def test_receipt_photo_is_confirmed_then_logged_once(uow: UowFactory, alice: UserId) -> None:
    receipts = FakeReceipts(
        ReceiptDraft(
            is_receipt=True,
            amount="23.40",
            merchant="FairPrice",
            date="2026-09-27",
            category="Groceries",
        )
    )
    agent = build(uow, scripted(), receipts)
    reply = only(await agent.handle_photo(alice, b"jpg", "image/jpeg", None, "telegram-photo:u1"))
    assert "Groceries" in receipts.categories  # the reader picks from the user's categories
    assert reply.text == "Log 23.40 SGD at FairPrice on 2026-09-27 from this receipt?"
    done = only(await agent.resolve(alice, reply.buttons[0][0].data.split(":")[1], True))
    assert done.text == "Logged from receipt: 2026-09-27 · -23.40 SGD · FairPrice · Groceries"
    page = await list_ledger(uow(), alice, LedgerQuery())
    assert page.items[0].source is Source.PHOTO

    again = only(await agent.handle_photo(alice, b"jpg", "image/jpeg", None, "telegram-photo:u1"))
    dup = only(await agent.resolve(alice, again.buttons[0][0].data.split(":")[1], True))
    assert dup.text == "That receipt was already recorded."
    assert (await list_ledger(uow(), alice, LedgerQuery())).total == 1


async def test_unreadable_photo(uow: UowFactory, alice: UserId) -> None:
    agent = build(uow, scripted(), FakeReceipts(ReceiptDraft(is_receipt=False)))
    reply = only(await agent.handle_photo(alice, b"jpg", "image/jpeg", None, "p"))
    assert reply.text.startswith("I couldn't read a total")


async def test_quick_actions(uow: UowFactory, alice: UserId) -> None:
    agent = build(uow, scripted())
    assert (
        only(await agent.quick_action(alice, "summary")).text == "Nothing recorded this month yet."
    )
    await log_transaction(uow(), alice, NewTransaction(Direction.OUT, Money.of("8", "SGD"), NOW))
    summary = only(await agent.quick_action(alice, "summary")).text
    assert summary.startswith("September so far:\nSpent 8.00 SGD")
    # A foreign amount with no rate is said, not silently mixed in or dropped.
    await log_transaction(uow(), alice, NewTransaction(Direction.OUT, Money.of("5", "USD"), NOW))
    summary = only(await agent.quick_action(alice, "summary")).text
    assert summary.startswith("September so far:\nSpent 8.00 SGD (plus 5.00 USD not converted)")
    assert only(await agent.quick_action(alice, "undo")).text == "Undone: the create of 5.00 USD."
    assert only(await agent.quick_action(alice, "undo")).text == "Undone: the create of 8.00 SGD."
    assert only(await agent.quick_action(alice, "undo")).text == "There is nothing to undo."
    assert only(await agent.quick_action(alice, "ious")).text == "Nobody owes you anything."


async def test_subscription_buttons_track_or_turn_down(uow: UowFactory, alice: UserId) -> None:
    agent = build(uow, scripted())
    user = await get_user(uow(), alice)
    for month in (7, 8, 9):
        at = NOW.replace(month=month, day=12)
        cmd = NewTransaction(Direction.OUT, Money.of("15.98", "SGD"), at, counterparty="Netflix")
        await log_transaction(uow(), alice, cmd)
    await subscription_cases.check(uow, user, now=NOW)
    [proposal] = (await subscription_cases.overview(uow(), alice)).proposed
    sub_id = proposal.subscription.id
    reply = only(await agent.press(alice, f"sub:track:{sub_id}"))
    assert reply.text.startswith("Tracking Netflix.")
    assert [
        v.subscription.id for v in (await subscription_cases.overview(uow(), alice)).tracked
    ] == [sub_id]
    reply = only(await agent.press(alice, f"sub:skip:{sub_id}"))
    assert reply.text == "OK, I won't ask about that one again."
    assert (await subscription_cases.overview(uow(), alice)).tracked == []
    assert only(await agent.press(alice, "sub:track:nope")).text == "I don't know that button."


async def test_cash_flow_lists_what_is_coming(uow: UowFactory, alice: UserId) -> None:
    user = await get_user(uow(), alice)
    await bill_cases.add_bill(
        uow(), user, "Rent", NOW.date() + timedelta(days=3), Cadence.MONTHLY,
        Money.of("1800", "SGD"), now=NOW,
    )  # fmt: skip
    model = scripted(call("cash_flow", days=14), say("Rent is due soon."))
    await build(uow, model).handle_text(alice, "what's coming up?", "tg:1:1")
    [result] = tool_results(model)
    assert "Rent (bill) -1800.00 SGD" in result
    assert "net -1800.00 SGD" in result and "not a balance" in result


async def test_threads_are_per_user(uow: UowFactory, alice: UserId, bob: UserId) -> None:
    model = scripted(say("hi alice"), say("hi bob"))
    agent = build(uow, model)
    await agent.handle_text(alice, "hello, I'm alice", "tg:1:1")
    await agent.handle_text(bob, "hello", "tg:2:1")
    bob_view = " ".join(str(m.content) for m in model.seen[-1])
    assert "alice" not in bob_view


async def test_a_category_correction_offers_a_rule_and_waits_for_the_answer(
    uow: UowFactory, alice: UserId
) -> None:
    ride = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("12", "SGD"), NOW, counterparty="Grab")
    )
    model = scripted(
        call("edit_transaction", transaction_id=str(ride.id), category="Transport"),
        say("Moved it to Transport. Want me to always do that?"),
    )
    agent = build(uow, model)
    confirm = only(await agent.handle_text(alice, "grab was transport", "tg:1:1"))
    assert confirm.text == "Change 2026-09-28 · -12.00 SGD · Grab · Other: category → Transport?"
    done = only(await agent.resolve(alice, confirm.buttons[0][0].data.split(":")[1], True))
    assert "Always file “grab” under Transport?" in tool_results(model)[-1]
    save, skip = done.buttons[0]
    assert (save.label, skip.label) == ("Save rule", "Just this once")
    assert done.buttons[-1][0].label == "Undo"
    assert await list_rules(uow(), alice) == []  # nothing until the user answers

    assert only(await agent.press(alice, skip.data)).text == (
        "OK, just this once. Your rules are unchanged."
    )
    assert await list_rules(uow(), alice) == []
    saved = only(await agent.press(alice, save.data))
    assert saved.text == "Saved: new expenses from “grab” will go under Transport."
    assert only(await agent.press(alice, save.data)).text == (
        "Your rule already files “grab” under Transport."
    )
    [rule] = await list_rules(uow(), alice)
    nxt = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("9", "SGD"), NOW, counterparty="grab")
    )
    assert nxt.category_rule_id == rule.rule.id
    assert only(await agent.press(alice, "rule:save:not-a-uuid")).text == (
        "I don't know that button."
    )


async def test_rule_changes_by_chat_are_confirmed(uow: UowFactory, alice: UserId) -> None:
    model = scripted(
        call("set_category_rule", pattern="Netflix", category="Activities"),
        say("Done."),
        call("set_category_rule", pattern="netflix", category="Bills & Utilities"),
        say("Changed."),
        call("remove_category_rule", pattern="NETFLIX"),
        say("Removed."),
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "netflix is entertainment", "tg:1:1"))
    assert ask.text == "File new expenses mentioning “netflix” under Activities?"
    assert await list_rules(uow(), alice) == []
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    [rule] = await list_rules(uow(), alice)
    assert rule.category.name == "Activities"

    ask = only(await agent.handle_text(alice, "actually it's a bill", "tg:1:2"))
    assert ask.text == (
        "Change your rule for “netflix” from Activities to Bills & Utilities? "
        "Expenses already logged stay as they are."
    )
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    ask = only(await agent.handle_text(alice, "forget the netflix rule", "tg:1:3"))
    assert ask.text == "Remove your rule filing “netflix” under Bills & Utilities?"
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    assert await list_rules(uow(), alice) == []


async def test_a_flood_of_messages_is_slowed_down(uow: UowFactory, alice: UserId) -> None:
    from datetime import timedelta

    from nexus.agent.service import SLOW_DOWN
    from nexus.application.limits import RateLimiter

    model = scripted(say("one"), say("two"))
    agent = build(uow, model)
    agent._limiter = RateLimiter({"message": ((2, timedelta(minutes=1)),)})
    replies = [(await agent.handle_text(alice, f"hi {n}", f"tg:9:{n}"))[0].text for n in range(3)]
    assert replies == ["one", "two", SLOW_DOWN]  # the third never reached the model
