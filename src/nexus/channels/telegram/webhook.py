"""POST /telegram/webhook.

Accepts an update only with Telegram's secret token, records its update_id so a
redelivery is ignored, answers 200 at once and handles it in the background.
Only allow-listed users in private chats are served.
"""

import asyncio
import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from nexus.agent.service import UNDO, AgentService, Button, Picture, Reply
from nexus.agent.tools import UowFactory
from nexus.application.access import create_invite
from nexus.application.clock import utcnow
from nexus.application.inbound import claim_event
from nexus.application.users import RegisterUser, register_user
from nexus.channels.telegram.client import MAX_DOWNLOAD, TelegramClient, TelegramError
from nexus.domain.errors import Forbidden
from nexus.domain.ledger import Role, UserId
from nexus.settings import Settings

log = logging.getLogger(__name__)
router = APIRouter()

PRIVATE = "This is a private assistant."
FAILED = "Sorry, something went wrong on my side. Please try again."

# The Undo button comes off a reply after this long (typing "undo" still works),
# so old messages don't keep offering to undo whatever happens to be latest.
UNDO_FOR = timedelta(minutes=5)
UNDO_EXPIRE = "telegram.undo_expire"
# Images Telegram sends as files that the models can read; PDFs are read for their text.
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
PDF = "application/pdf"
UNREADABLE_FILE = (
    "I can read photos, JPEG, PNG and WebP images, and PDFs. Send it as a photo instead."
)
# Photos sent together arrive as separate updates; wait this long for the rest.
ALBUM_WAIT = 1.5
_albums: dict[str, list[dict[str, Any]]] = {}
ONE_SHOT = ("hitl:", "bill:", "salary:", "rule:", "email:", "run:", "hold:", "plan:", "trip:")


@dataclass(frozen=True, slots=True)
class TelegramRuntime:
    settings: Settings
    uow: UowFactory
    service: AgentService
    client: TelegramClient
    clock: Callable[[], datetime] = field(default=utcnow)


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


def _undo_key(chat_id: int, message_id: int) -> str:
    return f"undo-expire:{chat_id}:{message_id}"


async def _send(runtime: TelegramRuntime, chat_id: int, replies: list[Reply]) -> None:
    for reply in replies:
        message_id = await runtime.client.send_message(chat_id, reply.text, reply.buttons or None)
        if message_id is not None and any(UNDO in row for row in reply.buttons):
            keep = [[b for b in row if b != UNDO] for row in reply.buttons]
            async with runtime.uow() as tx:
                await tx.jobs.enqueue(
                    UNDO_EXPIRE,
                    {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "keep": [
                            [{"label": b.label, "data": b.data} for b in row] for row in keep if row
                        ],
                    },
                    dedupe_key=_undo_key(chat_id, message_id),
                    run_at=runtime.clock() + UNDO_FOR,
                )
                await tx.commit()


def kept_buttons(payload: dict[str, Any]) -> list[list[Button]]:
    """The buttons an Undo-expiry job leaves on its message."""
    return [
        [Button(str(b["label"]), str(b["data"])) for b in row] for row in payload.get("keep") or []
    ]


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
        if message.get("photo") or message.get("document"):
            await _media(runtime, actor, chat_id, message, ref)
            return
        text = (message.get("text") or "").strip()
        if not text:
            await runtime.client.send_message(
                chat_id, "I can read text, photos, screenshots and PDFs."
            )
            return
        replied = message.get("reply_to_message") or {}
        if not text.startswith("/") and _image_of(replied) is not None:
            # A question about an earlier photo: look at it again, with the question.
            await _images(runtime, actor, chat_id, [replied], text, ref)
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


