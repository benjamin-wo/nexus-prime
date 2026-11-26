"""Web API: chat."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.datastructures import UploadFile

from nexus.application import speech as speech_rules
from nexus.channels.web.chat_stream import stream_turn
from nexus.channels.web.security import (
    Auth,
    Runtime,
)
from nexus.channels.web.shapes import Model, ReplyOut, replies_out

router = APIRouter(prefix="/api")

# --- chat -----------------------------------------------------------------------------


class ChatIn(Model):
    message: str = Field(min_length=1, max_length=2000)


class ChatLineOut(Model):
    id: int
    role: str  # "user" or "nexus"
    text: str
    channel: str | None
    at: datetime


class ChatHistoryOut(Model):
    lines: list[ChatLineOut]  # oldest first
    more: bool  # older lines exist (ask again with before=the first line's id)
    pending: ReplyOut | None  # a confirmation still waiting, with its buttons


@router.get("/chat/history")
async def chat_history(
    auth: Auth,
    web: Runtime,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
) -> ChatHistoryOut:
    """The running chat as the user saw it, on the web or Telegram; notifications
    aren't part of it."""
    async with web.uow() as tx:
        found = await tx.memory.chat(auth.user.id, limit + 1, before)
    more = len(found) > limit
    lines = found[-limit:]
    pending = await web.service.chat_pending(auth.user.id) if before is None else None
    return ChatHistoryOut(
        lines=[
            ChatLineOut(
                id=x.id or 0, role=x.role.value, text=x.text, channel=x.channel, at=x.created_at
            )
            for x in lines
        ],
        more=more,
        pending=replies_out([pending])[0] if pending else None,
    )


@router.post("/chat")
async def chat(body: ChatIn, auth: Auth, web: Runtime) -> list[ReplyOut]:
    ref = f"web:{auth.session.token_hash[:16]}:{web.clock().timestamp()}"
    return replies_out(await web.service.handle_text(auth.user.id, body.message, ref))


@router.post("/chat/stream")
async def chat_stream(body: ChatIn, auth: Auth, web: Runtime) -> StreamingResponse:
    """The same turn as ``POST /chat``, as a ``text/event-stream``: ``step`` events while
    it works, then ``replies`` (what ``/chat`` returns) or ``error``. Same sign-in, origin,
    CSRF and limits. A browser that leaves doesn't cancel the turn."""
    ref = f"web:{auth.session.token_hash[:16]}:{web.clock().timestamp()}"
    return stream_turn(
        web.service,
        auth.user.id,
        body.message,
        ref,
        replies=lambda done: [r.model_dump(mode="json") for r in replies_out(done)],
    )


@router.post("/chat/stop", status_code=204)
async def chat_stop(auth: Auth, web: Runtime) -> None:
    """Ask for the running chat turn to end at its next step, saying what it already did.
    Nothing is interrupted mid-write; with no turn running it does nothing."""
    web.service.request_stop(auth.user.id)


# A multipart body adds a little to the recording itself.
_VOICE_OVERHEAD = 64 * 1024


@router.post("/chat/voice")
async def chat_voice(request: Request, auth: Auth, web: Runtime) -> list[ReplyOut]:
    """A voice note (multipart, field ``audio``), handled as if its words were typed.
    413 over 5 MB, 415 for a type browsers don't record, 429 past 30 an hour, 503 when
    voice notes aren't set up. Nothing is kept of the recording."""
    if not web.service.hears_voice:
        raise HTTPException(status_code=503, detail=speech_rules.NOT_SET_UP)
    too_long = HTTPException(status_code=413, detail=speech_rules.TOO_LONG)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > speech_rules.MAX_BYTES + _VOICE_OVERHEAD:
        raise too_long
    try:
        form = await request.form(max_files=1, max_fields=1)
    except Exception as exc:  # not multipart, or malformed
        raise HTTPException(
            status_code=422, detail="send the recording as form field audio"
        ) from exc
    upload = form.get("audio")
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=422, detail="send the recording as form field audio")
    mime = speech_rules.base_type(upload.content_type or "")
    if mime not in speech_rules.WEB_TYPES:
        raise HTTPException(status_code=415, detail=speech_rules.UNSUPPORTED)
    audio = await upload.read(speech_rules.MAX_BYTES + 1)
    await form.close()
    if len(audio) > speech_rules.MAX_BYTES:
        raise too_long
    ref = f"web:{auth.session.token_hash[:16]}:{web.clock().timestamp()}"
    return replies_out(await web.service.handle_voice(auth.user.id, audio, mime, ref))


class PressIn(Model):
    data: str = Field(min_length=1, max_length=64)


@router.post("/chat/press")
async def press(body: PressIn, auth: Auth, web: Runtime) -> list[ReplyOut]:
    """Confirm/Cancel, Undo and quick-action buttons, as on Telegram."""
    return replies_out(await web.service.press(auth.user.id, body.data))
