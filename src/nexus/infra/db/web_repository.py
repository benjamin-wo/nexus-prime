"""PostgreSQL storage for web search: answers kept for a while and the credits each
product used a month. Shared by all users: search results are public pages, and
the questions asked carry nothing of anyone's own."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.infra.db.tables import web_cache, web_credits

# Expired answers removed each time one is kept, so the table stays small.
_PURGE_BATCH = 200


class SqlWebRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def cached(self, key: str, now: datetime) -> dict[str, Any] | None:
        row = (
            await self._c.execute(
                select(web_cache.c.body).where(web_cache.c.key == key, web_cache.c.expires_at > now)
            )
        ).first()
        return dict(row.body) if row else None

    async def keep(
        self, key: str, body: dict[str, Any], expires_at: datetime, now: datetime
    ) -> None:
        stale = (
            select(web_cache.c.key)
            .where(web_cache.c.expires_at <= now)
            .limit(_PURGE_BATCH)
            .scalar_subquery()
        )
        await self._c.execute(delete(web_cache).where(web_cache.c.key.in_(stale)))
        insert = pg_insert(web_cache).values(key=key, body=body, expires_at=expires_at)
        await self._c.execute(
            insert.on_conflict_do_update(
                index_elements=[web_cache.c.key],
                set_={"body": insert.excluded.body, "expires_at": insert.excluded.expires_at},
            )
        )

    async def credits(self, month: date) -> dict[str, int]:
        rows = await self._c.execute(
            select(web_credits.c.product, web_credits.c.credits).where(web_credits.c.month == month)
        )
        return {r.product: r.credits for r in rows}

    async def add_credits(self, month: date, product: str, credits: int) -> None:
        insert = pg_insert(web_credits).values(month=month, product=product, credits=credits)
        await self._c.execute(
            insert.on_conflict_do_update(
                index_elements=[web_credits.c.month, web_credits.c.product],
                set_={"credits": web_credits.c.credits + insert.excluded.credits},
            )
        )
