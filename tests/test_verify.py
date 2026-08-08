import pytest
from langchain_core.messages import AIMessage, HumanMessage
from unittest.mock import AsyncMock, patch

from orchestrator.planner import (
    CapabilitySelection,
    Decision,
    InsufficientCapability,
    decision_from_dict,
    llm_plan_prompt,
)
from orchestrator.verify import VerifyResult, verify_deterministic, verify_with_llm


def _decision(caps=("expenses",), insufficient=None):
    return Decision(
        capabilities=[CapabilitySelection(id=c, reason="r", confidence=0.9) for c in caps],
        ordering=list(caps),
        insufficient=insufficient,
        confidence=0.9,
        source="deterministic",
        retrieval_used=True,
        rationale="test rationale",
    )


def test_verify_deterministic_rules():
    assert verify_deterministic(_decision(), "   ").needs_replan is True
    refusal = _decision(
        caps=(),
        insufficient=InsufficientCapability(["calendar"], ["missing"]),
    )
    result = verify_deterministic(refusal, "I can't do that yet")
    assert result.needs_replan is False
    assert result.fulfilled is True
    ok = verify_deterministic(_decision(), "logged $5")
    assert ok.fulfilled is True and ok.needs_replan is False


@pytest.mark.asyncio
async def test_verify_with_llm_returns_none_without_key():
    assert await verify_with_llm(_decision(), "hi", "reply", "out", {}) is None


@pytest.mark.asyncio
async def test_verify_with_llm_parses_json(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "real-key")

    class _Message:
        content = '{"fulfilled": false, "missing": "budget not answered", "replan": true}'

    class _LLM:
        async def ainvoke(self, messages):
            return _Message()

    monkeypatch.setattr("core.llm.get_agent_llm", lambda *a, **k: _LLM())
    result = await verify_with_llm(_decision(), "q", "reply", "out", {})
    assert result is not None
    assert result.needs_replan is True
    assert result.missing == "budget not answered"


def test_llm_prompt_includes_conversation_context():
    state = {
        "active_domain": "expenses",
        "last_decision": {"capabilities": [{"id": "expenses"}]},
        "messages": [
            HumanMessage(content="how much did I spend last month"),
            AIMessage(content="you spent 100"),
            HumanMessage(content="and what about next month?"),
        ],
    }
    prompt = llm_plan_prompt(
        "and what about next month?",
        [{"id": "expenses", "description": "expense listing", "score": 0.9}],
        state,
    )
    user_content = prompt[-1]["content"]
    assert "Conversation so far" in user_content
    assert "user: how much did I spend last month" in user_content
    assert "assistant: you spent 100" in user_content
    assert "Current thread domain: expenses" in user_content


def test_decision_parses_rationale():
    decision = decision_from_dict(
        {
            "capabilities": [{"id": "expenses", "reason": "spend", "confidence": 0.9}],
            "ordering": ["expenses"],
            "insufficient_capability": None,
            "question": None,
            "rationale": "internal reasoning",
            "confidence": 0.9,
        },
        shortlist_ids={"expenses"},
    )
    assert decision.rationale == "internal reasoning"


@pytest.mark.asyncio
async def test_bounded_replan_loop_runs_once(monkeypatch):
    from orchestrator.plan_router import plan_dispatch
    from orchestrator.router import PluginOutput

    fake_plugin = AsyncMock()
    fake_plugin.execute.return_value = PluginOutput(
        message=AIMessage(content="fake reply"), state_update={}
    )
    registry = {"expenses": fake_plugin}
    calls = {"n": 0}

    async def fake_llm_plan(text, state, retrieval):
        calls["n"] += 1
        return Decision(
            capabilities=[CapabilitySelection(id="expenses", reason="r", confidence=0.9)],
            ordering=["expenses"],
            confidence=0.9,
            source="llm",
            retrieval_used=True,
            rationale="retry",
        )

    monkeypatch.setattr("orchestrator.planner.plan_with_llm", fake_llm_plan)
    verify_results = [
        VerifyResult(False, True, "needs more", "missing info"),
        VerifyResult(True, False, "ok"),
    ]
    verify_calls = {"n": 0}

    async def fake_verify(decision, text, reply, summary, state):
        verify_calls["n"] += 1
        return verify_results[min(verify_calls["n"] - 1, len(verify_results) - 1)]

    monkeypatch.setattr("orchestrator.verify.verify_with_llm", fake_verify)
    with patch("orchestrator.router.CAPABILITY_REGISTRY", registry):
        state = {
            "user_id": 1,
            "active_domain": None,
            "last_decision": None,
            "plan": None,
            "pending_bus_stops": None,
            "messages": [HumanMessage(content="show my expenses")],
        }
        command = await plan_dispatch(state)
    assert fake_plugin.execute.await_count == 2
    assert verify_calls["n"] == 2
    assert command.update["plan"]["source"] == "llm"


@pytest.mark.asyncio
async def test_replan_loop_is_bounded(monkeypatch):
    from orchestrator.plan_router import plan_dispatch
    from orchestrator.router import PluginOutput

    fake_plugin = AsyncMock()
    fake_plugin.execute.return_value = PluginOutput(
        message=AIMessage(content="fake reply"), state_update={}
    )
    registry = {"expenses": fake_plugin}

    async def fake_llm_plan(text, state, retrieval):
        return Decision(
            capabilities=[CapabilitySelection(id="expenses", reason="r", confidence=0.9)],
            ordering=["expenses"],
            confidence=0.9,
            source="llm",
            retrieval_used=True,
        )

    monkeypatch.setattr("orchestrator.planner.plan_with_llm", fake_llm_plan)

    async def always_replan(decision, text, reply, summary, state):
        return VerifyResult(False, True, "still missing", "still missing")

    monkeypatch.setattr("orchestrator.verify.verify_with_llm", always_replan)
    with patch("orchestrator.router.CAPABILITY_REGISTRY", registry):
        state = {
            "user_id": 1,
            "active_domain": None,
            "last_decision": None,
            "plan": None,
            "pending_bus_stops": None,
            "messages": [HumanMessage(content="show my expenses")],
        }
        await plan_dispatch(state)
    assert fake_plugin.execute.await_count == 2  # initial + exactly one retry
