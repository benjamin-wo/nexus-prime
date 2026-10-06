"""PostgreSQL storage for what Nexus remembers. Every query filters on user_id."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, and_, case, delete, func, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.chat import ChatLine, Speaker
from nexus.domain.ledger import UserId
from nexus.domain.memory import Memory, MemoryKind
from nexus.infra.db.tables import chat_log, memories

_WORD = re.compile(r"[a-z0-9]{2,}")


def _memory(row: Row[Any]) -> Memory:
    return Memory(
        id=row.id,
        user_id=UserId(row.user_id),
        kind=MemoryKind(row.kind),
        text=row.text,
        happened_on=row.happened_on,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlMemoryRepository:
    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def list_memories(
        self, user_id: UserId, kinds: tuple[MemoryKind, ...] | None = None, limit: int = 500
    ) -> list[Memory]:
        m = memories.c
        query = select(memories).where(m.user_id == user_id)
        if kinds is not None:
            query = query.where(m.kind.in_([k.value for k in kinds]))
        rows = await self._db.execute(query.order_by(m.updated_at.desc(), m.id).limit(limit))
        return [_memory(r) for r in rows]

    async def search_memories(
        self, user_id: UserId, text: str, kinds: tuple[MemoryKind, ...], limit: int
    ) -> list[Memory]:
        """The best matches for any word of ``text``, newest first among equals."""
        words = sorted(set(_WORD.findall(text.lower())))[:30]
        if not words:
            return []
        m = memories.c
        query_ts = func.to_tsquery("english", " | ".join(words))
        document = func.to_tsvector("english", m.text)
        rank = func.ts_rank(document, query_ts)
        rows = await self._db.execute(
            select(memories)
            .where(
                m.user_id == user_id,
                m.kind.in_([k.value for k in kinds]),
                document.op("@@")(query_ts),
            )
            .order_by(rank.desc(), m.updated_at.desc())
            .limit(limit)
        )
        return [_memory(r) for r in rows]

    async def insert_memory(self, memory: Memory) -> None:
        await self._db.execute(
            insert(memories).values(
                id=memory.id,
                user_id=memory.user_id,
                kind=memory.kind.value,
                text=memory.text,
                happened_on=memory.happened_on,
                created_at=memory.created_at,
                updated_at=memory.updated_at,
            )
        )

    async def update_memory(
        self, user_id: UserId, memory_id: UUID, text: str, at: datetime
    ) -> bool:
        m = memories.c
        result = await self._db.execute(
            update(memories)
            .where(m.user_id == user_id, m.id == memory_id)
            .values(text=text, updated_at=at)
        )
        return bool(result.rowcount)

    async def delete_memory(self, user_id: UserId, memory_id: UUID) -> bool:
        m = memories.c
        result = await self._db.execute(
            delete(memories).where(m.user_id == user_id, m.id == memory_id)
        )
        return bool(result.rowcount)

    async def prune_memories(self, user_id: UserId, keep: int) -> int:
        """Keep the newest ``keep``, dropping episodes before facts and preferences."""
        m = memories.c
        order = case((m.kind == MemoryKind.EPISODE.value, literal(1)), else_=literal(0))
        ranked = (
            select(m.id, func.row_number().over(order_by=(order, m.updated_at.desc())).label("n"))
            .where(m.user_id == user_id)
            .subquery()
        )
        result = await self._db.execute(
            delete(memories).where(
                and_(
                    m.user_id == user_id,
                    m.id.in_(select(ranked.c.id).where(ranked.c.n > keep)),
                )
            )
        )
        return int(result.rowcount or 0)

    # --- the chat as the user saw it ---

    async def add_chat(self, lines: list[ChatLine], keep: int) -> None:
        if not lines:
            return
        await self._db.execute(
            insert(chat_log).values(
                [
                    {
                        "user_id": line.user_id,
                        "role": line.role.value,
                        "text": line.text,
                        "channel": line.channel,
                        "created_at": line.created_at,
                    }
                    for line in lines
                ]
            )
        )
        c = chat_log.c
        kept = select(c.id).where(c.user_id == lines[0].user_id).order_by(c.id.desc()).limit(keep)
        await self._db.execute(
            delete(chat_log).where(c.user_id == lines[0].user_id, c.id.not_in(kept))
        )

    async def chat(self, user_id: UserId, limit: int, before: int | None = None) -> list[ChatLine]:
        c = chat_log.c
        query = select(chat_log).where(c.user_id == user_id)
        if before is not None:
            query = query.where(c.id < before)
        rows = await self._db.execute(query.order_by(c.id.desc()).limit(limit))
        found = [
            ChatLine(
                id=r.id,
                user_id=UserId(r.user_id),
                role=Speaker(r.role),
                text=r.text,
                channel=r.channel,
                created_at=r.created_at,
            )
            for r in rows
        ]
        return found[::-1]
