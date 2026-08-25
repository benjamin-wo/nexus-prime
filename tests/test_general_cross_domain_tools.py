"""Cross-domain read tools for GeneralPlugin: part of making "general" a real
conversational agent (full history + tools, the default landing zone for
ambiguous/cross-domain asks) rather than one narrow capability among many
that only ever sees the latest message. Deliberately READ-only -- writes
stay behind their own guarded plugins (expenses, whiteboard, reminders)."""
import pytest
from langchain_core.messages import HumanMessage

from app.dashboard_api import CreateWhiteboardRequest, create_whiteboard
from core.db import async_session_factory, init_db
from core.models import ScheduledJob, UserProfile
from capabilities.general.tools import (
    list_my_boards,
    list_my_reminders,
    search_my_email,
    summarize_board,
)


@pytest.fixture(autouse=True)
async def ensure_db():
    await init_db()


@pytest.mark.asyncio
async def test_list_my_reminders_reports_active_jobs():
    async with async_session_factory() as session:
        session.add(UserProfile(user_id=9101, telegram_chat_id=9101))
        session.add(ScheduledJob(
            user_id=9101,
            job_name="Weekly grocery reminder",
            cron_expression="0 9 * * 1",
            instruction_prompt="remind me to buy groceries",
        ))
        session.add(ScheduledJob(
            user_id=9101,
            job_name="Inactive job, should not appear",
            cron_expression="0 9 * * 1",
            instruction_prompt="stale",
            is_active=False,
        ))
        await session.commit()

    result = await list_my_reminders.ainvoke({"user_id": 9101})
    assert "Weekly grocery reminder" in result
    assert "Inactive job" not in result


@pytest.mark.asyncio
async def test_list_my_reminders_reports_none_when_empty():
    result = await list_my_reminders.ainvoke({"user_id": 9102})
    assert "No active reminders" in result


@pytest.mark.asyncio
async def test_list_my_boards_and_summarize_board():
    await create_whiteboard(
        payload=CreateWhiteboardRequest(title="Bali Bachelor Party", category="trip", template="blank"),
        user_id=9103,
    )

    boards = await list_my_boards.ainvoke({"user_id": 9103})
    assert "Bali Bachelor Party" in boards

    summary = await summarize_board.ainvoke({"board_ref": "bali", "user_id": 9103})
    assert "empty" in summary.lower() or "Bali" in summary


@pytest.mark.asyncio
async def test_summarize_board_reports_no_match():
    result = await summarize_board.ainvoke({"board_ref": "nonexistent board xyz", "user_id": 9104})
    assert "No board matching" in result


@pytest.mark.asyncio
async def test_search_my_email_formats_results(monkeypatch):
    import capabilities.email.tools as email_tools

    async def fake_search(user_id, custom_query=None, provider=None, latest=False):
        assert user_id == 9105
        return [{"sender": "flights@airline.com", "subject": "Your booking confirmation", "date": "2026-08-20"}]

    monkeypatch.setattr(email_tools, "search_email_messages", fake_search)

    result = await search_my_email.ainvoke({"query": "flight", "user_id": 9105})
    assert "flights@airline.com" in result
    assert "Your booking confirmation" in result


@pytest.mark.asyncio
async def test_search_my_email_reports_none_found(monkeypatch):
    import capabilities.email.tools as email_tools

    async def fake_search(user_id, custom_query=None, provider=None, latest=False):
        return []

    monkeypatch.setattr(email_tools, "search_email_messages", fake_search)

    result = await search_my_email.ainvoke({"query": "", "latest": True, "user_id": 9106})
    assert "No matching messages" in result


@pytest.mark.asyncio
async def test_general_plugin_binds_and_guards_all_cross_domain_tools():
    """The bounded tool loop must include the new tools, and the identity
    guard must force user_id for every one of them -- never trust a
    model-supplied user_id (matches the existing query_transactions guard)."""
    import inspect

    import orchestrator.router as router_module

    source = inspect.getsource(router_module.GeneralPlugin.execute)
    for tool_name in ("list_my_reminders", "list_my_boards", "summarize_board", "search_my_email"):
        assert tool_name in source, f"{tool_name} must be bound in GeneralPlugin's tool loop"
    assert '"list_my_reminders"' in source or "'list_my_reminders'" in source


@pytest.mark.asyncio
async def test_general_plugin_overrides_llm_supplied_user_id_for_new_tools(monkeypatch):
    """End-to-end identity guard check for the new tools, mirroring
    test_query_transactions.py's existing coverage for query_transactions."""
    from langchain_core.messages import AIMessage
    import orchestrator.router as router_module
    from orchestrator.router import GeneralPlugin

    captured = {}

    class _SpyListReminders:
        name = "list_my_reminders"

        async def ainvoke(self, args):
            captured["user_id"] = args.get("user_id")
            return "[reminders] spy observation"

    class _FakeToolCallingLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "list_my_reminders",
                    "args": {"user_id": 666666},
                    "id": "call_1",
                    "type": "tool_call",
                }])
            return AIMessage(content="here are your reminders")

    import capabilities.general.tools as general_tools

    monkeypatch.setattr(general_tools, "list_my_reminders", _SpyListReminders())
    monkeypatch.setattr(router_module, "get_agent_llm", lambda *a, **k: _FakeToolCallingLLM())
    monkeypatch.setattr(router_module.settings, "gemini_api_key", "fake-key-for-test")

    output = await GeneralPlugin().execute({
        "user_id": 9107,
        "messages": [HumanMessage(content="what reminders do I have?")],
    })

    assert captured["user_id"] == 9107
    assert captured["user_id"] != 666666
    assert "here are your reminders" in str(output.message.content)
