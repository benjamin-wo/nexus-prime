from langchain_core.messages import HumanMessage
import pytest
from langchain_core.messages import AIMessage

from capabilities.registry import load_registry
from capabilities.retrieval import BM25Index
from orchestrator.planner import decision_from_dict, deterministic_plan, plan_with_llm
from orchestrator.graph import get_assistant_graph


def _state(message: str, domain=None, last=None):
    return {
        "user_id": 1,
        "active_domain": domain,
        "last_decision": last,
        "messages": [HumanMessage(content=message)],
    }


def _retrieval(message: str):
    index = BM25Index(list(load_registry().values()))
    return index.retrieve_with_recovery(message, k=5)


def test_c3_probe1_budget_question_names_missing_capability():
    message = "how much did I spend on food last month, and does that put my Japan trip budget at risk?"
    decision = deterministic_plan(message, _state(message), _retrieval(message))
    assert "expenses" in decision.planned_set
    assert decision.insufficient is not None
    assert "budget" in decision.insufficient.missing_capabilities
    assert "budget" in decision.insufficient.message


def test_c3_probe2_shared_reminder_capability():
    for domain in ("expenses", "recipes", "routes"):
        decision = deterministic_plan("remind me about this on Friday", _state("remind me about this on Friday", domain=domain), _retrieval("remind me about this on Friday"))
        assert decision.capability_ids == ["reminders"]
        assert decision.ordering == ["reminders"]


def test_c3_probe3_referent_reuse_without_retrieval():
    state = _state(
        "and what about next month?",
        domain="expenses",
        last={"capabilities": [{"id": "expenses", "confidence": 0.9}]},
    )
    decision = deterministic_plan("and what about next month?", state, retrieval=None)
    assert decision.capability_ids == ["expenses"]
    assert decision.retrieval_used is False
    assert decision.source == "referent-reuse"


def test_c3_probe4_ambiguity_asks_question():
    decision = deterministic_plan("how am I doing?", _state("how am I doing?"), retrieval=None)
    assert decision.question is not None
    assert decision.capabilities == []


@pytest.mark.asyncio
async def test_referent_reuse_persists_across_graph_turns():
    graph = get_assistant_graph()
    config = {"configurable": {"thread_id": "ref_reuse_graph_001"}}
    first = {
        "messages": [HumanMessage(content="how much did I spend on food last month?")],
        "user_id": 777001,
        "current_timezone": "Asia/Singapore",
        "active_domain": None,
    }
    result1 = await graph.ainvoke(first, config=config)
    assert result1.get("active_domain") == "expenses"
    assert result1.get("last_decision", {}).get("capabilities") or result1.get("last_decision")

    second = {
        "messages": [HumanMessage(content="and what about next month?")],
        "user_id": 777001,
        "current_timezone": "Asia/Singapore",
        "active_domain": None,
    }
    result2 = await graph.ainvoke(second, config=config)
    assert result2.get("active_domain") == "expenses"
    reply = str(result2["messages"][-1].content)
    assert "Hey! I'm here" not in reply


def test_bare_place_fragment_reuses_routes_thread():
    state = {
        "active_domain": "routes",
        "last_decision": {"ordering": ["routes"], "capabilities": [{"id": "routes"}]},
        "messages": [HumanMessage(content="What bus should I take from Tembusu Grand to Suntec")],
    }
    decision = deterministic_plan("tembusu grand", state, None)
    assert decision.capability_ids == ["routes"]
    assert decision.source == "fragment-reuse"
    assert deterministic_plan("who is Albert Einstein", _state("who is Albert Einstein"), None).recipe is None


