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
    get_bus_timings,
    list_my_boards,
    list_my_reminders,
    query_my_points_balances,
    search_my_email,
    summarize_board,
    transit_journey,
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
async def test_get_bus_timings_returns_live_message(monkeypatch):
    import capabilities.routes.tools as routes_tools

    async def fake_bus_query(text, pending_stops=None):
        assert text == "next bus from Tampines West CC"
        return {"kind": "arrivals", "message": "Tampines West CC (76161):\nBus 27: next 4 min"}

    monkeypatch.setattr(routes_tools, "handle_bus_query", fake_bus_query)

    result = await get_bus_timings.ainvoke({"query": "next bus from Tampines West CC"})
    assert "Bus 27: next 4 min" in result


@pytest.mark.asyncio
async def test_get_bus_timings_handles_ambiguous(monkeypatch):
    import capabilities.routes.tools as routes_tools

    async def fake_bus_query(text, pending_stops=None):
        return {"kind": "stop_ambiguous", "message": "Which stop did you mean?\n- Fullerton Sq (03011)"}

    monkeypatch.setattr(routes_tools, "handle_bus_query", fake_bus_query)

    result = await get_bus_timings.ainvoke({"query": "bus timing at Fullerton sq"})
    assert "Which stop did you mean?" in result
    assert "03011" in result


@pytest.mark.asyncio
async def test_transit_journey_formats_live_steps(monkeypatch):
    import capabilities.routes.journey as journey_module

    async def fake_journey(origin, destination):
        return {
            "origin": "Raffles Place",
            "destination": "Changi Airport",
            "total": "40 mins",
            "distance": "18 km",
            "steps": [{"kind": "transit", "line": "EWL", "departure_stop": "Raffles Place",
                       "arrival_stop": "Changi Airport", "duration_text": "40 mins",
                       "live_minutes": 2, "scheduled_time": None}],
            "map_url": "https://maps.example/dir",
        }

    monkeypatch.setattr(journey_module, "plan_transit_journey", fake_journey)

    result = await transit_journey.ainvoke({"origin": "Raffles Place", "destination": "Changi Airport"})
    assert "Raffles Place" in result
    assert "next in ~2 min" in result


@pytest.mark.asyncio
async def test_query_my_points_balances_formats_rows():
    from capabilities.memory.tools import upsert_points_balance

    await upsert_points_balance(user_id=9109, issuer="DBS", program="DBS Rewards", balance=12000)

    result = await query_my_points_balances.ainvoke({"user_id": 9109})
    assert "DBS Rewards" in result
    assert "12,000" in result


@pytest.mark.asyncio
async def test_general_plugin_agent_calls_bus_tool(monkeypatch):
    """The orchestrator agent can answer a bus-timing ask directly via its tools."""
    from langchain_core.messages import AIMessage as _AIMessage

    from orchestrator.router import GeneralPlugin
    import orchestrator.router as router_module

    class _FakeBusTool:
        name = "get_bus_timings"

        async def ainvoke(self, args):
            return "Fullerton Sq (03011, Fullerton Rd):\nBus 10: next 3 min, Bus 75: next 8 min"

    class _FakeToolCallingLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            self.tools = tools
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _AIMessage(content="", tool_calls=[{
                    "name": "get_bus_timings",
                    "args": {"query": "bus timing at Fullerton sq"},
                    "id": "call_bus_1",
                    "type": "tool_call",
                }])
            return _AIMessage(content="Bus 10 is due in 3 minutes at Fullerton Sq.")

    import capabilities.general.tools as general_tools

    monkeypatch.setattr(general_tools, "get_bus_timings", _FakeBusTool())
    monkeypatch.setattr(router_module, "get_agent_llm", lambda *a, **k: _FakeToolCallingLLM())
    monkeypatch.setattr(router_module.settings, "gemini_api_key", "fake-key-for-test")

    output = await GeneralPlugin().execute({
        "user_id": 9108,
        "messages": [HumanMessage(content="what time is the next bus at fullerton sq")],
    })

    assert "Bus 10" in str(output.message.content)
    tool_call_messages = [m for m in output.extra_messages if isinstance(m, _AIMessage) and m.tool_calls]
    assert tool_call_messages and tool_call_messages[0].tool_calls[0]["name"] == "get_bus_timings"


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


@pytest.mark.asyncio
async def test_general_plugin_surfaces_tool_call_provenance_for_persistence(monkeypatch):
    """Regression (#53): GeneralPlugin's tool loop calls real tools
    (summarize_board here) against a local `history` list that plan_router.py
    used to discard entirely -- only the final AIMessage(content=...) ever
    reached persisted state. That leaves the durable conversation transcript
    showing a reply grounded in real board data with NO tool invocation
    anywhere in it, indistinguishable from a hallucination to any later
    reader (the audit pipeline included -- this is what got #53 filed as a
    false-positive P1). PluginOutput.extra_messages must now carry the
    genuine AIMessage(tool_calls=...)/ToolMessage pair produced this turn."""
    from langchain_core.messages import AIMessage, ToolMessage
    import orchestrator.router as router_module
    from orchestrator.router import GeneralPlugin

    class _SpySummarizeBoard:
        name = "summarize_board"

        async def ainvoke(self, args):
            return "✈️ Bali Bachelor Party: Villa Samatha (booked), Finn's Beach Club (tbd)."

    class _FakeToolCallingLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "summarize_board",
                    "args": {"board_ref": "bali"},
                    "id": "call_1",
                    "type": "tool_call",
                }])
            return AIMessage(content="Here's what's on your Bali board.")

    import capabilities.general.tools as general_tools

    monkeypatch.setattr(general_tools, "summarize_board", _SpySummarizeBoard())
    monkeypatch.setattr(router_module, "get_agent_llm", lambda *a, **k: _FakeToolCallingLLM())
    monkeypatch.setattr(router_module.settings, "gemini_api_key", "fake-key-for-test")

    output = await GeneralPlugin().execute({
        "user_id": 9108,
        "messages": [HumanMessage(content="what is on my board")],
    })

    assert "Here's what's on your Bali board" in str(output.message.content)
    # The real tool call/result must be surfaced, not silently dropped.
    tool_call_messages = [m for m in output.extra_messages if isinstance(m, AIMessage) and m.tool_calls]
    tool_result_messages = [m for m in output.extra_messages if isinstance(m, ToolMessage)]
    assert tool_call_messages, "the tool-calling AIMessage must be in extra_messages"
    assert tool_call_messages[0].tool_calls[0]["name"] == "summarize_board"
    assert tool_result_messages, "the ToolMessage result must be in extra_messages"
    assert "Villa Samatha" in str(tool_result_messages[0].content)
