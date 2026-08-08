from langchain_core.messages import HumanMessage
import pytest

from capabilities.registry import load_registry
from capabilities.retrieval import BM25Index
from orchestrator.planner import deterministic_plan
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
