from fastapi import APIRouter, Request, HTTPException
from app.ingress import telegram_ingress
from core.background import fire_and_forget
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

    Regression (live incident, chat=149917165): a bare
    asyncio.create_task(...) with the Task discarded is silently
    GC-eligible mid-await (stdlib docs: "the event loop only keeps weak
    references to tasks") -- confirmed via Railway logs, the turn's own
    internal error fallback fired ("[AGENT_LOOP] tool loop failed, using
    fallback") but the reply was never sent and nothing else was ever
    logged, meaning the task itself stopped executing before it could get
    that far. core.background.fire_and_forget keeps a strong reference
    until the task actually completes.
    """
    if settings.telegram_webhook_secret:
        received_secret = request.headers.get("x-telegram-bot-api-secret-token")
        if received_secret != settings.telegram_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    fire_and_forget(telegram_ingress.handle_update(payload))
    return {"status": "ok", "queued": True}
