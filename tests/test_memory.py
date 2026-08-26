import pytest
from langchain_core.messages import HumanMessage
from unittest.mock import AsyncMock, patch

from capabilities.memory.tools import (
    _normalize_issuer,
    _regex_extract_points,
    extract_points_balance,
    query_points_balances,
    upsert_points_balance,
)


def test_normalize_issuer():
    assert _normalize_issuer("citibank") == "Citibank"
    assert _normalize_issuer("CITI") == "Citibank"
    assert _normalize_issuer("krisflyer") == "KrisFlyer"
    assert _normalize_issuer("dbs") == "DBS"
    assert _normalize_issuer("posb") == "DBS"
    assert _normalize_issuer("random") == "Random"


def test_regex_extract_points():
    result = _regex_extract_points("I have 12000 DBS reward points expiring next month")
    assert result["balance"] == 12000.0
    assert result["issuer"] == "DBS"
    assert _regex_extract_points("no points here") is None


def test_regex_extract_miles():
    result = _regex_extract_points("my Citibank miles balance is 45000")
    assert result["balance"] == 45000.0
    assert result["issuer"] == "Citibank"


@pytest.mark.asyncio
async def test_extract_points_balance_falls_back_to_regex_without_llm():
    result = await extract_points_balance("I have 12000 DBS points")
    assert result["balance"] == 12000.0
    assert result["issuer"] == "DBS"


@pytest.mark.asyncio
async def test_upsert_updates_existing_balance_not_append():
    first = await upsert_points_balance(user_id=777001, issuer="DBS", program="DBS Rewards", balance=12000)
    second = await upsert_points_balance(user_id=777001, issuer="DBS", program="DBS Rewards", balance=13500)
    assert first.id == second.id
    rows = await query_points_balances(user_id=777001)
    assert len(rows) == 1
    assert rows[0]["balance"] == 13500.0
    assert rows[0]["program"] == "DBS Rewards"


@pytest.mark.asyncio
async def test_query_returns_all_balances():
    await upsert_points_balance(user_id=777002, issuer="Citibank", balance=45000)
    await upsert_points_balance(user_id=777002, issuer="KrisFlyer", balance=8200)
    rows = await query_points_balances(user_id=777002)
    issuers = {r["issuer"] for r in rows}
    assert issuers == {"Citibank", "KrisFlyer"}


@pytest.mark.asyncio
async def test_memory_plugin_records_balance(monkeypatch):
    from orchestrator.router import MemoryPlugin

    fake = AsyncMock(return_value={"balance": 12000.0, "issuer": "DBS", "program": "DBS Rewards"})
    monkeypatch.setattr("capabilities.memory.tools.extract_points_balance", fake)
    state = {
        "user_id": 777003,
        "messages": [HumanMessage(content="I have 12000 DBS points")],
    }
    output = await MemoryPlugin().execute(state)
    assert "DBS Rewards" in output.message.content
    assert "12,000" in output.message.content


@pytest.mark.asyncio
async def test_memory_plugin_recall_empty(monkeypatch):
    from orchestrator.router import MemoryPlugin

    monkeypatch.setattr(
        "capabilities.memory.tools.query_points_balances",
        AsyncMock(return_value=[]),
    )
    state = {
        "user_id": 777003,
        "messages": [HumanMessage(content="what are my points balances?")],
    }
    output = await MemoryPlugin().execute(state)
    assert "don't have any points" in output.message.content


def test_deterministic_plan_routes_memory():
    from orchestrator.planner import deterministic_plan

    state = {
        "user_id": 1,
        "active_domain": None,
        "last_decision": None,
        "messages": [HumanMessage(content="what are my points balances?")],
    }
    decision = deterministic_plan("what are my points balances?", state, None)
    assert "memory" in decision.capability_ids