@pytest.mark.asyncio
async def test_plugin_state_update_merged_by_plan_router(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from orchestrator.plan_router import plan_dispatch
    from orchestrator.router import PluginOutput

    fake_plugin = AsyncMock()
    fake_plugin.execute.return_value = PluginOutput(
        message=AIMessage(content="fake reply"),
        state_update={"pending_bus_stops": [{"code": "76161"}]},
    )
    fake_registry = {"expenses": fake_plugin}
    with patch("orchestrator.router.CAPABILITY_REGISTRY", fake_registry):
        state = {
            "user_id": 1,
            "active_domain": None,
            "last_decision": None,
            "pending_bus_stops": None,
            "messages": [HumanMessage(content="show my expenses")],
        }
        command = await plan_dispatch(state)
    assert command.update["pending_bus_stops"] == [{"code": "76161"}]
    assert command.update["active_domain"] == "expenses"


@pytest.mark.asyncio
async def test_incoming_money_is_not_reclassified_as_missing_capability(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from orchestrator.plan_router import plan_dispatch
    from orchestrator.router import PluginOutput
    from orchestrator.planner import Decision, InsufficientCapability

    fake_plugin = AsyncMock()
    fake_plugin.execute.return_value = PluginOutput(
        message=AIMessage(content="logged incoming SGD 13.00 from Loren"),
    )
    unsupported = Decision(
        insufficient=InsufficientCapability(
            missing_capabilities=["income_tracking"],
            reasons=["test planner response"],
            message="unsupported",
        ),
        confidence=0.9,
    )
    state = _state("Loren already paid me $13 yesterday")

    with patch("orchestrator.router.CAPABILITY_REGISTRY", {"expenses": fake_plugin}), \
            patch("orchestrator.planner.plan_with_llm", new=AsyncMock(return_value=unsupported)):
        command = await plan_dispatch(state)

    fake_plugin.execute.assert_awaited_once()
    assert command.update["active_domain"] == "expenses"
    assert "unsupported" not in command.update["messages"][-1].content


@pytest.mark.asyncio
async def test_llm_planner_returns_none_without_real_key():
    decision = await plan_with_llm("check my email", _state("check my email"), None)
    assert decision is None


def test_llm_decision_dict_validated_against_shortlist():
    decision = decision_from_dict(
        {
            "capabilities": [
                {"id": "email", "reason": "email intent", "confidence": 0.9},
                {"id": "not_in_shortlist", "reason": "ignored", "confidence": 0.9},
            ],
            "ordering": ["email"],
            "insufficient_capability": None,
            "question": None,
            "confidence": 0.9,
        },
        shortlist_ids={"email"},
    )
    assert decision is not None
    assert decision.capability_ids == ["email"]
    assert decision.source == "llm"


@pytest.mark.asyncio
async def test_llm_planner_widens_shortlist_to_expanded_on_recovery(monkeypatch):
    """Regression (#10): a low-confidence retrieval (`recovered=True`) must widen
    the LLM's candidate pool to `expanded`, not just the top-k. Otherwise a query
    that shares no tokens with any manifest (e.g. "did u see the one from DBS
    today?") can leave the right capability out of the shortlist entirely, the
    LLM's pick gets rejected by decision_from_dict's shortlist validation, and
    the planner silently falls back to deterministic routing / hallucination."""
    from core.config import settings
    from capabilities.retrieval import RetrievalHit, RetrievalResult

    monkeypatch.setattr(settings, "deepseek_api_key", "real-key")
    monkeypatch.setattr(settings, "llm_provider", "deepseek")

    registry = load_registry()
    general_hit = RetrievalHit(id="general", score=0.0, rank=1, manifest=registry["general"])
    email_hit = RetrievalHit(id="email", score=0.0, rank=2, manifest=registry["email"])
    # "email" only appears in the expanded pool, not the top-k shown by default.
    retrieval = RetrievalResult(
        query="did u see the one from dbs today",
        top=(general_hit,),
        recovered=True,
        expanded=(general_hit, email_hit),
        all_scores=(general_hit, email_hit),
        k=1,
    )

    class _FakeMessage:
        content = (
            '{"capabilities":[{"id":"email","reason":"sender reference","confidence":0.8}],'
            '"ordering":["email"],"insufficient_capability":null,"question":null,"confidence":0.8}'
        )

    class _FakeLLM:
        async def ainvoke(self, messages):
            return _FakeMessage()

    monkeypatch.setattr("core.llm.get_agent_llm", lambda *a, **k: _FakeLLM())

    decision = await plan_with_llm(
        "did u see the one from dbs today", _state("did u see the one from dbs today"), retrieval
    )
    assert decision is not None
    assert decision.capability_ids == ["email"]


@pytest.mark.asyncio
async def test_llm_planner_used_when_key_present(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "real-key")

    class _FakeMessage:
        content = (
            '{"capabilities":[{"id":"expenses","reason":"spend query","confidence":0.9}],'
            '"ordering":["expenses"],"insufficient_capability":null,"question":null,"confidence":0.9}'
        )

    class _FakeLLM:
        async def ainvoke(self, messages):
            return _FakeMessage()

    monkeypatch.setattr("core.llm.get_agent_llm", lambda *a, **k: _FakeLLM())
    from capabilities.registry import load_registry
    from capabilities.retrieval import BM25Index

    index = BM25Index(list(load_registry().values()))
    retrieval = index.retrieve_with_recovery("how much did I spend on food", k=5)
    decision = await plan_with_llm("how much did I spend on food", _state("how much did I spend on food"), retrieval)
    assert decision is not None
    assert decision.source == "llm"
    assert decision.capability_ids == ["expenses"]
