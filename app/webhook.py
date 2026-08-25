import asyncio

from fastapi import APIRouter, Request, HTTPException
from app.ingress import send_telegram_message, telegram_ingress
from core.config import settings

router = APIRouter()

# A stalled call anywhere downstream (e.g. a hung LLM request -- see
# core/llm.py's LLM_REQUEST_TIMEOUT_SECONDS) must not hang this response
# forever: Telegram never gets its 200 OK if we do, so it redelivers the
# same update on its own backoff schedule, piling up duplicate in-flight
# processing (and duplicate typing-indicator loops) for one stuck chat.
# Comfortably under Telegram's own webhook timeout.
WEBHOOK_PROCESSING_TIMEOUT_SECONDS = 45.0


@router.post("/webhook")
async def receive_telegram_webhook(request: Request):
    """
    High-performance Telegram Bot API Webhook Endpoint.
    Acts as a lightweight HTTP adapter that delegates payload processing,
    profile provisioning, callbacks, and slash commands to TelegramIngress.
    """
    if settings.telegram_webhook_secret:
        received_secret = request.headers.get("x-telegram-bot-api-secret-token")
        if received_secret != settings.telegram_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    try:
        return await asyncio.wait_for(
            telegram_ingress.handle_update(payload),
            timeout=WEBHOOK_PROCESSING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        # asyncio.wait_for cancels the still-running handle_update() task and
        # waits for the cancellation to unwind before raising, so
        # TelegramIngress.handle_update's own try/finally still runs here --
        # the per-update typing-indicator loop gets stopped, not orphaned.
        chat_id = (
            (payload.get("message") or payload.get("edited_message") or {})
            .get("chat", {})
            .get("id")
        )
        if chat_id:
            try:
                await send_telegram_message(
                    chat_id,
                    "Still working on that — it's taking longer than expected. Hang tight.",
                )
            except Exception:  # noqa: BLE001 - never let the timeout handler itself hang the response
                pass
        # Regression: this cancellation happens mid-flight through
        # handle_update(), before plan_dispatch() ever reaches the point
        # where it schedules a conversation audit -- so a run of webhook
        # timeouts was previously invisible to every audit/monitoring path
        # (confirmed live: 5 consecutive timeouts for one chat, zero audit
        # entries). Report it explicitly instead of leaving it silent.
        try:
            from core.audit import record_operation_event

            await record_operation_event(
                subsystem="webhook",
                error_context=(
                    f"Webhook processing exceeded {WEBHOOK_PROCESSING_TIMEOUT_SECONDS}s "
                    f"and was cancelled (chat_id={chat_id})."
                ),
                detection_source="webhook_timeout",
                user_id=chat_id,
                fingerprint="op_webhook_processing_timeout",
                severity="P1",
                title="Webhook processing repeatedly exceeds its own timeout",
            )
        except Exception:  # noqa: BLE001 - audit reporting must never break the timeout response
            pass
        return {"status": "ok", "processed": False, "timeout": True}
