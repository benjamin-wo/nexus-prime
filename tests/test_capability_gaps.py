import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage
from sqlmodel import select
from core.db import async_session_factory
from core.models import CapabilityRequestLog, UserProfile
from core.audit import log_capability_request, get_capability_leaderboard
from core.github_sync import sync_capability_gap_to_github_issue
from orchestrator.graph import assistant_graph
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
    config = {"configurable": {"thread_id": "test_thread_cap_1001"}}

    # 1. Test Informational fallback -> general_subagent
    state_info = {
        "messages": [HumanMessage(content="What is the capital of France?")],
        "user_id": 9001,
        "current_timezone": "UTC",
        "active_domain": None,
    }
    result_info = await assistant_graph.ainvoke(state_info, config=config)
    assert result_info.get("active_domain") == "general"
    assert result_info.get("intent_type") == "informational_fallback"

    # 2. Test Unsupported transaction -> FINISH with refusal and telemetry tags
    state_tx = {
        "messages": [HumanMessage(content="Schedule a meeting on my calendar tomorrow")],
        "user_id": 9001,
        "current_timezone": "UTC",
        "active_domain": None,
    }
    result_tx = await assistant_graph.ainvoke(state_tx, config=config)
    assert result_tx.get("intent_type") == "unsupported_transaction"
    assert "calendar" in result_tx.get("missing_capability_tags", [])


def test_webhook_missing_capabilities_command():
    payload = {
        "update_id": 20001,
        "message": {
            "message_id": 601,
            "from": {"id": 9001, "first_name": "Admin"},
            "chat": {"id": 9001, "type": "private"},
            "text": "/missing_capabilities",
        },
    }
    response = client.post("/api/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "leaderboard" in response.json()

