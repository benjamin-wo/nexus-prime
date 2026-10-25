"""Open items: the summary pass also lists what the user said they'd come back to, the
prompt shows it (while fresh) as something the model may use, and a later pass can clear it."""

from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from nexus.agent.graph import HISTORY_LIMIT, thread_id
from nexus.agent.open_items import OpenItem
from nexus.agent.service import AgentService
from nexus.domain.ledger import UserId
from tests.fakes import ScriptedModel, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build

pytestmark = pytest.mark.integration

SAT_NIGHT = datetime(2026, 10, 24, 22, 51, tzinfo=UTC)  # the test user's time zone is UTC
JUMBO = "Jumbo dinner on Sat 24 Oct, about 80; the user will send the exact amount"
SUMMARY = "The user had dinner at Jumbo on Sat 24 Oct."
HEADING = "Still open from earlier"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _config(actor: UserId) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id(actor), "user_id": str(actor)}}


def _system(seen: list[BaseMessage]) -> str:
    first = seen[0]
    assert isinstance(first, SystemMessage)
    return str(first.content)


async def _values(agent: AgentService, actor: UserId) -> dict[str, object]:
    return dict((await agent._graph.aget_state(_config(actor))).values)


async def _condensed(
    uow: UowFactory, alice: UserId, clock: Clock, reply: str
) -> tuple[AgentService, ScriptedModel]:
    """A thread whose first summary pass (run after the turn that tipped it over) got ``reply``."""
    turns = HISTORY_LIMIT // 2
    model = scripted(*[say("ok") for _ in range(turns + 1)], say(reply))
    agent = build(uow, model, clock=clock)
    await agent.handle_text(
        alice, "dinner at jumbo tonight, about 80. exact amount later", "tg:1:0"
    )
    for n in range(1, turns + 1):
        await agent.handle_text(alice, f"note {n}", f"tg:1:{n}")
    await agent.drain()
    return agent, model


async def _stuff(agent: AgentService, alice: UserId, extra: dict[str, object]) -> None:
    """Grow the thread past the window again, and set more state, in one write."""
    messages: list[BaseMessage] = []
    for n in range(HISTORY_LIMIT):
        messages += [HumanMessage(content=f"later {n}"), AIMessage(content="ok")]
    await agent._graph.aupdate_state(
        _config(alice), {"messages": messages, **extra}, as_node="kernel_reply"
    )


async def test_a_summary_pass_stores_the_open_items_and_the_next_prompt_shows_them(
    uow: UowFactory, alice: UserId
) -> None:
    clock = Clock(SAT_NIGHT)
    agent, model = await _condensed(uow, alice, clock, f"{SUMMARY}\n\nOPEN:\n- {JUMBO}\n")
    turns = HISTORY_LIMIT // 2
    assert len(model.seen) == turns + 2  # one summary call, and it was asked for the items
    request = str(model.seen[turns + 1][0].content)
    assert "OPEN:" in request and "Items so far:\n(none)" in request

    values = await _values(agent, alice)
    assert values["summary"] == SUMMARY  # the section is not part of it
    assert values["open_items"] == [{"text": JUMBO, "since": SAT_NIGHT.isoformat()}]

    model.script.append(say("Which dinner? Ah, Jumbo."))
    await agent.handle_text(alice, "log that dinner, it came to 85", "tg:1:x")
    system = _system(model.seen[-1])
    assert f"{JUMBO} (noted Sat 24 Oct)" in system
    assert HEADING in system and "it may already be done" in system
    assert "OPEN:" not in system  # only the summary, not the marker
    assert system.index("a summary") < system.index(HEADING)  # near the summary


async def test_an_item_older_than_three_days_is_not_shown(uow: UowFactory, alice: UserId) -> None:
    clock = Clock(SAT_NIGHT)
    agent, model = await _condensed(uow, alice, clock, f"{SUMMARY}\nOPEN:\n- {JUMBO}")
    model.script.extend([say("a"), say("b")])

    clock.now = SAT_NIGHT + timedelta(days=2, hours=23)
    await agent.handle_text(alice, "hello", "tg:1:y")
    assert JUMBO in _system(model.seen[-1])

    clock.now = SAT_NIGHT + timedelta(days=3, minutes=1)
    await agent.handle_text(alice, "hello again", "tg:1:z")
    system = _system(model.seen[-1])
    assert HEADING not in system and JUMBO not in system
    assert SUMMARY in system  # the summary itself is untouched


async def test_a_later_pass_that_lists_none_clears_them(uow: UowFactory, alice: UserId) -> None:
    clock = Clock(SAT_NIGHT)
    agent, model = await _condensed(uow, alice, clock, f"{SUMMARY}\nOPEN:\n- {JUMBO}")
    await _stuff(agent, alice, {})
    model.script.extend([say("It came to 85, logged.\nOPEN: none"), say("ok")])

    assert agent._condense is not None
    assert await agent._condense(_config(alice)) is True
    request = str(model.seen[-1][0].content)
    assert f"Items so far:\n- {JUMBO}" in request  # the model was shown what was open
    assert (await _values(agent, alice))["open_items"] == []

    await agent.handle_text(alice, "thanks", "tg:1:w")
    assert HEADING not in _system(model.seen[-1])


async def test_a_reply_without_the_section_keeps_fresh_items_and_drops_stale_ones(
    uow: UowFactory, alice: UserId
) -> None:
    clock = Clock(SAT_NIGHT)
    agent, model = await _condensed(uow, alice, clock, SUMMARY)  # no section at all
    assert "open_items" in await _values(agent, alice)
    assert (await _values(agent, alice))["open_items"] == []

    fresh: OpenItem = {"text": "Send the Jumbo total", "since": SAT_NIGHT.isoformat()}
    stale: OpenItem = {
        "text": "Old thing",
        "since": (SAT_NIGHT - timedelta(days=4)).isoformat(),
    }
    await _stuff(agent, alice, {"open_items": [stale, fresh]})
    model.script.append(say("A newer summary with no section."))
    assert agent._condense is not None
    assert await agent._condense(_config(alice)) is True

    request = str(model.seen[-1][0].content)
    assert "Send the Jumbo total" in request and "Old thing" not in request
    assert (await _values(agent, alice))["open_items"] == [fresh]
