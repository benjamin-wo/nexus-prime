"""Local end-to-end webhook smoke test (offline: test keys, no live APIs).

Boots the real FastAPI app, drives real Telegram webhook payloads through the
full ingress -> planner -> plugin -> send path, and captures the outbound text.
"""

from __future__ import annotations

import os

os.environ.update(
    {
        "TELEGRAM_BOT_TOKEN": "test_bot_token",
        "TELEGRAM_WEBHOOK_SECRET": "",
        "DEEPSEEK_API_KEY": "test_deepseek_key",
        "GEMINI_API_KEY": "test_google_key",
        "TAVILY_API_KEY": "",
        "GOOGLE_MAPS_API_KEY": "",
        "LTA_ACCOUNT_KEY": "",
        "GOOGLE_CLIENT_ID": "",
        "DATABASE_URL": "sqlite+aiosqlite:////tmp/nexus_smoke.db",
        "E2B_API_KEY": "",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _payload(message: str, uid: int) -> dict:
    return {
        "update_id": uid,
        "message": {
            "message_id": uid,
            "from": {"id": uid, "first_name": "Smoke"},
            "chat": {"id": uid, "type": "private"},
            "text": message,
        },
    }


def main() -> None:
    import app.ingress as ingress

    captured: list[dict] = []

    async def _silent_api_call(method: str, payload: dict) -> bool:
        return False

    async def _capture_send(chat_id: int, text: str, reply_markup=None) -> bool:
        captured.append({"chat_id": chat_id, "text": text})
        return True

    ingress.telegram_api_call = _silent_api_call
    ingress.send_telegram_message = _capture_send

    cases = [
        ("when's my next bus?", "bus query (fast path)"),
        ("check my gmail for receipts", "email"),
        (
            "how much did I spend on food last month, and does that put my Japan trip budget at risk?",
            "cross-domain + budget insufficiency",
        ),
        ("book a table for two at 7", "pure refusal"),
        ("and what about next month?", "referent continuation", 555003),
    ]

    with TestClient(app) as client:
        health = client.get("/health")
        print(f"health: {health.status_code}")
        for idx, case in enumerate(cases, start=1):
            message, label = case[0], case[1]
            captured.clear()
            uid = case[2] if len(case) > 2 else 555000 + idx
            response = client.post("/api/webhook", json=_payload(message, uid))
            print(f"\n[{label}] webhook={response.status_code} {response.json()}")
            for item in captured:
                print("  ->", item["text"].replace("\n", " | ")[:240])
            if not captured:
                print("  -> (no outbound message captured)")


if __name__ == "__main__":
    main()
