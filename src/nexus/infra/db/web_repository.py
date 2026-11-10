"""PostgreSQL storage for web search: answers kept for a while and the credits each
product used a month. Shared by all users: search results are public pages, and
the questions asked carry nothing of anyone's own."""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.infra.db.tables import serp_searches, web_cache, web_credits

# Expired answers removed each time one is kept, so the table stays small.
_PURGE_BATCH = 200
# The ``web_credits`` product the app's SerpApi searches are counted under.
SERPAPI = "serpapi"


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

    async def reserve_serp(
        self,
        month: date,
        monthly_cap: int,
        user_id: UUID | None,
        day: date,
        daily_cap: int,
    ) -> str:
        """Count one SerpApi search before it is made: "ok", or "day" (the user has made
        ``daily_cap`` today) or "month" (the app has made ``monthly_cap`` this month), in
        which case nothing is kept. Each count is one INSERT ... ON CONFLICT DO UPDATE that
        adds one only while the count is below its cap, so searches made at the same moment
        can't pass the cap together: the second waits on the row lock and sees the first's
        count. The caller commits only on "ok", so a day counted before the month said no is
        rolled back with it. ``user_id`` is None for work done for no one in particular (the
        trip researcher), which counts against the month alone."""
        if monthly_cap <= 0:
            return "month"
        if user_id is not None:
            if daily_cap <= 0:
                return "day"
            mine = pg_insert(serp_searches).values(user_id=user_id, day=day, searches=1)
            today = await self._c.execute(
                mine.on_conflict_do_update(
                    index_elements=[serp_searches.c.user_id, serp_searches.c.day],
                    set_={"searches": serp_searches.c.searches + 1},
                    where=serp_searches.c.searches < daily_cap,
                ).returning(serp_searches.c.searches)
            )
            if today.first() is None:
                return "day"
            # Old days are of no use: tidy up this user's own.
            await self._c.execute(
                delete(serp_searches).where(
                    serp_searches.c.user_id == user_id,
                    serp_searches.c.day < day - timedelta(days=7),
                )
            )
        used = pg_insert(web_credits).values(month=month, product=SERPAPI, credits=1)
        counted = await self._c.execute(
            used.on_conflict_do_update(
                index_elements=[web_credits.c.month, web_credits.c.product],
                set_={"credits": web_credits.c.credits + 1},
                where=web_credits.c.credits < monthly_cap,
            ).returning(web_credits.c.credits)
        )
        return "ok" if counted.first() is not None else "month"
