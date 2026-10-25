"""The model is told which day each message is from, so "tomorrow" said last night
is not taken for tomorrow this morning."""

from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from nexus.agent.graph import HISTORY_LIMIT, SENT_AT, thread_id
from nexus.agent.service import AgentService
from nexus.domain.ledger import UserId
from tests.fakes import call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build

pytestmark = pytest.mark.integration

SAT_NIGHT = datetime(2026, 10, 24, 22, 51, tzinfo=UTC)  # the test user's time zone is UTC
SUN_MORNING = datetime(2026, 10, 25, 11, 28, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _config(actor: UserId) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id(actor), "user_id": str(actor)}}


async def _messages(agent: AgentService, actor: UserId) -> list[BaseMessage]:
    return list((await agent._graph.aget_state(_config(actor))).values["messages"])


def _texts(seen: list[BaseMessage]) -> list[str]:
    return [str(m.content) for m in seen[1:]]  # after the system prompt


def _system(seen: list[BaseMessage]) -> str:
    first = seen[0]
    assert isinstance(first, SystemMessage)
    return str(first.content)


async def test_yesterdays_words_are_stamped_for_the_model_but_stored_as_said(
    uow: UowFactory, alice: UserId
) -> None:
    clock = Clock(SAT_NIGHT)
    model = scripted(say("Kamakura it is."), say("Brunch it is."))
    agent = build(uow, model, clock=clock)
    await agent.handle_text(alice, "lets go to Kamakura tomorrow", "tg:1:0")
    assert _texts(model.seen[0]) == ["lets go to Kamakura tomorrow"]  # same day: untouched

    clock.now = SUN_MORNING
    await agent.handle_text(alice, "brunch?", "tg:1:1")
    note = "[It's now Sun 25 Oct; the messages above are from Sat 24 Oct or earlier.]\n"
    assert _texts(model.seen[1]) == [
        "[Sat 24 Oct, 22:51] lets go to Kamakura tomorrow",
        "Kamakura it is.",
        note + "brunch?",
    ]
    assert "Now: Sunday 2026-10-25 11:28" in _system(model.seen[1])

    stored = await _messages(agent, alice)  # what is kept is what was said
    assert [str(m.content) for m in stored] == [
        "lets go to Kamakura tomorrow",
        "Kamakura it is.",
        "brunch?",
        "Brunch it is.",
    ]
    assert stored[0].additional_kwargs[SENT_AT] == SAT_NIGHT.isoformat()
    assert stored[2].additional_kwargs[SENT_AT] == SUN_MORNING.isoformat()


async def test_the_day_note_is_kept_through_a_tool_call_and_its_result(
    uow: UowFactory, alice: UserId
) -> None:
    clock = Clock(SAT_NIGHT)
    model = scripted(say("Hi."), call("list_categories"), say("Those are they."))
    agent = build(uow, model, clock=clock)
    await agent.handle_text(alice, "hello", "tg:2:0")
    clock.now = SUN_MORNING
    await agent.handle_text(alice, "what categories are there?", "tg:2:1")

    # The model's second look at the turn, after the tool ran: calls still paired.
    seen = model.seen[-1][1:]
    assert isinstance(seen[0], HumanMessage) and str(seen[0].content).startswith("[Sat 24 Oct")
    kinds = [type(m) for m in seen]
    assert kinds == [HumanMessage, AIMessage, HumanMessage, AIMessage, ToolMessage]
    assert isinstance(seen[3], AIMessage) and seen[3].tool_calls
    assert isinstance(seen[4], ToolMessage)
    assert seen[4].tool_call_id == seen[3].tool_calls[0]["id"]
    assert str(seen[2].content).startswith("[It's now Sun 25 Oct")


async def test_old_messages_without_a_stamp_are_shown_as_they_are(
    uow: UowFactory, alice: UserId
) -> None:
    clock = Clock(SAT_NIGHT)
    model = scripted(say("a"), say("b"))
    agent = build(uow, model, clock=clock)
    await agent.handle_text(alice, "from before the stamps", "tg:3:0")
    # Take the stamp off, as in a thread kept from before this feature.
    state = await agent._graph.aget_state(_config(alice))
    first = state.values["messages"][0]
    first.additional_kwargs.pop(SENT_AT)
    await agent._graph.aupdate_state(_config(alice), {"messages": [first]}, as_node="kernel_reply")

    clock.now = SUN_MORNING
    await agent.handle_text(alice, "morning", "tg:3:1")
    assert _texts(model.seen[1]) == ["from before the stamps", "a", "morning"]


async def test_the_summariser_is_asked_for_absolute_dates_and_the_summary_is_dated(
    uow: UowFactory, alice: UserId
) -> None:
    clock = Clock(SAT_NIGHT)
    turns = HISTORY_LIMIT // 2
    model = scripted(
        *[say("ok") for _ in range(turns)],
        say("ok"),  # the turn that tips it over
        say("User plans Kamakura on Sun 25 Oct; protest on Gran Vía reported Sat 24 Oct evening."),
        say("Not today."),
    )
    agent = build(uow, model, clock=clock)
    await agent.handle_text(alice, "protest on Gran Vía now, Kamakura tomorrow", "tg:4:0")
    for n in range(1, turns):
        await agent.handle_text(alice, f"note {n}", f"tg:4:{n}")
    clock.now = SUN_MORNING
    await agent.handle_text(alice, "brunch?", "tg:4:x")
    await agent.drain()

    request = model.seen[turns + 1]
    assert len(request) == 1
    text = str(request[0].content)
    assert "absolute" in text and "never use relative words" in text
    assert "tomorrow" in text  # named as the words to avoid
    assert "User [Sat 24 Oct, 22:51]: protest on Gran Vía now, Kamakura tomorrow" in text
    assert "(their local time, UTC)" in text
    assert "It is now Sun 25 Oct, 11:28." in text
    assert "Summary so far:\n(none)" in text

    state = await agent._graph.aget_state(_config(alice))
    assert state.values["summary_at"] == SUN_MORNING.isoformat()

    clock.now = SUN_MORNING + timedelta(days=1)
    await agent.handle_text(alice, "and today?", "tg:4:y")
    system = _system(model.seen[-1])
    assert "a summary, written Sun 25 Oct, 11:28; the messages themselves are gone" in system
    assert "Kamakura on Sun 25 Oct" in system
    assert "treat anything an older message called" in system  # the rule about old words


async def test_a_summary_from_before_the_stamps_shows_no_written_time(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("a"), say("b"))
    agent = build(uow, model, clock=Clock(SUN_MORNING))
    await agent.handle_text(alice, "hi", "tg:5:0")
    await agent._graph.aupdate_state(
        _config(alice), {"summary": "The user has a cat."}, as_node="kernel_reply"
    )
    await agent.handle_text(alice, "hello", "tg:5:1")
    system = _system(model.seen[-1])
    assert "Earlier in this conversation (a summary; the messages themselves are gone)" in system
    assert "written" not in system.split("Earlier in this conversation")[1]
