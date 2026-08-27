import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import AIMessage, HumanMessage
from sqlmodel import select
from core.db import async_session_factory
from core.models import CapabilityRequestLog, UserProfile
from core.audit import log_capability_request, get_capability_leaderboard
from core.github_sync import sync_capability_gap_to_github_issue
from orchestrator.graph import get_assistant_graph

assistant_graph = get_assistant_graph()
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_capability_request_log_crud():
    async with async_session_factory() as session:
        profile = UserProfile(user_id=8001, telegram_chat_id=8001, current_timezone="UTC")
        session.add(profile)
        await session.commit()

        log_entry = CapabilityRequestLog(
            user_id=8001,
            requested_task="Book a flight to Paris",
            intent_type="unsupported_transaction",
            missing_capability_tags="flight_booking,travel",
        )
        session.add(log_entry)
        await session.commit()
        await session.refresh(log_entry)

        assert log_entry.id is not None
        assert log_entry.user_id == 8001
        assert "flight_booking" in log_entry.missing_capability_tags
        assert log_entry.created_at is not None


@pytest.mark.asyncio
async def test_capability_leaderboard_aggregation():
    async with async_session_factory() as session:
        profile = UserProfile(user_id=8002, telegram_chat_id=8002, current_timezone="UTC")
        session.add(profile)
        await session.commit()

    await log_capability_request(
        user_id=8002,
        requested_task="Schedule a team meeting at 3pm",
        intent_type="unsupported_transaction",
        tags=["calendar", "smart_home"],
    )
    await log_capability_request(
        user_id=8002,
        requested_task="Add appointment to calendar",
        intent_type="unsupported_transaction",
        tags=["calendar"],
    )

    leaderboard = await get_capability_leaderboard(limit=5)
    assert len(leaderboard) >= 1
    top_item = leaderboard[0]
    assert top_item["tag"] == "calendar"
    assert top_item["count"] == 2
    assert "Schedule" in top_item["sample_prompt"]


@pytest.mark.asyncio
async def test_github_issue_syncing_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    url = await sync_capability_gap_to_github_issue("calendar", "Schedule meeting", "unsupported_transaction")
    assert url is None


@pytest.mark.asyncio
async def test_github_issue_syncing_existing_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "dummy_token")
    monkeypatch.setenv("GITHUB_REPO", "owner/agent-learn")

    # Mock httpx.AsyncClient response for search existing issues
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = [{"title": "[Wishlist] Missing Capability: #calendar", "number": 42}]

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201

    mock_client_instance = AsyncMock()
    mock_client_instance.get.return_value = mock_get_resp
    mock_client_instance.post.return_value = mock_post_resp

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

    with patch("core.github_sync.httpx.AsyncClient", mock_client_cls):
        url = await sync_capability_gap_to_github_issue("calendar", "Schedule meeting", "unsupported_transaction")
        assert url == "https://github.com/owner/agent-learn/issues/42"
        mock_client_instance.post.assert_called_once()
        args, kwargs = mock_client_instance.post.call_args
        assert "/issues/42/comments" in args[0]


@pytest.mark.asyncio
async def test_supervisor_fallback_and_guardrail_routing():
    """Informational fallback: no LLM key configured in tests -> the
    rule-based fallback, no tools ever bound/called."""
    config = {"configurable": {"thread_id": "test_thread_cap_1001"}}
    state_info = {
        "messages": [HumanMessage(content="What is the capital of France?")],
        "user_id": 9001,
        "current_timezone": "UTC",
        "active_domain": None,
    }
    result_info = await assistant_graph.ainvoke(state_info, config=config)
    assert result_info.get("active_domain") == "agent"
    assert result_info.get("intent_type") is None


@pytest.mark.asyncio
async def test_agent_loop_logs_capability_gap_when_agent_calls_the_tool(monkeypatch):
    """Regression-shape coverage for the deleted GuardrailPolicy: unsupported
    transactional requests (calendar, bank transfer, ...) used to be caught
    by a hardcoded keyword matcher in orchestrator/router.py. That decision
    is now the agent's own judgment (orchestrator/agent_loop.py's
    log_capability_gap tool + system-prompt guidance) -- not deterministically
    testable without an LLM, so this scripts the model's tool call and
    verifies the WIRING: a log_capability_gap call actually reaches
    core.audit.log_capability_request and sets intent_type/
    missing_capability_tags on the returned Command for app/ingress.py's
    "+ Log Feature Request" button."""
    import orchestrator.agent_loop as agent_loop_module
    from orchestrator.agent_loop import agent_loop

    class _ScriptedLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "log_capability_gap",
                    "args": {"tag": "calendar", "expectation": "Schedule a meeting tomorrow"},
                    "id": "call_1",
                    "type": "tool_call",
                }])
            return AIMessage(content="I can't do that yet, but I've logged it as a feature request!")

    logged = []

    async def _fake_log_capability_request(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(agent_loop_module, "get_agent_llm", lambda *a, **k: _ScriptedLLM())
    monkeypatch.setattr(agent_loop_module.settings, "gemini_api_key", "fake-key-for-test")
    monkeypatch.setattr(agent_loop_module, "log_capability_request", _fake_log_capability_request)

    command = await agent_loop({
        "messages": [HumanMessage(content="Schedule a meeting on my calendar tomorrow")],
        "user_id": 9001,
        "current_timezone": "UTC",
        "active_domain": None,
    })

    assert logged, "log_capability_gap should have called log_capability_request"
    assert logged[0]["tags"] == ["calendar"]
    assert command.update.get("intent_type") == "unsupported_transaction"
    assert "calendar" in command.update.get("missing_capability_tags", [])


@pytest.mark.asyncio
async def test_webhook_missing_capabilities_command(monkeypatch):
    """A slash command's reply is delivered via send_telegram_message, not
    via the now-immediate (fire-and-forget) webhook HTTP response -- see
    app/webhook.py's docstring."""
    from unittest.mock import AsyncMock

    import app.ingress as ingress_module
    from app.ingress import telegram_ingress

    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(ingress_module, "send_telegram_message", sent)
    await telegram_ingress.handle_update({
        "update_id": 20001,
        "message": {
            "message_id": 601,
            "from": {"id": 9001, "first_name": "Admin"},
            "chat": {"id": 9001, "type": "private"},
            "text": "/missing_capabilities",
        },
    })

    assert sent.await_count >= 1
    reply_text = sent.await_args.args[1]
    assert "missing capability" in reply_text.lower()
