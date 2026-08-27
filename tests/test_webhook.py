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


@pytest.mark.asyncio
async def test_email_command_lists_only_configured_providers():
    """The /email command must only link providers whose OAuth client credentials are configured."""
    from app.ingress import TelegramIngress
    from core.config import settings

    res = await TelegramIngress().handle_slash_command("/email", user_id=9001)
    assert res is not None
    text = res["text"]
    has_gmail_creds = bool(settings.google_client_id and settings.google_client_secret)
    has_ms_creds = bool(settings.microsoft_client_id and settings.microsoft_client_secret)
    if has_gmail_creds:
        assert "/auth/gmail" in text
    if has_ms_creds:
        assert "/auth/outlook" in text
    assert has_gmail_creds or has_ms_creds or "isn't configured" in text

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
    """Same reasoning as test_webhook_callback_query_resume: a slash
    command's reply is delivered via send_telegram_message (asserted here),
    not via the now-immediate webhook HTTP response."""
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
    assert "jobs" in reply_text.lower() or "reminder" in reply_text.lower()


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
