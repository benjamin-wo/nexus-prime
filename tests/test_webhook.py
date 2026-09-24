import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def _webhook_headers():
    from core.config import settings
    if settings.telegram_webhook_secret:
        return {"X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret}
    return {}

def test_health_check_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_webhook_text_message():
    payload = {
        "update_id": 10001,
        "message": {
            "message_id": 501,
            "from": {"id": 9001, "first_name": "Test"},
            "chat": {"id": 9001, "type": "private"},
            "text": "Check my gmail inbox for receipts",
        },
    }
    response = client.post("/api/webhook", json=payload, headers=_webhook_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_slash_command_routes_through_graph(monkeypatch):
    """Pure LLM agent: /jobs must reach the agent graph (which replies via the
    LLM or its honest fallback) instead of the old deterministic handler that
    returned a jobs listing without any model call."""
    from unittest.mock import AsyncMock

    import app.ingress as ingress_module
    from app.ingress import telegram_ingress

    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(ingress_module, "send_telegram_message", sent)
    monkeypatch.setattr(ingress_module, "send_telegram_chat_action", AsyncMock())

    await telegram_ingress.handle_update({
        "update_id": 10005,
        "message": {
            "message_id": 504,
            "from": {"id": 9003},
            "chat": {"id": 9003, "type": "private"},
            "text": "/jobs",
        },
    })

    assert sent.await_count >= 1
    reply_text = sent.await_args.args[1]
    assert "No jobs" not in reply_text
    assert "usage" not in reply_text.lower()

@pytest.mark.asyncio
async def test_webhook_callback_query_resume():
    """app/webhook.py's endpoint itself is fire-and-forget now (see
    test_webhook_endpoint_acks_immediately_and_backgrounds_the_turn below),
    so its HTTP response can no longer carry a per-turn result like
    "resumed" -- that contract moved entirely to TelegramIngress.
    handle_callback_query()'s own return value, exercised directly here."""
    from app.ingress import telegram_ingress

    result = await telegram_ingress.handle_callback_query({
        "id": "cb_001",
        "from": {"id": 9001},
        "message": {"chat": {"id": 9001}},
        "data": '{"a": "confirm"}',
    })
    assert result["status"] == "ok"
    assert result["resumed"] is True


@pytest.mark.asyncio
async def test_webhook_jobs_command(monkeypatch):
    """Slash commands reach the agent graph now; without a valid LLM key in
    tests the loop's honest-error fallback answers instead of the old
    deterministic jobs listing. The point of the assertion: the turn is
    handled by the graph path and the user still gets a reply."""
    from unittest.mock import AsyncMock

    import app.ingress as ingress_module
    from app.ingress import telegram_ingress

    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(ingress_module, "send_telegram_message", sent)
    await telegram_ingress.handle_update({
        "update_id": 10003,
        "message": {
            "message_id": 502,
            "from": {"id": 9001},
            "chat": {"id": 9001},
            "text": "/jobs",
        },
    })

    assert sent.await_count >= 1
    reply_text = sent.await_args.args[1]
    assert reply_text  # some reply reached the user
    assert "Usage: /run_now" not in reply_text  # old deterministic handler text


def test_webhook_endpoint_acks_immediately_and_backgrounds_the_turn(monkeypatch):
    """The webhook response body has no bearing on message delivery -- every
    reply goes through an explicit send_telegram_message() call inside
    handle_update(), never through this endpoint's return value (see
    app/webhook.py's docstring). So the endpoint just needs to ack Telegram
    right away and hand the actual turn off to a background task, rather
    than awaiting it inline -- confirmed here by making handle_update hang
    indefinitely and asserting the HTTP response still returns promptly."""
    import asyncio

    import app.webhook as webhook_module
    from app.ingress import telegram_ingress

    hang_started = asyncio.Event()

    async def _hang(payload):
        hang_started.set()
        await asyncio.sleep(999)

    monkeypatch.setattr(telegram_ingress, "handle_update", _hang)

    payload = {
        "update_id": 10004,
        "message": {
            "message_id": 503,
            "from": {"id": 9002, "first_name": "Test"},
            "chat": {"id": 9002, "type": "private"},
            "text": "Can you see if there are any flight bookings in my email",
        },
    }
    response = client.post("/api/webhook", json=payload, headers=_webhook_headers())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "queued": True}
