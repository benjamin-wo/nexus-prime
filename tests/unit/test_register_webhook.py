import json

import httpx
import pytest

from nexus.channels.telegram import register


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/nexus")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:tok")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "shh")
    monkeypatch.setenv("ADMIN_TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "nexus.example.app")


def fake_api(calls: list[tuple[str, dict[str, object]]]) -> httpx.AsyncClient:
    state = {"url": "https://old.example.app/api/webhook"}

    def handle(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        calls.append((method, body))
        if method == "setWebhook":
            state["url"] = body["url"]
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": {"url": state["url"]}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def test_shows_but_does_not_change_without_yes(capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    assert await register.main([], fake_api(calls)) == 0
    assert [m for m, _ in calls] == ["getWebhookInfo"]
    out = capsys.readouterr().out
    assert "current webhook: https://old.example.app/api/webhook" in out
    assert "would set: https://nexus.example.app/telegram/webhook" in out


async def test_sets_webhook_with_secret(capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    assert await register.main(["--yes"], fake_api(calls)) == 0
    method, body = calls[1]
    assert method == "setWebhook"
    assert body == {
        "url": "https://nexus.example.app/telegram/webhook",
        "secret_token": "shh",
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    }
    assert "webhook set: https://nexus.example.app/telegram/webhook" in capsys.readouterr().out


async def test_rollback_and_https_only() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    old = "https://old.example.app/api/webhook"
    assert await register.main(["--yes", "--url", old], fake_api(calls)) == 0
    assert calls[1][1]["url"] == old
    assert await register.main(["--url", "http://insecure"], fake_api([])) == 2
