"""POST /telegram/webhook.

Accepts an update only with Telegram's secret token, records its update_id so a
redelivery is ignored, answers 200 at once and handles it in the background.
Only allow-listed users in private chats are served.
"""

import hmac
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from nexus.agent.service import AgentService, Reply
from nexus.agent.tools import UowFactory
from nexus.application.access import create_invite
from nexus.application.clock import utcnow
from nexus.application.inbound import claim_event
from nexus.application.users import RegisterUser, register_user
from nexus.channels.telegram.client import MAX_DOWNLOAD, TelegramClient
from nexus.domain.errors import Forbidden
from nexus.domain.ledger import Role, UserId
from nexus.settings import Settings

log = logging.getLogger(__name__)
router = APIRouter()

PRIVATE = "This is a private assistant."
FAILED = "Sorry, something went wrong on my side. Please try again."


@dataclass(frozen=True, slots=True)
class TelegramRuntime:
    settings: Settings
    uow: UowFactory
    service: AgentService
    client: TelegramClient


def _runtime(request: Request) -> TelegramRuntime:
    runtime: TelegramRuntime | None = getattr(request.app.state, "telegram", None)
    if runtime is None:
        raise HTTPException(status_code=404)
    return runtime


@router.post("/telegram/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> dict[str, bool]:
    runtime = _runtime(request)
    secret = runtime.settings.telegram_webhook_secret
    given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret is None or not hmac.compare_digest(
        given.encode(), secret.get_secret_value().encode()
    ):
        raise HTTPException(status_code=401)
    try:
        update = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400) from exc
    update_id = update.get("update_id") if isinstance(update, dict) else None
    if not isinstance(update_id, int):
        raise HTTPException(status_code=400)
    if not await claim_event(runtime.uow(), "telegram", str(update_id)):
        return {"ok": True}
    background.add_task(handle_update, runtime, update)
    return {"ok": True}


async def _actor(runtime: TelegramRuntime, sender: dict[str, Any], chat_id: int) -> UserId | None:
    telegram_id = sender.get("id")
    if (
        not isinstance(telegram_id, int)
        or telegram_id not in runtime.settings.allowed_telegram_user_ids
    ):
        return None
    is_owner = telegram_id == runtime.settings.admin_telegram_chat_id
    registration = await register_user(
        runtime.uow(),
        RegisterUser(
            telegram_user_id=telegram_id,
            telegram_chat_id=chat_id,
            home_currency=runtime.settings.default_home_currency,
            timezone=runtime.settings.default_timezone,
            role=Role.OWNER if is_owner else Role.MEMBER,
        ),
    )
    return registration.user.id


async def _send(runtime: TelegramRuntime, chat_id: int, replies: list[Reply]) -> None:
    for reply in replies:
        await runtime.client.send_message(chat_id, reply.text, reply.buttons or None)


async def handle_update(runtime: TelegramRuntime, update: dict[str, Any]) -> None:
    chat_id: int | None = None
    try:
        if "callback_query" in update:
            await _callback(runtime, update["callback_query"])
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return  # edits, channel posts, etc. are ignored
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return
        chat_id = int(chat["id"])
        actor = await _actor(runtime, message.get("from") or {}, chat_id)
        if actor is None:
            await runtime.client.send_message(chat_id, PRIVATE)
            return
        ref = f"telegram:{chat_id}:{message.get('message_id')}"
        if photos := message.get("photo"):
            await _photo(runtime, actor, chat_id, photos, message.get("caption"), ref)
            return
        text = (message.get("text") or "").strip()
        if not text:
            await runtime.client.send_message(chat_id, "I can read text and receipt photos.")
            return
        command = text.split()[0].split("@")[0]
        if command == "/app":
            await _open_app(runtime, chat_id)
            return
        if command == "/invite":
            await runtime.client.send_message(chat_id, await _invite(runtime, actor))
            return
        if command in {"/start", "/menu", "/help"}:
            await _send(runtime, chat_id, await runtime.service.quick_action(actor, "menu"))
            return
        await _send(runtime, chat_id, await runtime.service.handle_text(actor, text, ref))
    except Exception:
        log.exception("failed to handle telegram update %s", update.get("update_id"))
        if chat_id is not None:
            try:
                await runtime.client.send_message(chat_id, FAILED)
            except Exception:
                log.exception("could not report the failure to the user")


APP_LABEL = "Open Nexus"


async def _open_app(runtime: TelegramRuntime, chat_id: int) -> None:
    origin = runtime.settings.public_origin
    if origin is None:
        await runtime.client.send_message(chat_id, "The web app isn't set up yet.")
        return
    await runtime.client.send_app_button(
        chat_id,
        "Your dashboard and ledger. It opens here in Telegram, already signed in.",
        APP_LABEL,
        f"{origin}/",
    )


async def _invite(runtime: TelegramRuntime, actor: UserId) -> str:
    origin = runtime.settings.public_origin
    if origin is None:
        return "The web app isn't set up yet."
    try:
        issued = await create_invite(runtime.uow(), actor, now=utcnow())
    except Forbidden:
        return "Only the owner can invite people."
    return (
        "Invite link for the web app (single use, expires in 24 hours):\n"
        f"{origin}/invite/{issued.token}"
    )


async def _photo(
    runtime: TelegramRuntime,
    actor: UserId,
    chat_id: int,
    photos: list[dict[str, Any]],
    caption: str | None,
    ref: str,
) -> None:
    fitting = [p for p in photos if int(p.get("file_size") or 0) <= MAX_DOWNLOAD]
    if not fitting:
        await runtime.client.send_message(chat_id, "That photo is too large.")
        return
    best = max(fitting, key=lambda p: int(p.get("width", 0)) * int(p.get("height", 0)))
    image = await runtime.client.download(best["file_id"])
    # Keyed by the image itself, so resending the same photo isn't logged twice.
    photo_ref = f"telegram-photo:{best.get('file_unique_id') or ref}"
    replies = await runtime.service.handle_photo(actor, image, "image/jpeg", caption, photo_ref)
    await _send(runtime, chat_id, replies)


async def _callback(runtime: TelegramRuntime, query: dict[str, Any]) -> None:
    message = query.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return
    chat_id = int(chat["id"])
    await runtime.client.answer_callback(str(query["id"]))
    actor = await _actor(runtime, query.get("from") or {}, chat_id)
    if actor is None:
        return
    data = str(query.get("data") or "")
    # One-shot buttons: take them off the message once pressed.
    if data.startswith(("hitl:", "bill:")) and message.get("message_id") is not None:
        await runtime.client.clear_buttons(chat_id, int(message["message_id"]))
    await _send(runtime, chat_id, await runtime.service.press(actor, data))