def _image_of(message: dict[str, Any]) -> dict[str, Any] | None:
    """The largest readable size of a message's photo, or its image file."""
    if photos := message.get("photo"):
        fitting = [p for p in photos if int(p.get("file_size") or 0) <= MAX_DOWNLOAD]
        if not fitting:
            return None
        best = max(fitting, key=lambda p: int(p.get("width", 0)) * int(p.get("height", 0)))
        return {**best, "mime_type": "image/jpeg"}
    document = message.get("document") or {}
    if document.get("mime_type") in IMAGE_TYPES:
        return document
    return None


async def _media(
    runtime: TelegramRuntime, actor: UserId, chat_id: int, message: dict[str, Any], ref: str
) -> None:
    document = message.get("document") or {}
    if document and int(document.get("file_size") or 0) > MAX_DOWNLOAD:
        await runtime.client.send_message(chat_id, "That file is too large.")
        return
    if document.get("mime_type") == PDF:
        data = await runtime.client.download(document["file_id"])
        name = str(document.get("file_name") or "document.pdf")
        replies = await runtime.service.handle_pdf(actor, data, name, message.get("caption"), ref)
        await _send(runtime, chat_id, replies)
        return
    if _image_of(message) is None:
        too_big = bool(message.get("photo"))
        await runtime.client.send_message(
            chat_id, "That photo is too large." if too_big else UNREADABLE_FILE
        )
        return
    group = message.get("media_group_id")
    if group is None:
        await _images(runtime, actor, chat_id, [message], message.get("caption"), ref)
        return
    # One photo of an album: the first to arrive waits for the rest and handles them
    # all together (the caption is on only one of them).
    key = f"{chat_id}:{group}"
    if key in _albums:
        _albums[key].append(message)
        return
    _albums[key] = [message]
    try:
        await asyncio.sleep(ALBUM_WAIT)
    finally:
        album = _albums.pop(key, [message])
    caption = next((m.get("caption") for m in album if m.get("caption")), None)
    readable = [m for m in album if _image_of(m) is not None]
    await _images(runtime, actor, chat_id, readable, caption, ref)


async def _images(
    runtime: TelegramRuntime,
    actor: UserId,
    chat_id: int,
    messages: list[dict[str, Any]],
    caption: str | None,
    ref: str,
) -> None:
    pictures: list[Picture] = []
    for message in messages:
        found = _image_of(message)
        if found is None:
            continue
        data = await runtime.client.download(found["file_id"])
        # Keyed by the image itself, so resending the same photo isn't logged twice.
        unique = found.get("file_unique_id") or f"{ref}:{len(pictures)}"
        pictures.append(Picture(data, str(found["mime_type"]), f"telegram-photo:{unique}"))
    if not pictures:
        await runtime.client.send_message(chat_id, UNREADABLE_FILE)
        return
    replies = await runtime.service.handle_images(actor, pictures, caption, ref)
    await _send(runtime, chat_id, replies)


async def _callback(runtime: TelegramRuntime, query: dict[str, Any]) -> None:
    message = query.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return
    chat_id = int(chat["id"])
    # Telegram refuses to answer a press that's too old (after a restart or a slow
    # turn). That only stops the button's spinner: the press is still handled.
    try:
        await runtime.client.answer_callback(str(query["id"]))
    except TelegramError as exc:
        log.info("telegram: couldn't answer a button press: %s", exc)
    actor = await _actor(runtime, query.get("from") or {}, chat_id)
    if actor is None:
        return
    data = str(query.get("data") or "")
    # One-shot buttons: take them off the message once pressed, Undo included, and
    # drop the job that would later put the rest back without Undo.
    if data.startswith(ONE_SHOT) and message.get("message_id") is not None:
        message_id = int(message["message_id"])
        try:
            await runtime.client.clear_buttons(chat_id, message_id)
        except TelegramError as exc:  # already cleared, or too old to edit
            log.info("telegram: couldn't clear buttons: %s", exc)
        async with runtime.uow() as tx:
            await tx.jobs.cancel(_undo_key(chat_id, message_id))
            await tx.commit()
    await _send(runtime, chat_id, await runtime.service.press(actor, data))
