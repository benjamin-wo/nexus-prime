"""PostgreSQL storage for answers from outside services (travel times, weather), kept for
as long as the in-memory caches keep them. Shared by all users: the key is a hash of what
was asked and the value only the answer, so nothing in it is anyone's own."""

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.infra.db.tables import external_cache

# Expired answers removed each time one is kept, so the table stays small.
_PURGE_BATCH = 200


class SqlExternalCacheRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def cached(self, key: str, now: datetime) -> tuple[Any, datetime] | None:
        row = (
            await self._c.execute(
                select(external_cache.c.value, external_cache.c.expires_at).where(
                    external_cache.c.key == key, external_cache.c.expires_at > now
                )
            )
        ).first()
        return (row.value, row.expires_at) if row else None

    async def keep(
        self, key: str, kind: str, value: Any, expires_at: datetime, now: datetime
    ) -> None:
        stale = (
            select(external_cache.c.key)
            .where(external_cache.c.expires_at <= now)
            .limit(_PURGE_BATCH)
            .scalar_subquery()
        )
        await self._c.execute(delete(external_cache).where(external_cache.c.key.in_(stale)))
        insert = pg_insert(external_cache).values(
            key=key, kind=kind, value=value, expires_at=expires_at
        )
        await self._c.execute(
            insert.on_conflict_do_update(
                index_elements=[external_cache.c.key],
                set_={
                    "kind": insert.excluded.kind,
                    "value": insert.excluded.value,
                    "expires_at": insert.excluded.expires_at,
                },
            )
        )
