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


@pytest.mark.asyncio
async def test_file_issue_command_requires_description():
    """#14: bare /file-issue (no description) must not file anything -- just usage help."""
    from app.ingress import TelegramIngress

    res = await TelegramIngress().handle_slash_command("/file-issue", user_id=9001)
    assert res is not None
    assert res["status"] == "error"
    assert "Usage" in res["text"]


@pytest.mark.asyncio
async def test_file_issue_command_files_report_and_links_issue(monkeypatch):
    """#14: /file-issue <description> files through core.audit.report_user_filed_bug
    and replies with the filed issue link -- never through the LangGraph orchestrator."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import core.audit as audit_mod
    from app.ingress import TelegramIngress

    fake_log = SimpleNamespace(
        github_issue_url="https://github.com/owner/repo/issues/303",
        github_issue_number=303,
        title="Split icon missing on cockpit",
        severity="P2",
        subsystem="showcase",
    )
    mock_report = AsyncMock(return_value=fake_log)
    monkeypatch.setattr(audit_mod, "report_user_filed_bug", mock_report)

    res = await TelegramIngress().handle_slash_command(
        "/file-issue there is no icon for transaction splitting beside the edit icon",
        user_id=9002,
    )
    assert res is not None
    assert res["status"] == "ok"
    assert "https://github.com/owner/repo/issues/303" in res["text"]
    assert "#303" in res["text"]

    mock_report.assert_called_once()
    _, kwargs = mock_report.call_args
    assert kwargs["user_id"] == 9002
    assert "no icon for transaction splitting" in kwargs["description"]
    assert kwargs["channel"] == "telegram"


@pytest.mark.asyncio
async def test_file_issue_command_underscore_alias_and_unconfigured_github(monkeypatch):
    """The /file_issue alias works, and an unconfigured GitHub sync says so
    honestly instead of implying a public issue was filed."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import core.audit as audit_mod
    from app.ingress import TelegramIngress

    fake_log = SimpleNamespace(
        github_issue_url=None,
        github_issue_number=None,
        title="Cockpit bug",
        severity="P2",
        subsystem="general",
    )
    monkeypatch.setattr(audit_mod, "report_user_filed_bug", AsyncMock(return_value=fake_log))

    res = await TelegramIngress().handle_slash_command("/file_issue something is off", user_id=9003)
    assert res is not None
    assert res["status"] == "ok"
    assert "isn't configured" in res["text"]


def test_bug_filing_not_wired_into_general_chat_routing():
    """#14: filing a bug must only be reachable via the explicit /file-issue
    command -- never through general chat intent-matching (CAPABILITY_REGISTRY
    keyword routing or the LLM planner both dispatch off this same registry)."""
    from orchestrator.router import CAPABILITY_REGISTRY

    assert "bug_logging" not in CAPABILITY_REGISTRY
    assert "file_issue" not in CAPABILITY_REGISTRY
