from fastapi import APIRouter, Request, HTTPException
from app.ingress import telegram_ingress

router = APIRouter()


@router.post("/webhook")
async def receive_telegram_webhook(request: Request):
    """
    High-performance Telegram Bot API Webhook Endpoint.
    Acts as a lightweight HTTP adapter that delegates payload processing,
    profile provisioning, callbacks, and slash commands to TelegramIngress.
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    response = await telegram_ingress.handle_update(payload)
    return response
