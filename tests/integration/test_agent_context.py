"""What the model is told each turn besides the messages: a snapshot of the user's
money, and a rolling summary once a conversation outgrows its window."""

import asyncio
from datetime import datetime

import pytest
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from nexus.agent import snapshot as snapshot_module
from nexus.agent.graph import HISTORY_LIMIT, KEEP, thread_id
from nexus.agent.service import AgentService
from nexus.agent.snapshot import money_snapshot
from nexus.agent.tools import ToolContext
from nexus.application.transactions import NewTransaction, log_transaction
from nexus.domain.ledger import Direction, UserId
from nexus.domain.money import Money
from nexus.evals import seed
from nexus.evals.runner import FixedRates
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build

pytestmark = pytest.mark.integration


async def test_the_snapshot_shows_the_users_money(uow: UowFactory) -> None:
    user = (await seed.seed_user(uow, 5150)).user
    text = await money_snapshot(ToolContext(user, uow, seed.NOW, FixedRates()))
    assert f"spent {seed.SEPT_SPENT} SGD" in text
    assert "received 5,000.00 SGD" in text
    assert "Dining Out 143.90 SGD of 300.00 SGD (47%, 156.10 SGD left)" in text
    assert "Thu 1 Oct bill Rent 1,800.00 SGD" in text  # due within the week
    assert "Ann 40.00 SGD" in text and "Ben 40.00 SGD" in text
    assert text.index("Kopitiam") < text.index("Grab")  # newest first
    assert len(text) <= 2000


async def test_an_empty_ledger_gives_a_short_snapshot(uow: UowFactory, alice: object) -> None:
    from nexus.application.users import get_user

    user = await get_user(uow(), alice)  # type: ignore[arg-type]
    text = await money_snapshot(ToolContext(user, uow, seed.NOW))
    assert "spent 0.00 SGD" in text
    assert "Next 7 days: no bills, subscriptions or payday due." in text
    assert "Owed to the user" not in text and "Latest transactions" not in text


def _history_line(text: str) -> str:
    [line] = [ln for ln in text.splitlines() if ln.startswith("History:")]
    return line


async def test_the_snapshot_says_how_far_history_goes_and_gives_past_months(
    uow: UowFactory,
) -> None:
    user = (await seed.seed_user(uow, 5160, november=True)).user
    text = await money_snapshot(ToolContext(user, uow, seed.NOV_NOW, FixedRates()))
    # The month figures Home and month_outlook use: August 4,753.22, September 4,539.97, nothing
    # in October. Next to the month line, so this month is never taken for all there is.
    assert _history_line(text) == (
        "History: from 3 Aug 2026. Net by month (in minus out, SGD): "
        "Aug +4,753.22, Sep +4,539.97, Oct 0.00."
    )
    lines = text.splitlines()
    month = next(i for i, ln in enumerate(lines) if ln.startswith("This month so far"))
    assert lines[month + 1] == _history_line(text)
    assert seed.AUG_NET == "4753.22" and seed.SEP_NET == "4539.97"


async def test_the_history_line_leaves_out_months_before_the_ledger_starts(
    uow: UowFactory,
) -> None:
    user = (await seed.seed_user(uow, 5161)).user  # August and September, on 28 September
    text = await money_snapshot(ToolContext(user, uow, seed.NOW, FixedRates()))
    assert _history_line(text) == (
        "History: from 3 Aug 2026. Net by month (in minus out, SGD): Aug +4,753.22."
    )


async def test_the_history_line_gives_at_most_three_months_and_points_to_the_rest(
    uow: UowFactory,
) -> None:
    user = (await seed.seed_user(uow, 5162, november=True)).user
    await log_transaction(
        uow(),
        user.id,
        NewTransaction(Direction.OUT, Money.of("10", "SGD"), datetime(2026, 5, 2, tzinfo=seed.TZ)),
    )
    text = await money_snapshot(ToolContext(user, uow, seed.NOV_NOW, FixedRates()))
    assert _history_line(text) == (
        "History: from 2 May 2026. Net by month (in minus out, SGD): "
        "Aug +4,753.22, Sep +4,539.97, Oct 0.00. Earlier months: query_ledger by month."
    )


