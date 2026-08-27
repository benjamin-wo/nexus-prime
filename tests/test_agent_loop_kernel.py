"""The agent loop's safety kernel: deterministic checks that never reach the LLM."""
import pytest
from langchain_core.messages import HumanMessage

from orchestrator.agent_loop import agent_loop
from orchestrator.kernel import is_termination_intent


def test_termination_intent_detection():
    assert is_termination_intent("Stop") is True
    assert is_termination_intent("stop!") is True
    assert is_termination_intent("that's enough") is True
    assert is_termination_intent("never mind") is True
    assert is_termination_intent("This is a problem") is False
    assert is_termination_intent("fullerton sq") is False


@pytest.mark.asyncio
async def test_kernel_terminates_without_llm(monkeypatch):
    async def _fail(*args, **kwargs):
        raise AssertionError("LLM must not run for termination intents")

    monkeypatch.setattr("orchestrator.agent_loop.get_agent_llm", _fail)
    result = await agent_loop({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="Stop")],
    })
    update = result.update
    assert "stop here" in str(update["messages"][-1].content)
    assert update.get("intent_type") == "close"


@pytest.mark.asyncio
async def test_kernel_answers_pending_bus_disambiguation(monkeypatch):
    import capabilities.routes.tools as routes_tools

    async def fake_bus_query(text, pending_stops=None):
        assert pending_stops and pending_stops[0]["code"] == "03011"
        return {"kind": "arrivals", "message": "Fullerton Sq (03011):\nBus 10: next 3 min"}

    monkeypatch.setattr(routes_tools, "handle_bus_query", fake_bus_query)
    pending = [
        {"code": "03011", "description": "Fullerton Sq", "road_name": "Fullerton Rd"},
        {"code": "01139", "description": "Bugis Stn/Parkview Sq", "road_name": "Nth Bridge Rd"},
    ]
    result = await agent_loop({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "pending_bus_stops": pending,
        "messages": [HumanMessage(content="Fullerton sq")],
    })
    assert "Bus 10" in str(result.update["messages"][-1].content)


def test_tool_roster_comes_from_skills():
    """Every tool the agent can call must be declared by a SKILL.md (or be the
    built-in load_skill tool) — the skill files are the declaration surface."""
    from orchestrator.agent_loop import _build_tool_roster
    from core.skill_registry import discover_skills

    roster = _build_tool_roster()
    names = {t.name for t in roster}
    assert "load_skill" in names
    declared = set()
    for skill in discover_skills().values():
        declared.update(skill.tools)
    undeclared = names - declared - {"load_skill", "log_capability_gap"}
    assert not undeclared, f"roster tools not declared by any skill: {undeclared}"
