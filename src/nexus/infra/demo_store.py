"""Counts what a public-demo account uses and what all demos cost (see ``application.demo``).

It reads and writes through the engine with no user named, as the owner's cost page does:
the spend across every demo is not any one user's rows, and a count is one statement on the
user's own row, so two requests can't both take the last use. The day's demo spend is the
live demo accounts' ``model_costs`` rows plus ``demo_costs`` (the erased ones'); it is read
after the cost store has written what it holds, and kept for a few seconds so a burst of
messages is one query.
"""

import time
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.clock import utcnow
from nexus.application.demo import (
    ALLOWANCE,
    CAP_REACHED,
    DAILY_CAP,
    LIMIT_REACHED,
    DemoUsage,
    Use,
)
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import demo_costs, model_costs, users

# How long a read of the day's spend is used again: a soft cap, by a few seconds.
SPEND_CACHE_SECONDS = 10.0

_COUNTER = {
    Use.MESSAGE: users.c.demo_messages,
    Use.VOICE: users.c.demo_voice,
    Use.PHOTO: users.c.demo_photos,
}


class DemoStore:
    def __init__(
        self,
        engine: AsyncEngine,
        flush: Callable[[], Awaitable[object]] | None = None,
        today: Callable[[], date] = lambda: utcnow().date(),
        cap: Decimal = DAILY_CAP,
    ) -> None:
        self._engine = engine
        self._flush = flush
        self._today = today
        self._cap = cap
        self._spend: tuple[float, date, Decimal] | None = None

    async def usage(self, user_id: UserId) -> DemoUsage | None:
        async with self._engine.connect() as db:
            row = (
                await db.execute(
                    select(
                        users.c.demo_expires_at,
                        users.c.demo_messages,
                        users.c.demo_voice,
                        users.c.demo_photos,
                    ).where(users.c.id == user_id)
                )
            ).first()
        if row is None or row.demo_expires_at is None:
            return None
        return DemoUsage(row.demo_messages, row.demo_voice, row.demo_photos)

    async def use(
        self, user_id: UserId, kind: Use | None, amount: int = 1, *, count: bool = True
    ) -> str | None:
        found = await self.usage(user_id)
        if found is None:
            return None  # a real user: no demo limits
        if kind is not None:
            used = {Use.MESSAGE: found.messages, Use.VOICE: found.voice, Use.PHOTO: found.photos}
            if used[kind] + amount > ALLOWANCE[kind]:
                return LIMIT_REACHED[kind]
        if await self.spent_today() >= self._cap:
            return CAP_REACHED
        if kind is not None and count:
            counter = _COUNTER[kind]
            async with self._engine.begin() as db:
                taken = await db.execute(
                    update(users)
                    .where(
                        users.c.id == user_id,
                        users.c.demo_expires_at.is_not(None),
                        counter + amount <= ALLOWANCE[kind],
                    )
                    .values({counter: counter + amount})
                    .returning(users.c.id)
                )
            if taken.first() is None:  # someone else took the last one meanwhile
                return LIMIT_REACHED[kind]
        return None

    async def spent_today(self) -> Decimal:
        """What the demos have cost today (UTC) in US dollars."""
        day = self._today()
        held = self._spend
        if held is not None and held[1] == day and time.monotonic() - held[0] < SPEND_CACHE_SECONDS:
            return held[2]
        if self._flush is not None:
            await self._flush()  # what was counted so far counts
        spent = await self.read_spend(day)
        self._spend = (time.monotonic(), day, spent)
        return spent

    async def read_spend(self, day: date) -> Decimal:
        live = (
            select(func.coalesce(func.sum(model_costs.c.cost_usd), 0))
            .select_from(model_costs.join(users, users.c.id == model_costs.c.user_id))
            .where(model_costs.c.day == day, users.c.demo_expires_at.is_not(None))
            .scalar_subquery()
        )
        erased = (
            select(func.coalesce(func.sum(demo_costs.c.cost_usd), 0))
            .where(demo_costs.c.day == day)
            .scalar_subquery()
        )
        async with self._engine.connect() as db:
            total: Decimal = (await db.execute(select(live + erased))).scalar_one()
        return Decimal(total)
