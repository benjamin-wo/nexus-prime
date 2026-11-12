"""What Nexus remembers about a user, from the user's own words.

Three kinds: facts about the user and their world ("Ann is my sister"),
preferences about how they like things done ("split dinners with Ann 50/50"),
and episodes, dated notes of what happened ("the 27 Sep Grab ride was for work").
A memory is information for the assistant, never an instruction to it.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId

MAX_TEXT = 300
MAX_MEMORIES = 300  # per user; the oldest episodes make way first


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    EPISODE = "episode"


@dataclass(frozen=True, slots=True)
class Memory:
    id: UUID
    user_id: UserId
    kind: MemoryKind
    text: str
    happened_on: date | None  # episodes only
    created_at: datetime
    updated_at: datetime


def clean_memory(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise InvalidInput("a memory needs some text")
    if len(cleaned) > MAX_TEXT:
        raise InvalidInput(f"a memory is at most {MAX_TEXT} characters")
    return cleaned
