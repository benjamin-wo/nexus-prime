"""The model is offered a core set of tools; a skill's tools arrive when it loads
the skill and lapse a few messages later. Any real tool still runs if called."""

import pytest
from langchain_core.messages import AIMessage

from nexus.agent.graph import CORE_TOOLS, SKILL_TURNS, thread_id
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from tests.fakes import call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build

pytestmark = pytest.mark.integration


def load(skill: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": "load_skill", "args": {"name": skill}, "id": "load-1"}]
    )


def test_every_tool_is_core_or_in_a_skill() -> None:
    skills = SkillLibrary.load()
    reachable = set(CORE_TOOLS).union(*skills.tools().values())
    exposed = {name for name, spec in build_tools(skills.body).items() if spec.exposed}
    assert exposed <= reachable, sorted(exposed - reachable)
    assert set(CORE_TOOLS) <= exposed
    assert len(CORE_TOOLS) < len(exposed) / 2


async def _skills(agent: object, alice: object) -> dict[str, int]:
    config = {"configurable": {"thread_id": thread_id(alice), "user_id": str(alice)}}  # type: ignore[arg-type]
    state = await agent._graph.aget_state(config)  # type: ignore[attr-defined]
    return dict(state.values.get("skills", {}))


async def test_a_skill_brings_its_tools_then_lapses(uow: UowFactory, alice: object) -> None:
    model = scripted(
        say("hi"),
        load("Bills"),
        say("Which bill?"),
        *[say("ok") for _ in range(SKILL_TURNS)],
    )
    agent = build(uow, model)
    await agent.handle_text(alice, "hello", "tg:1:1")  # type: ignore[arg-type]
    assert model.bound == [set(CORE_TOOLS)]

    await agent.handle_text(alice, "remind me about a bill", "tg:1:2")  # type: ignore[arg-type]
    assert await _skills(agent, alice) == {"bills": SKILL_TURNS}
    assert "add_bill" in model.bound[-1] and "set_budget" not in model.bound[-1]

    for n in range(SKILL_TURNS):
        await agent.handle_text(alice, f"note {n}", f"tg:1:x{n}")  # type: ignore[arg-type]
    assert await _skills(agent, alice) == {}
    # Back to the core set, bound once already: no new set of tools appeared.
    assert len(model.bound) == 2


async def test_an_unknown_skill_loads_nothing(uow: UowFactory, alice: object) -> None:
    model = scripted(load("crypto"), say("I can't help with that."))
    agent = build(uow, model)
    await agent.handle_text(alice, "trade crypto", "tg:2:1")  # type: ignore[arg-type]
    assert await _skills(agent, alice) == {}


async def test_a_tool_not_offered_still_runs(uow: UowFactory, alice: object) -> None:
    model = scripted(call("list_budgets"), say("No budgets yet."))
    agent = build(uow, model)
    reply = await agent.handle_text(alice, "budgets?", "tg:3:1")  # type: ignore[arg-type]
    assert reply[0].text == "No budgets yet."
    assert "Error" not in str(model.seen[-1][-1].content)
