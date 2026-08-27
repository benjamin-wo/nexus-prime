"""The agent kernel: deterministic safety checks that never reach the LLM."""
import pytest
from langchain_core.messages import HumanMessage

from orchestrator.agent_node import agent_turn
from orchestrator.kernel import is_termination_intent, insufficiency_refusal, missing_policy


def test_termination_intent_detection():
    assert is_termination_intent("Stop") is True
    assert is_termination_intent("stop!") is True
    assert is_termination_intent("that's enough") is True
    assert is_termination_intent("never mind") is True
    assert is_termination_intent("This is a problem") is False
    assert is_termination_intent("fullerton sq") is False


def test_guardrail_detects_unsupported_transactional_categories():
    assert "calendar" in missing_policy("Schedule a meeting on my calendar tomorrow")
    assert "bank_transfer" in missing_policy("please transfer $500 to Loren")
    assert missing_policy("what are my points balances?") == []


def test_insufficiency_refusal_messages():
    refusal = insufficiency_refusal(["bank_transfer"])
    assert "needs your explicit approval" in refusal.message
    refusal = insufficiency_refusal(["calendar"])
    assert "#calendar" in refusal.message


@pytest.mark.asyncio
async def test_kernel_terminates_without_llm(monkeypatch):
    async def _fail(*args, **kwargs):
        raise AssertionError("LLM must not run for termination intents")

    monkeypatch.setattr("orchestrator.agent_node.get_agent_llm", _fail)
    result = await agent_turn({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="Stop")],
    })
    assert "stop here" in str(result.update["messages"][-1].content)


@pytest.mark.asyncio
async def test_kernel_refuses_transactional_ask_without_llm(monkeypatch):
    async def _fail(*args, **kwargs):
        raise AssertionError("LLM must not run for guardrailed transactional asks")

    monkeypatch.setattr("orchestrator.agent_node.get_agent_llm", _fail)
    result = await agent_turn({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="Schedule a meeting on my calendar tomorrow")],
    })
    reply = str(result.update["messages"][-1].content)
    assert "#calendar" in reply
    assert result.update.get("intent_type") == "unsupported_transaction"


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
    result = await agent_turn({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "pending_bus_stops": pending,
        "messages": [HumanMessage(content="Fullerton sq")],
    })
    assert "Bus 10" in str(result.update["messages"][-1].content)


@pytest.mark.asyncio
async def test_kernel_income_write_is_deterministic():
    from core.db import async_session_factory, init_db
    from core.models import UserProfile

    await init_db()
    async with async_session_factory() as session:
        session.add(UserProfile(user_id=424242, telegram_chat_id=424242))
        await session.commit()

    result = await agent_turn({
        "user_id": 424242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="Loren already paid me $13 yesterday")],
    })
    reply = str(result.update["messages"][-1].content)
    assert "Logged" in reply or "marked their IOU" in reply


@pytest.mark.asyncio
async def test_agent_loop_chains_tools_and_surfaces_result(monkeypatch):
    """The agent loop must call a skill tool, inject the authenticated
    user_id, and surface the final answer."""
    import core.skill_registry as skill_registry
    import orchestrator.agent_node as agent_node_module
    from langchain_core.messages import AIMessage

    class _SpyTool:
        name = "query_my_points_balances"

        async def ainvoke(self, args):
            self.captured = dict(args)
            return "DBS Rewards: 12,000"

        async def __call__(self, *a, **k):
            return ""

    spy = _SpyTool()

    class _FakeLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "query_my_points_balances",
                    "args": {"user_id": 666666},
                    "id": "call_1",
                    "type": "tool_call",
                }])
            return AIMessage(content="You have 12,000 DBS Rewards points.")

    fake = _FakeLLM()
    monkeypatch.setattr(
        skill_registry,
        "build_tool_registry",
        lambda force=False: {"query_my_points_balances": spy},
    )
    monkeypatch.setattr(agent_node_module, "get_agent_llm", lambda *a, **k: fake)

    result = await agent_turn({
        "user_id": 4242,
        "current_timezone": "Asia/Singapore",
        "messages": [HumanMessage(content="what are my points balances?")],
    })

    assert spy.captured["user_id"] == 4242, "identity guard must override the model-supplied user_id"
    reply = result.update["messages"][-1]
    assert "12,000 DBS Rewards" in str(reply.content)
