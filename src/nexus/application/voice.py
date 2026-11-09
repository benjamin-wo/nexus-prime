"""How Kaya talks to a user: reading and changing their voice (see ``domain.voice``).

Used by the settings page, the chat tools and every chat turn (which loads it once).

A chat turn also opens a ``scope`` for the user's voice: the agent service loads it once, and
anything that makes a message during the turn (the prompt, the fixed wordings, the last pass
that takes emoji out) reads it from there instead of asking the database again. It is a
context variable like ``application.acting``, so it ends with the task that opened it.

The scope is opened at once and filled the first time something needs it (``load``): a turn
queues for the user's lock, and a database read before that would change who gets it first."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from nexus.application.ports import UnitOfWork
from nexus.domain.emoji import strip_emoji
from nexus.domain.ledger import UserId
from nexus.domain.voice import DEFAULT, Emoji, Humour, Length, Preset, VoiceSettings, changed

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Scope:
    """The voice of the user a turn is for. Changed in place when the turn changes it (the
    reply that confirms "no emoji" is already without)."""

    settings: VoiceSettings = DEFAULT
    loaded: bool = False  # settings are the user's own, read from the database


_scope: ContextVar[Scope | None] = ContextVar("voice_scope", default=None)


@contextmanager
def scope(settings: VoiceSettings | None = None) -> Iterator[Scope]:
    """Do the work inside for one user: with ``settings`` as their voice, or, left out,
    the default one until ``load`` reads theirs."""
    opened = Scope() if settings is None else Scope(settings, loaded=True)
    token = _scope.set(opened)
    try:
        yield opened
    finally:
        _scope.reset(token)


def in_scope() -> bool:
    return _scope.get() is not None


def is_loaded() -> bool:
    """Whether the current turn already has the user's own voice."""
    opened = _scope.get()
    return opened is not None and opened.loaded


async def load(uow: UnitOfWork, user_id: UserId) -> None:
    """Read the user's voice into the current scope, once; nothing outside one."""
    opened = _scope.get()
    if opened is not None and not opened.loaded:
        opened.settings = await voice_or_default(uow, user_id)
        opened.loaded = True


def current() -> VoiceSettings:
    """The voice of the user the current turn is for; the default one outside a turn."""
    opened = _scope.get()
    return opened.settings if opened is not None else DEFAULT


def note_change(settings: VoiceSettings) -> None:
    """The user's voice has just changed: the rest of the turn uses the new one."""
    opened = _scope.get()
    if opened is not None:
        opened.settings, opened.loaded = settings, True


def sent(text: str) -> str:
    """``text`` as it may leave for the user of the current turn: without emoji when they
    chose none."""
    return strip_emoji(text) if current().emoji is Emoji.NONE else text


async def worded_for(uow: UnitOfWork, user_id: UserId, text: str) -> str:
    """``text`` as it may go to ``user_id`` outside a chat turn: without emoji when they
    chose none."""
    voice = await voice_or_default(uow, user_id)
    return strip_emoji(text) if voice.emoji is Emoji.NONE else text


async def voice_or_default(uow: UnitOfWork, user_id: UserId) -> VoiceSettings:
    """The user's voice, or the default one when it can't be read: a voice is polish, and
    must never stop a message from going out."""
    try:
        return await get_voice(uow, user_id)
    except Exception:
        log.exception("loading the voice failed")
        return DEFAULT


async def get_voice(uow: UnitOfWork, user_id: UserId) -> VoiceSettings:
    """The user's voice; the default one if they never chose."""
    async with uow:
        return await uow.memory.get_voice(user_id)


async def set_voice(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    preset: str | Preset | None = None,
    emoji: str | Emoji | None = None,
    length: str | Length | None = None,
    humour: str | Humour | None = None,
    note: str | None = None,
    clear_note: bool = False,
    now: datetime,
) -> VoiceSettings:
    """Change the voice; what is left out stays as it was. Choosing a preset starts from
    that preset's own dials, unless dials are given in the same call. A blank
    note clears the note, like ``clear_note``. Raises InvalidInput for a value that isn't
    one of the choices, or a note that is too long or has control characters."""
    async with uow:
        current = await uow.memory.get_voice(user_id, for_update=True)
        updated = changed(
            current,
            preset=preset,
            emoji=emoji,
            length=length,
            humour=humour,
            note=note,
            clear_note=clear_note,
        )
        await uow.memory.save_voice(user_id, updated, now)
        await uow.commit()
    return updated
