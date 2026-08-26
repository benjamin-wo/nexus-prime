import pytest
from langchain_core.messages import HumanMessage
from unittest.mock import AsyncMock, patch

from capabilities.scheduled_content_delivery.tools import _fallback_briefing, build_daily_briefing


def test_fallback_briefing_formats_sections():
    news = "Summary: Big headline\n- Title (url): content\n- Title2 (url2): content2"
    markets = "Summary: Markets up\n- Title (url): content"
    text = _fallback_briefing(news, markets)
    assert "🌍 *Top Global News*" in text
    assert "📈 *Stock Market*" in text
    assert "Big headline" in text


def test_fallback_briefing_empty():
    text = _fallback_briefing("", "")
    assert text == "No briefing content could be fetched right now."


@pytest.mark.asyncio
async def test_build_daily_briefing_without_llm(monkeypatch):
    async def fake_search(query: str) -> str:
        if "stock" in query:
            return "Summary: Stocks rally\n- Tech (http://x): gains"
        return "Summary: Global headline\n- News (http://y): details"

    monkeypatch.setattr(
        "capabilities.scheduled_content_delivery.tools._search",
        fake_search,
    )
    text = await build_daily_briefing()
    assert "Top Global News" in text
    assert "Stock Market" in text
    assert "Global headline" in text


@pytest.mark.asyncio
async def test_plugin_registers_daily_briefing_job(monkeypatch):
    from orchestrator.router import ScheduledContentDeliveryPlugin

    class _FakeJob:
        id = 4242

    fake_schedule = AsyncMock(return_value=_FakeJob())
    monkeypatch.setattr("core.scheduler.schedule_proactive_task", fake_schedule)

    state = {
        "user_id": 1,
        "messages": [HumanMessage(content="Can you send me a daily morning summary of the top global news and stock market news")],
    }
    output = await ScheduledContentDeliveryPlugin().execute(state)
    assert "daily morning briefing" in output.message.content
    assert "4242" in output.message.content
    args = fake_schedule.await_args.kwargs
    assert args["job_name"] == "daily_briefing"
    assert args["cron_expression"] == "0 9 * * *"


@pytest.mark.asyncio
async def test_plugin_one_shot_briefing(monkeypatch):
    from orchestrator.router import ScheduledContentDeliveryPlugin

    monkeypatch.setattr(
        "capabilities.scheduled_content_delivery.tools.build_daily_briefing",
        AsyncMock(return_value="📰 Today's briefing content"),
    )
    state = {
        "user_id": 1,
        "messages": [HumanMessage(content="what's the market news today?")],
    }
    output = await ScheduledContentDeliveryPlugin().execute(state)
    assert "Today's briefing content" in output.message.content


def test_deterministic_plan_routes_daily_briefing():
    from orchestrator.planner import deterministic_plan

    state = {
        "user_id": 1,
        "active_domain": None,
        "last_decision": None,
        "messages": [HumanMessage(content="Can you send me a daily morning summary of the top global news and stock market news")],
    }
    decision = deterministic_plan(
        "Can you send me a daily morning summary of the top global news and stock market news",
        state,
        None,
    )
    assert "scheduled_content_delivery" in decision.capability_ids