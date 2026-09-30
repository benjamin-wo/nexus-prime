"""What the model is told each turn besides the messages: a snapshot of the user's
money, and a rolling summary once a conversation outgrows its window."""

import pytest
from langchain_core.messages import BaseMessage, SystemMessage

from nexus.agent.graph import HISTORY_LIMIT, thread_id
from nexus.agent.snapshot import money_snapshot
from nexus.agent.tools import ToolContext
from nexus.evals import seed
from nexus.evals.runner import FixedRates
from tests.fakes import say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build

pytestmark = pytest.mark.integration


async def test_the_snapshot_shows_the_users_money(uow: UowFactory) -> None:
    user = (await seed.seed_user(uow, 5150)).user
    text = await money_snapshot(ToolContext(user, uow, seed.NOW, FixedRates()))
    assert f"spent {seed.SEPT_SPENT} SGD" in text
    assert "received 5000.00 SGD" in text
    assert "Dining Out 143.90 SGD of 300.00 SGD (47%, 156.10 SGD left)" in text
    assert "Thu 1 Oct bill Rent 1800.00 SGD" in text  # due within the week
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


def _system(seen: list[BaseMessage]) -> str:
    first = seen[0]
    assert isinstance(first, SystemMessage)
    return str(first.content)


async def test_a_long_conversation_is_summarised_not_forgotten(
    uow: UowFactory, alice: object
) -> None:
    turns = HISTORY_LIMIT // 2  # two messages a turn: the next message tips it over
    model = scripted(
        *[say("ok") for _ in range(turns)],
        say("The user's landlord is Mr Tan; rent is due on the 1st."),  # the summary
        say("Mr Tan."),
    )
    agent = build(uow, model)
    await agent.handle_text(alice, "my landlord is mr tan", "tg:1:0")  # type: ignore[arg-type]
    for n in range(1, turns):
        await agent.handle_text(alice, f"note {n}", f"tg:1:{n}")  # type: ignore[arg-type]
    reply = await agent.handle_text(alice, "who is my landlord?", "tg:1:x")  # type: ignore[arg-type]
    assert reply[0].text == "Mr Tan."

    # The summariser saw the start of the conversation; the next prompt carries it.
    assert "my landlord is mr tan" in str(model.seen[-2][0].content)
    assert "The user's landlord is Mr Tan" in _system(model.seen[-1])
    graph = agent._graph
    config = {"configurable": {"thread_id": thread_id(alice), "user_id": str(alice)}}  # type: ignore[arg-type]
    messages = (await graph.aget_state(config)).values["messages"]  # type: ignore[arg-type]
    assert len(messages) <= HISTORY_LIMIT // 2 + 2
    assert "landlord" not in str(messages[0].content)  # the old messages are gone


async def test_a_failed_summary_keeps_the_conversation(uow: UowFactory, alice: object) -> None:
    turns = HISTORY_LIMIT // 2
    model = scripted(
        *[say("ok") for _ in range(turns)], RuntimeError("model down"), say("still here")
    )
    agent = build(uow, model)
    for n in range(turns):
        await agent.handle_text(alice, f"note {n}", f"tg:2:{n}")  # type: ignore[arg-type]
    reply = await agent.handle_text(alice, "hello?", "tg:2:x")  # type: ignore[arg-type]
    assert reply[0].text == "still here"
