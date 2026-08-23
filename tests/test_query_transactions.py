import pytest
from datetime import datetime
from langchain_core.messages import AIMessage, HumanMessage

from core.db import async_session_factory
from core.models import ExpenseTransaction, IncomeTransaction, UserProfile
from capabilities.expenses.tools import query_unified_transactions
from capabilities.general.tools import query_transactions
from orchestrator.router import GeneralPlugin


USER_ID = 4242


async def _seed_ledger():
    async with async_session_factory() as session:
        session.add(UserProfile(
            user_id=USER_ID,
            telegram_chat_id=USER_ID,
            current_timezone="Asia/Singapore",
        ))
        session.add(ExpenseTransaction(
            user_id=USER_ID,
            amount=12.50,
            currency="SGD",
            merchant="Starbucks",
            category="Dining",
            date=datetime(2026, 8, 10, 12, 0),
        ))
        session.add(ExpenseTransaction(
            user_id=USER_ID,
            amount=40.00,
            currency="SGD",
            merchant="FairPrice",
            category="Groceries",
            date=datetime(2026, 8, 15, 9, 30),
        ))
        session.add(IncomeTransaction(
            user_id=USER_ID,
            amount=2000.00,
            currency="SGD",
            source="Acme Corp",
            category="Salary",
            date=datetime(2026, 8, 1, 8, 0),
        ))
        # Other user's rows must never leak into queries.
        session.add(ExpenseTransaction(
            user_id=999999,
            amount=500.00,
            currency="SGD",
            merchant="Other User Spend",
            category="Shopping",
            date=datetime(2026, 8, 20, 10, 0),
        ))
        await session.commit()


@pytest.mark.asyncio
async def test_unified_query_merges_both_directions_and_nets():
    await _seed_ledger()
    ledger = await query_unified_transactions(
        user_id=USER_ID,
        direction="all",
        since_date="2026-08-01T00:00:00",
        until_date="2026-09-01T00:00:00",
    )

    assert ledger["money_out"]["SGD"]["total"] == pytest.approx(52.50)
    assert ledger["money_out"]["SGD"]["count"] == 2
    assert ledger["money_in"]["SGD"]["total"] == pytest.approx(2000.00)
    assert ledger["net"]["SGD"] == pytest.approx(1947.50)

    titles = [item["title"] for item in ledger["items"]]
    assert "Acme Corp" in titles and "FairPrice" in titles
    assert ledger["items"][0]["date"] >= ledger["items"][-1]["date"]


@pytest.mark.asyncio
async def test_unified_query_direction_and_text_filters():
    await _seed_ledger()

    outgoing_only = await query_unified_transactions(user_id=USER_ID, direction="outgoing")
    assert all(item["direction"] == "outgoing" for item in outgoing_only["items"])
    assert not outgoing_only["money_in"]

    salary = await query_unified_transactions(user_id=USER_ID, search_text="acme")
    assert [item["title"] for item in salary["items"]] == ["Acme Corp"]

    dining = await query_unified_transactions(user_id=USER_ID, categories=["Dining"])
    assert [item["category"] for item in dining["items"]] == ["Dining"]


@pytest.mark.asyncio
async def test_query_transactions_tool_formats_summary():
    await _seed_ledger()
    report = await query_transactions.ainvoke({
        "direction": "all",
        "user_id": USER_ID,
        "since_date": "2026-08-01T00:00:00",
    })

    assert "Money out: -SGD 52.50 (2 tx)" in report
    assert "Money in: +SGD 2000.00 (1 tx)" in report
    assert "Net (SGD): +1947.50" in report
    assert "-SGD 12.50 — Starbucks (Dining)" in report


class _FakeToolCallingLLM:
    """First call emits a tool_call with a fabricated user_id; second call answers."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "query_transactions",
                "args": {"direction": "all", "user_id": 666666},
                "id": "call_1",
                "type": "tool_call",
            }])
        return AIMessage(content="ledger answered")


@pytest.mark.asyncio
async def test_general_plugin_overrides_llm_supplied_user_id(monkeypatch):
    await _seed_ledger()
    captured = []

    class _SpyTool:
        name = "query_transactions"

        async def ainvoke(self, args):
            captured.append(dict(args))
            return "[transactions] spy observation"

    import capabilities.general.tools as general_tools
    import orchestrator.router as router_module

    monkeypatch.setattr(general_tools, "query_transactions", _SpyTool())
    monkeypatch.setattr(router_module, "get_agent_llm", lambda *a, **k: _FakeToolCallingLLM())
    monkeypatch.setattr(router_module.settings, "gemini_api_key", "fake-key-for-test")

    output = await GeneralPlugin().execute({
        "user_id": USER_ID,
        "messages": [HumanMessage(content="how much did I spend this month?")],
    })

    assert captured, "query_transactions should have been invoked"
    assert captured[0]["user_id"] == USER_ID
    assert captured[0]["user_id"] != 666666
    assert "ledger answered" in str(output.message.content)
    assert output.state_update == {"active_domain": "general"}
