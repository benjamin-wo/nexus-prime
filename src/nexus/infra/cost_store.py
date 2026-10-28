"""Keeps what the AI models cost in the database: added up in memory, written every few
seconds as increments to the day's rows, and dropped after 13 months. Writing never blocks or
fails the call a charge describes: errors are logged and swallowed, and a batch that couldn't
be written is kept for the next flush."""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.clock import utcnow
from nexus.application.cost_report import Row
from nexus.application.costs import Charge
from nexus.infra.db.tables import NO_USER_ID, model_costs, users

log = logging.getLogger("nexus.ops.costs")

FLUSH_EVERY = 5.0
KEEP_MONTHS = 13

# The row for a day, user, feature and model is added to. The conflict target is the unique
# index's own expression (migration 0059): every NULL user counts as one.
_ADD = text(
    f"""
    INSERT INTO model_costs (day, user_id, feature, model, calls, input_tokens, output_tokens,
                             cost_usd)
    VALUES (:day, :user_id, :feature, :model, :calls, :input_tokens, :output_tokens, :cost)
    ON CONFLICT (day, (coalesce(user_id, {NO_USER_ID})), feature, model) DO UPDATE SET
        calls = model_costs.calls + EXCLUDED.calls,
        input_tokens = model_costs.input_tokens + EXCLUDED.input_tokens,
        output_tokens = model_costs.output_tokens + EXCLUDED.output_tokens,
        cost_usd = model_costs.cost_usd + EXCLUDED.cost_usd
    """  # noqa: S608  (built from this file's constants, never from input)
)


def keep_from(today: date) -> date:
    """The first day kept: the start of the month ``KEEP_MONTHS - 1`` months back, so the
    current month and the twelve before it are whole."""
    months = today.year * 12 + today.month - 1 - (KEEP_MONTHS - 1)
    return date(months // 12, months % 12 + 1, 1)


class CostStore:
    def __init__(self, engine: AsyncEngine, clock: Callable[[], datetime] = utcnow) -> None:
        self._engine = engine
        self._clock = clock
        # Added up as they arrive: the buffer holds one entry per day, user, feature and
        # model, however many calls were made.
        self._buffer: dict[tuple[date, UUID | None, str, str], Charge] = {}
        self._pruned: date | None = None
        # A call made on a worker thread adds to the same totals as one on the event loop.
        self._lock = threading.Lock()

    def add(self, charge: Charge) -> None:
        with self._lock:
            held = self._buffer.get(charge.key)
            self._buffer[charge.key] = (
                charge
                if held is None
                else Charge(
                    charge.day,
                    charge.user_id,
                    charge.feature,
                    charge.model,
                    held.calls + charge.calls,
                    held.input_tokens + charge.input_tokens,
                    held.output_tokens + charge.output_tokens,
                    held.cost + charge.cost,
                )
            )

    async def flush(self) -> int:
        """Write what has been counted. Returns the rows written; never raises."""
        with self._lock:
            batch, self._buffer = list(self._buffer.values()), {}
        if not batch:
            return 0
        try:
            await self._write(batch)
        except IntegrityError:
            # A user erased since their call (its row would break the whole batch): write
            # one by one and let go of what can't be written.
            return await self._write_each(batch)
        except Exception:
            log.warning("couldn't write %d model cost rows; will retry", len(batch), exc_info=True)
            for charge in batch:
                self.add(charge)
            return 0
        return len(batch)

    async def _write(self, batch: list[Charge]) -> None:
        async with self._engine.begin() as db:
            await db.execute(_ADD, [_params(c) for c in batch])

    async def _write_each(self, batch: list[Charge]) -> int:
        written = 0
        for charge in batch:
            try:
                await self._write([charge])
                written += 1
            except IntegrityError:
                log.info("dropped a model cost row for a user that no longer exists")
            except Exception:
                log.warning("couldn't write a model cost row; will retry", exc_info=True)
                self.add(charge)
        return written

    async def prune(self) -> int:
        cutoff = keep_from(self._clock().date())
        async with self._engine.begin() as db:
            result = await db.execute(delete(model_costs).where(model_costs.c.day < cutoff))
        self._pruned = self._clock().date()
        return int(result.rowcount or 0)

    async def run(self, stop: asyncio.Event) -> None:
        """Flush every few seconds and prune once a day, until ``stop``; then flush what's
        left."""
        while not stop.is_set():
            try:
                await self.flush()
                if self._pruned != self._clock().date():
                    await self.prune()
            except Exception:
                log.warning("model cost store loop failed", exc_info=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), FLUSH_EVERY)
        await self.flush()


def _params(charge: Charge) -> dict[str, object]:
    return {
        "day": charge.day,
        "user_id": charge.user_id,
        "feature": charge.feature,
        "model": charge.model,
        "calls": charge.calls,
        "input_tokens": charge.input_tokens,
        "output_tokens": charge.output_tokens,
        "cost": charge.cost,
    }


async def read_rows(engine: AsyncEngine, since: date) -> list[Row]:
    """Every stored row from ``since`` on, across users (the owner's view: no user is named
    for the transaction, so row-level security hides nothing)."""
    c = model_costs.c
    async with engine.connect() as db:
        found = await db.execute(
            select(c.day, c.user_id, c.feature, c.model, c.calls, c.input_tokens,
                   c.output_tokens, c.cost_usd)
            .where(c.day >= since)
            .order_by(c.day)
        )  # fmt: skip
        return [
            Row(r.day, r.user_id, r.feature, r.model, r.calls, r.input_tokens, r.output_tokens,
                Decimal(r.cost_usd))
            for r in found
        ]  # fmt: skip


async def read_names(engine: AsyncEngine, ids: set[UUID]) -> dict[UUID, str | None]:
    """Display names of the given users (None for one who has none)."""
    if not ids:
        return {}
    async with engine.connect() as db:
        found = await db.execute(
            select(users.c.id, users.c.display_name).where(users.c.id.in_(ids))
        )
        return {r.id: r.display_name for r in found}
