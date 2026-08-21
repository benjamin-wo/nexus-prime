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
