import pytest
from datetime import datetime, timezone as dt_timezone
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

from core.db import async_session_factory
from core.models import ExpenseTransaction, GroceryItem, ScheduledJob, UserProfile
from orchestrator.planner import deterministic_plan
from orchestrator.recipes import execute_recipe


def _state(message: str, user_id: int = 900001):
    return {
        "user_id": user_id,
        "active_domain": None,
        "last_decision": None,
        "pending_bus_stops": None,
        "messages": [HumanMessage(content=message)],
    }


async def _seed_profile(user_id: int) -> None:
    async with async_session_factory() as session:
        session.add(
            UserProfile(user_id=user_id, telegram_chat_id=user_id, current_timezone="Asia/Singapore")
        )
        await session.commit()


def test_recipe_triggers_in_planner():
    assert deterministic_plan("good morning!", _state("good morning!"), None).recipe == "briefing"
    assert deterministic_plan("where did my money go", _state("where did my money go"), None).recipe == "spend_autopsy"
    assert deterministic_plan("grocery run from Tampines", _state("grocery run from Tampines"), None).recipe == "grocery_run"
    assert deterministic_plan("what's my commute like tomorrow", _state("what's my commute like tomorrow"), None).recipe == "commute_conditions"
    assert deterministic_plan("track my bills", _state("track my bills"), None).recipe == "bill_watch"
    assert deterministic_plan("who is Albert Einstein", _state("who is Albert Einstein"), None).recipe is None


@pytest.mark.asyncio
async def test_briefing_recipe_output():
    user_id = 900002
    await _seed_profile(user_id)
    async with async_session_factory() as session:
        session.add(
            ScheduledJob(
                user_id=user_id,
                job_name="morning_briefing",
                cron_expression="0 8 * * *",
                instruction_prompt="morning briefing",
                timezone="Asia/Singapore",
                is_active=True,
            )
        )
        await session.commit()
    mock_search = AsyncMock()
    mock_search.ainvoke = AsyncMock(return_value=[])
    with patch("orchestrator.recipes.search_email_messages", mock_search):
        reply = await execute_recipe("briefing", _state("good morning", user_id))
    assert "No new financial emails" in reply
    assert "morning_briefing" in reply


@pytest.mark.asyncio
async def test_spend_autopsy_uses_sandbox():
    user_id = 900003
    await _seed_profile(user_id)
    async with async_session_factory() as session:
        now = datetime.now(dt_timezone.utc)
        session.add(ExpenseTransaction(user_id=user_id, amount=5.50, currency="SGD", merchant="Starbucks", category="Food", date=now, source_message_id="r1", is_verified=True))
        session.add(ExpenseTransaction(user_id=user_id, amount=12.00, currency="SGD", merchant="Grab", category="Transport", date=now, source_message_id="r2", is_verified=True))
        await session.commit()
    reply = await execute_recipe("spend_autopsy", _state("where did my money go", user_id))
    assert "Spend autopsy" in reply
    assert "17.50" in reply
    assert "Starbucks" in reply
    assert "Grab" in reply


@pytest.mark.asyncio
async def test_grocery_run_lists_items_and_route_note(monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    user_id = 900004
    await _seed_profile(user_id)
    async with async_session_factory() as session:
        session.add(GroceryItem(user_id=user_id, name="Milk", quantity="1L", category="Dairy"))
        await session.commit()
    reply = await execute_recipe(
        "grocery_run",
        _state("grocery run from Tampines to FairPrice", user_id),
    )
    assert "Milk × 1L" in reply
    assert "isn't configured" in reply


@pytest.mark.asyncio
async def test_bill_watch_lists_emails_payments_and_requirement():
    user_id = 900005
    await _seed_profile(user_id)
    async with async_session_factory() as session:
        now = datetime.now(dt_timezone.utc)
        session.add(ExpenseTransaction(user_id=user_id, amount=42.00, currency="SGD", merchant="M1", category="Bills", date=now, source_message_id="r3", is_verified=True))
        await session.commit()
    fake_emails = [
        {"sender": "alerts@m1.com.sg", "subject": "Your M1 bill is ready"},
    ]
    mock_search = AsyncMock()
    mock_search.ainvoke = AsyncMock(return_value=fake_emails)
    with patch("orchestrator.recipes.search_email_messages", mock_search):
        reply = await execute_recipe("bill_watch", _state("track my bills", user_id))
    assert "Your M1 bill is ready" in reply
    assert "Recent payments" in reply
    assert "due-date extraction" in reply


@pytest.mark.asyncio
async def test_commute_conditions_is_honest_without_keys(monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "google_maps_api_key", "")
    monkeypatch.setattr(settings, "tavily_api_key", "")
    reply = await execute_recipe(
        "commute_conditions",
        _state("commute from Tampines to Raffles Place tomorrow", 900006),
    )
    assert "Route planning isn't configured" in reply
    assert "Weather unavailable" in reply


@pytest.mark.asyncio
async def test_recipe_runs_through_graph():
    from orchestrator.graph import get_assistant_graph

    graph = get_assistant_graph()
    config = {"configurable": {"thread_id": "recipe_graph_001"}}
    state = {
        "messages": [HumanMessage(content="where did my money go")],
        "user_id": 900007,
        "current_timezone": "Asia/Singapore",
        "active_domain": None,
    }
    result = await graph.ainvoke(state, config=config)
    assert result.get("active_domain") == "expenses"
    assert "No expenses logged yet" in str(result["messages"][-1].content)