async def test_a_ledger_that_began_this_month_says_there_is_nothing_before(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.application.users import get_user

    user = await get_user(uow(), alice)
    assert "History:" not in await money_snapshot(ToolContext(user, uow, seed.NOW))  # empty
    await log_transaction(
        uow(),
        alice,
        NewTransaction(Direction.OUT, Money.of("12", "SGD"), seed.NOW, counterparty="Grab"),
    )
    text = await money_snapshot(ToolContext(user, uow, seed.NOW))
    assert _history_line(text) == "History: from 28 Sep 2026 (nothing before this month)."


async def test_the_history_line_survives_the_character_cap(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = (await seed.seed_user(uow, 5163, november=True)).user
    monkeypatch.setattr(snapshot_module, "MAX_CHARS", 600)
    text = await money_snapshot(ToolContext(user, uow, seed.NOV_NOW, FixedRates()))
    assert len(text) <= 600
    assert "Net by month (in minus out, SGD): Aug +4,753.22" in text  # cut from the end instead
    assert "Expected by month end" in text
    assert "Latest transactions" not in text


def _system(seen: list[BaseMessage]) -> str:
    first = seen[0]
    assert isinstance(first, SystemMessage)
    return str(first.content)


def _config(actor: UserId) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id(actor), "user_id": str(actor)}}


async def _messages(agent: AgentService, actor: UserId) -> list[BaseMessage]:
    return list((await agent._graph.aget_state(_config(actor))).values["messages"])


async def _fill(agent: AgentService, actor: UserId, turns: int) -> None:
    """Chat until the thread holds exactly 2 * turns messages."""
    await agent.handle_text(actor, "my landlord is mr tan", "tg:1:0")
    for n in range(1, turns):
        await agent.handle_text(actor, f"note {n}", f"tg:1:{n}")


async def test_a_long_conversation_is_summarised_after_the_reply(
    uow: UowFactory, alice: UserId
) -> None:
    turns = HISTORY_LIMIT // 2  # two messages a turn: the next turn tips it over
    model = scripted(
        *[say("ok") for _ in range(turns + 1)],
        say("The user's landlord is Mr Tan; rent is due on the 1st."),  # the summary
        say("Mr Tan."),
    )
    agent = build(uow, model)
    await _fill(agent, alice, turns)
    assert len(model.seen) == turns

    reply = await agent.handle_text(alice, "who is my landlord?", "tg:1:x")
    assert reply[0].text == "ok"
    assert len(await _messages(agent, alice)) <= HISTORY_LIMIT + 2

    await agent.drain()
    # The turn's own prompt (with the system message) came first; the summariser's
    # request came after the reply and saw the start of the conversation.
    assert len(model.seen) == turns + 2
    assert isinstance(model.seen[turns][0], SystemMessage)
    assert len(model.seen[turns + 1]) == 1
    assert "my landlord is mr tan" in str(model.seen[turns + 1][0].content)
    messages = await _messages(agent, alice)
    assert len(messages) <= KEEP + 1
    assert "landlord" not in str(messages[0].content)  # the old messages are gone
    state = await agent._graph.aget_state(_config(alice))
    assert "The user's landlord is Mr Tan" in state.values["summary"]
    assert state.next == ()  # writing the summary scheduled nothing

    # ...and the next prompt carries it, with no further model call in between.
    reply = await agent.handle_text(alice, "who is my landlord again?", "tg:1:y")
    assert reply[0].text == "Mr Tan."
    assert "The user's landlord is Mr Tan" in _system(model.seen[-1])
    await agent.drain()
    assert len(model.seen) == turns + 3  # under the limit again: nothing to condense


async def test_a_short_conversation_is_never_condensed(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("ok"), say("ok"))
    agent = build(uow, model)
    await agent.handle_text(alice, "hi", "tg:3:0")
    await agent.handle_text(alice, "hello", "tg:3:1")
    await agent.drain()
    assert len(model.seen) == 2 and len(await _messages(agent, alice)) == 4


