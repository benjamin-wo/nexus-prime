"""The chat as the user saw it: their messages and Nexus's replies, on the web or
Telegram. Kept so the web chat can show the conversation again; notifications
(alerts, reminders, digests) are not part of it."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from nexus.domain.ledger import UserId

MAX_TEXT = 4000
CHAT_KEEP = 500  # lines per user; older ones are dropped


class Speaker(StrEnum):
    USER = "user"
    NEXUS = "nexus"


@dataclass(frozen=True, slots=True)
class ChatLine:
    user_id: UserId
    role: Speaker
    text: str
    channel: str | None  # "web" or "telegram"
    created_at: datetime
    id: int | None = None  # set once kept; later lines have larger ids


def clip(text: str) -> str:
    """The text as kept: trimmed, and cut to MAX_TEXT."""
    text = text.strip()
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def channel_of(ref: str) -> str | None:
    """Where a message came from, by its reference ("web:…", "telegram:…")."""
    head = ref.split(":", 1)[0]
    return head if head in ("web", "telegram") else None
