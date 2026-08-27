import asyncio

from fastapi import APIRouter, Request, HTTPException
from app.ingress import telegram_ingress
from core.config import settings

router = APIRouter()


@router.post("/webhook")
async def receive_telegram_webhook(request: Request):
    """
    High-performance Telegram Bot API Webhook Endpoint.
    Acts as a lightweight HTTP adapter that delegates payload processing,
    profile provisioning, callbacks, and slash commands to TelegramIngress.

    Fire-and-forget by design: the response body has no bearing on message
    delivery -- every reply to the user goes through an explicit
    send_telegram_message() call inside handle_update(), never through this
    endpoint's return value. So this acks Telegram immediately and lets
    handle_update() (including its own agent turn, which may now legitimately
    run for a while -- see orchestrator/agent_loop.py's MAX_TOOL_ROUNDS) run
    to completion in the background, instead of holding the HTTP request
    open for however long that takes. TelegramIngress.handle_update's own
    per-chat_id lock (see app/ingress.py) serializes overlapping updates for
    the same chat so two backgrounded turns never race the same checkpoint
    thread.
    """
    if settings.telegram_webhook_secret:
        received_secret = request.headers.get("x-telegram-bot-api-secret-token")
        if received_secret != settings.telegram_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    asyncio.create_task(telegram_ingress.handle_update(payload))
    return {"status": "ok", "queued": True}
