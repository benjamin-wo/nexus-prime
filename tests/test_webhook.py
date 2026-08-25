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

def test_webhook_callback_query_resume():
    payload = {
        "update_id": 10002,
        "callback_query": {
            "id": "cb_001",
            "from": {"id": 9001},
            "message": {"chat": {"id": 9001}},
            "data": '{"a": "confirm"}',
        },
    }
    response = client.post("/api/webhook", json=payload, headers=_webhook_headers())
    assert response.status_code == 200
    assert response.json()["resumed"] is True

def test_webhook_times_out_instead_of_hanging_forever(monkeypatch):
    """Regression (P0, production incident): a hung downstream call (e.g. a
    stalled LLM request -- see core/llm.py's LLM_REQUEST_TIMEOUT_SECONDS)
    must not hang the webhook response forever. Before this fix,
    receive_telegram_webhook fully awaited handle_update() with no
    timeout anywhere in the chain -- if handle_update never completed,
    the webhook never returned, Telegram never got its 200 OK, and it
    redelivered the same update on its own backoff schedule indefinitely.
    Verified against a real incident: the same chat was redelivered every
    ~60-130s for 10+ minutes with zero replies ever sent, while each
    redelivery's never-cancelled typing-indicator loop piled up until
    Telegram's sendChatAction calls were failing with 429s dozens/sec."""
    import asyncio
    from unittest.mock import AsyncMock

    import app.webhook as webhook_module
    from app.ingress import telegram_ingress

    monkeypatch.setattr(webhook_module, "WEBHOOK_PROCESSING_TIMEOUT_SECONDS", 0.05)

    async def _hang(payload):
        await asyncio.sleep(999)

    monkeypatch.setattr(telegram_ingress, "handle_update", _hang)
    monkeypatch.setattr(webhook_module, "send_telegram_message", AsyncMock(return_value=True))

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
    body = response.json()
    assert body["status"] == "ok"
    assert body.get("timeout") is True


def test_webhook_timeout_reports_an_operation_event(monkeypatch):
    """Regression: a webhook-level timeout cancels handle_update() before
    plan_dispatch() ever reaches schedule_turn_audit(), so a run of repeated
    timeouts was invisible to every audit/monitoring path (confirmed live:
    5 consecutive timeouts for one chat, zero audit entries -- the owner
    asked why the auto-audit never picked it up). The timeout handler must
    now explicitly report the incident through record_operation_event so it
    surfaces as a tracked (deduplicated) production bug instead of silently
    vanishing."""
    import asyncio
    from unittest.mock import AsyncMock

    import app.webhook as webhook_module
    import core.audit as audit_module
    from app.ingress import telegram_ingress

    monkeypatch.setattr(webhook_module, "WEBHOOK_PROCESSING_TIMEOUT_SECONDS", 0.05)

    async def _hang(payload):
        await asyncio.sleep(999)

    monkeypatch.setattr(telegram_ingress, "handle_update", _hang)
    monkeypatch.setattr(webhook_module, "send_telegram_message", AsyncMock(return_value=True))
    fake_record = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_module, "record_operation_event", fake_record)

    payload = {
        "update_id": 10005,
        "message": {
            "message_id": 504,
            "from": {"id": 9003, "first_name": "Test"},
            "chat": {"id": 9003, "type": "private"},
            "text": "bring up the upcoming bali trip for me to plan some stuff",
        },
    }
    response = client.post("/api/webhook", json=payload, headers=_webhook_headers())
    assert response.status_code == 200
    assert response.json().get("timeout") is True

    assert fake_record.await_count == 1
    call_kwargs = fake_record.await_args.kwargs
    assert call_kwargs["detection_source"] == "webhook_timeout"
    assert call_kwargs["user_id"] == 9003
    assert call_kwargs["fingerprint"] == "op_webhook_processing_timeout"
    assert call_kwargs["severity"] == "P1"


def test_webhook_jobs_command():
    payload = {
        "update_id": 10003,
        "message": {
            "message_id": 502,
            "from": {"id": 9001},
            "chat": {"id": 9001},
            "text": "/jobs",
        },
    }
    response = client.post("/api/webhook", json=payload, headers=_webhook_headers())
    assert response.status_code == 200
    assert "jobs" in response.json()
