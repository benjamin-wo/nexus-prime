import pytest
from datetime import datetime
from langchain_core.messages import AIMessage, HumanMessage

from core.db import async_session_factory
from core.models import ExpenseTransaction, IncomeTransaction, UserProfile
from capabilities.expenses.tools import query_unified_transactions
from capabilities.general.tools import query_transactions
from orchestrator.agent_loop import agent_loop


USER_ID = 4242
OTHER_USER_ID = 666666


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
        # A real transaction under the id an attacker-controlled model arg
        # would try to read below -- if identity_bound ever failed to
        # override, this merchant name would leak into the reply.
        session.add(ExpenseTransaction(
            user_id=OTHER_USER_ID,
            amount=9999.00,
            currency="SGD",
            merchant="Confidential Other-User Purchase",
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
    """First call emits a tool_call with a fabricated user_id belonging to a
    DIFFERENT real user with real data; second call answers from whatever
    the tool actually returned."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "query_transactions",
                "args": {"direction": "all", "user_id": OTHER_USER_ID},
                "id": "call_1",
                "type": "tool_call",
            }])
        tool_result = str(messages[-1].content)
        return AIMessage(content=f"here's your ledger: {tool_result}")


@pytest.mark.asyncio
async def test_agent_loop_overrides_llm_supplied_user_id(monkeypatch):
    """End-to-end guardrail test for core/tool_guard.py's identity_bound:
    drives a real tool call (the actual query_transactions @tool, decorated
    with @identity_bound in capabilities/general/tools.py -- not a mock
    standing in for it) through agent_loop with a model that tries to read
    a different real user's ledger, and confirms the DB read actually lands
    on the trusted caller's own data. This replaces the old GeneralPlugin
    tool-loop's hardcoded allowlist override, deleted along with
    orchestrator/router.py -- the guarantee now lives in the tool itself."""
    await _seed_ledger()

    import orchestrator.agent_loop as agent_loop_module

    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: _FakeToolCallingLLM())
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")

    command = await agent_loop({
        "user_id": USER_ID,
        "messages": [HumanMessage(content="how much did I spend this month?")],
    })

    reply = str(command.update["messages"][-1].content)
    assert "Starbucks" in reply or "FairPrice" in reply, f"reply should reflect USER_ID's own ledger: {reply!r}"
    assert "Confidential Other-User Purchase" not in reply, (
        "identity_bound failed to override the model-supplied user_id -- "
        "another user's transaction leaked into the reply"
    )
    assert command.update["active_domain"] == "agent"