async def test_nothing_is_condensed_while_a_confirmation_waits(
    uow: UowFactory, alice: UserId
) -> None:
    tx = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, Money.of("12", "SGD"), NOW, counterparty="Grab")
    )
    turns = HISTORY_LIMIT // 2
    model = scripted(
        *[say("ok") for _ in range(turns)],
        call("delete_transaction", transaction_id=str(tx.id)),
        say("Deleted it."),
        say("A summary."),
    )
    agent = build(uow, model)
    await _fill(agent, alice, turns)

    reply = await agent.handle_text(alice, "delete the grab ride", "tg:1:x")
    pending = reply[0].buttons[0][0].data.split(":")[1]
    await agent.drain()
    assert len(model.seen) == turns + 1  # no summariser call
    assert agent._condense is not None
    assert await agent._condense(_config(alice)) is False  # even when asked directly
    assert len(await _messages(agent, alice)) > HISTORY_LIMIT

    # Once answered, the turn completes and the thread is condensed.
    done = await agent.resolve(alice, pending, True)
    assert done[0].text == "Deleted it."
    await agent.drain()
    assert len(model.seen) == turns + 3
    state = await agent._graph.aget_state(_config(alice))
    assert state.values["summary"] == "A summary."
    assert len(state.values["messages"]) <= KEEP + 2


async def test_a_failed_summary_keeps_the_conversation(uow: UowFactory, alice: UserId) -> None:
    turns = HISTORY_LIMIT // 2
    model = scripted(
        *[say("ok") for _ in range(turns)],
        say("last"),
        RuntimeError("model down"),
        say("still here"),
    )
    agent = build(uow, model)
    await _fill(agent, alice, turns)
    reply = await agent.handle_text(alice, "hello?", "tg:2:x")
    assert reply[0].text == "last"
    await agent.drain()  # the summariser failed; nothing escapes
    state = await agent._graph.aget_state(_config(alice))
    assert "summary" not in state.values
    assert len(state.values["messages"]) == HISTORY_LIMIT + 2

    reply = await agent.handle_text(alice, "anyone there?", "tg:2:y")
    assert reply[0].text == "still here"


async def test_quick_turns_do_not_corrupt_the_thread(uow: UowFactory, alice: UserId) -> None:
    turns = HISTORY_LIMIT // 2
    model = scripted(
        *[say("ok") for _ in range(turns)],
        say("first"),
        say("second"),
        say("The user's landlord is Mr Tan."),  # the one summary
    )
    agent = build(uow, model)
    await _fill(agent, alice, turns)

    replies = await asyncio.gather(
        agent.handle_text(alice, "note a", "tg:4:a"), agent.handle_text(alice, "note b", "tg:4:b")
    )
    assert [r[0].text for r in replies] == ["first", "second"]
    await agent.drain()

    assert len(model.seen) == turns + 3  # the second task found nothing left to do
    state = await agent._graph.aget_state(_config(alice))
    messages = state.values["messages"]
    ids = [m.id for m in messages]
    assert len(set(ids)) == len(ids)
    assert [str(m.content) for m in messages[-4:]] == ["note a", "first", "note b", "second"]
    assert state.values["summary"] == "The user's landlord is Mr Tan."
    assert state.next == ()


async def test_the_reply_does_not_wait_for_a_slow_summary(uow: UowFactory, alice: UserId) -> None:
    turns = HISTORY_LIMIT // 2
    model = scripted(*[say("ok") for _ in range(turns + 1)])
    agent = build(uow, model)
    await _fill(agent, alice, turns)
    release = asyncio.Event()
    started = asyncio.Event()
    real = agent._condense
    assert real is not None

    async def slow(config: RunnableConfig) -> bool:
        started.set()
        await release.wait()
        return await real(config)

    agent._condense = slow
    reply = await asyncio.wait_for(agent.handle_text(alice, "hello", "tg:5:x"), timeout=5)
    assert reply[0].text == "ok"
    await asyncio.wait_for(started.wait(), timeout=5)
    release.set()
    await agent.drain()
