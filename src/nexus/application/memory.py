"""What Nexus remembers: listing, forgetting, recalling for a turn, and applying
the changes the memory writer proposes."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User, UserId
from nexus.domain.memory import MAX_MEMORIES, Memory, MemoryKind, clean_memory

type UowFactory = Callable[[], UnitOfWork]

LASTING = (MemoryKind.FACT, MemoryKind.PREFERENCE)
RECALL_LASTING = 40  # facts and preferences given to the model each turn, newest first
RECALL_MATCHING = 5  # episodes that match the message
RECALL_RECENT = 3  # and the latest episodes, whatever the message
RECALL_CHARS = 2500


class Action(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class MemoryChange:
    action: Action
    kind: MemoryKind | None = None  # for ADD
    text: str | None = None  # for ADD and UPDATE
    happened_on: date | None = None  # for an episode
    target: UUID | None = None  # for UPDATE and DELETE


async def list_memories(uow: UnitOfWork, actor: UserId) -> list[Memory]:
    async with uow:
        return await uow.memory.list_memories(actor)


async def forget(uow: UnitOfWork, actor: UserId, memory_id: UUID) -> None:
    async with uow:
        if not await uow.memory.delete_memory(actor, memory_id):
            raise NotFound("no such memory")
        await uow.commit()


async def forget_all(uow: UnitOfWork, actor: UserId) -> int:
    async with uow:
        removed = await uow.memory.prune_memories(actor, keep=0)
        await uow.commit()
        return removed


async def recall(uow_factory: UowFactory, user: User, message: str) -> list[Memory]:
    """The memories worth showing the model for this message."""
    async with uow_factory() as db:
        lasting = await db.memory.list_memories(user.id, LASTING, RECALL_LASTING)
        matching = await db.memory.search_memories(
            user.id, message, (MemoryKind.EPISODE,), RECALL_MATCHING
        )
        recent = await db.memory.list_memories(user.id, (MemoryKind.EPISODE,), RECALL_RECENT)
    chosen: list[Memory] = []
    for memory in [*lasting, *matching, *recent]:
        if memory.id not in {m.id for m in chosen}:
            chosen.append(memory)
    return chosen


def describe(memories: list[Memory]) -> str:
    """One line each, capped; episodes carry their date."""
    lines: list[str] = []
    size = 0
    for m in memories:
        when = f"{m.happened_on.isoformat()}: " if m.happened_on else ""
        line = f"- ({m.kind.value}) {when}{m.text}"
        if size + len(line) > RECALL_CHARS:
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines)


async def apply_changes(
    uow: UnitOfWork, user: User, changes: list[MemoryChange], *, now: datetime
) -> int:
    """Apply what the writer proposed; anything malformed or not the user's is skipped.
    Returns how many changes took effect."""
    done = 0
    async with uow:
        for change in changes:
            try:
                done += await _apply(uow, user, change, now)
            except InvalidInput:
                continue
        await uow.memory.prune_memories(user.id, keep=MAX_MEMORIES)
        await uow.commit()
    return done


async def _apply(uow: UnitOfWork, user: User, change: MemoryChange, now: datetime) -> int:
    match change.action:
        case Action.ADD:
            if change.kind is None or change.text is None:
                return 0
            episode = change.kind is MemoryKind.EPISODE
            await uow.memory.insert_memory(
                Memory(
                    id=uuid4(),
                    user_id=user.id,
                    kind=change.kind,
                    text=clean_memory(change.text),
                    happened_on=change.happened_on if episode else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            return 1
        case Action.UPDATE:
            if change.target is None or change.text is None:
                return 0
            return int(
                await uow.memory.update_memory(
                    user.id, change.target, clean_memory(change.text), now
                )
            )
        case Action.DELETE:
            if change.target is None:
                return 0
            return int(await uow.memory.delete_memory(user.id, change.target))
