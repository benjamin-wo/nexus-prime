"""Keeps ops events in the database: buffered in memory, written every few seconds
in one insert, and dropped after 30 days. Writing never blocks or fails the work an
event describes; if the buffer fills (the database is down), the oldest go."""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import mistakes, ops
from nexus.application.clock import utcnow
from nexus.infra.db.tables import email_connections, jobs, ops_events, web_credits

log = logging.getLogger(ops.LOGGER)

KEEP = timedelta(days=30)
FLUSH_EVERY = 5.0
PRUNE_EVERY = timedelta(hours=24)
BUFFER = 20_000
# Kinds read row by row for the report; requests and outside calls are counted in SQL.
DETAILED = ("turn", "model", "tool", "job", "log")


class OpsStore:
    def __init__(self, engine: AsyncEngine, clock: Callable[[], datetime] = utcnow) -> None:
        self._engine = engine
        self._clock = clock
        self._buffer: deque[ops.Event] = deque(maxlen=BUFFER)
        self._pruned: datetime | None = None

    def add(self, event: ops.Event) -> None:
        self._buffer.append(event)

    async def flush(self) -> int:
        batch: list[ops.Event] = []
        while self._buffer:
            batch.append(self._buffer.popleft())
        if not batch:
            return 0
        rows = [
            {
                "at": e.at,
                "kind": e.kind[:16],
                "name": e.name[:120],
                "ok": e.ok,
                "ms": e.ms,
                "trace": e.trace,
                "user_ref": e.user,
                "channel": (e.channel or "")[:16] or None,
                "detail": e.detail,
            }
            for e in batch
        ]
        try:
            async with self._engine.begin() as db:
                await db.execute(insert(ops_events), rows)
        except Exception:
            log.warning("couldn't write %d ops events; dropped", len(rows), exc_info=True)
            return 0
        return len(rows)

    async def prune(self) -> int:
        cutoff = self._clock() - KEEP
        async with self._engine.begin() as db:
            result = await db.execute(delete(ops_events).where(ops_events.c.at < cutoff))
        self._pruned = self._clock()
        return int(result.rowcount or 0)

    async def run(self, stop: asyncio.Event) -> None:
        """Flush every few seconds and prune once a day, until ``stop``; then flush
        what's left."""
        while not stop.is_set():
            try:
                await self.flush()
                if self._pruned is None or self._clock() - self._pruned >= PRUNE_EVERY:
                    await self.prune()
            except Exception:
                log.warning("ops store loop failed", exc_info=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), FLUSH_EVERY)
        await self.flush()


@dataclass(frozen=True, slots=True)
class Window:
    """What the report reads: events of the detailed kinds, and counts for the rest."""

    since: datetime
    until: datetime
    events: list[dict[str, Any]]
    requests: list[dict[str, Any]]  # per route: calls, failures, p90 ms
    calls: list[dict[str, Any]]  # per outside host: calls, failures, p90 ms, errors


@dataclass(frozen=True, slots=True)
class JobsState:
    stuck: list[dict[str, Any]]  # running past their lease
    overdue: list[dict[str, Any]]  # pending, well past when they should have run
    last_done: dict[str, datetime]  # each kind's last finish
    failed: list[dict[str, Any]]  # given up on in the window


async def read_window(engine: AsyncEngine, since: datetime, until: datetime) -> Window:
    e = ops_events.c
    in_window = (e.at >= since) & (e.at < until)
    p90 = func.percentile_cont(0.9).within_group(e.ms)
    async with engine.connect() as db:
        rows = await db.execute(
            select(e.at, e.kind, e.name, e.ok, e.ms, e.trace, e.user_ref, e.channel, e.detail)
            .where(in_window, e.kind.in_(DETAILED))
            .order_by(e.at)
        )
        events = [dict(r._mapping) for r in rows]
        requests = await db.execute(
            select(
                e.name,
                func.count().label("calls"),
                func.count().filter(~e.ok).label("failures"),
                p90.label("p90_ms"),
            )
            .where(in_window, e.kind == "request")
            .group_by(e.name)
        )
        calls = await db.execute(
            select(
                e.name,
                func.count().label("calls"),
                func.count().filter(~e.ok).label("failures"),
                p90.label("p90_ms"),
                func.array_agg(func.distinct(e.detail["error"].astext))
                .filter(~e.ok)
                .label("errors"),
            )
            .where(in_window, e.kind == "http")
            .group_by(e.name)
        )
        return Window(
            since,
            until,
            events,
            [dict(r._mapping) for r in requests],
            [dict(r._mapping) for r in calls],
        )


# The newest agent events kept for the weekly mistakes problem; far more than a week holds.
MAX_AGENT_EVENTS = 20_000


async def read_agent_events(
    engine: AsyncEngine, since: datetime, until: datetime
) -> list[dict[str, Any]]:
    """The "agent" events (signs the agent got something wrong; see
    application/mistakes.py) in a window, oldest first."""
    e = ops_events.c
    async with engine.connect() as db:
        rows = await db.execute(
            select(e.at, e.name, e.ok, e.trace, e.user_ref, e.channel, e.detail)
            .where(e.at >= since, e.at < until, e.kind == mistakes.KIND)
            .order_by(e.at.desc())
            .limit(MAX_AGENT_EVENTS)
        )
        return [dict(r._mapping) for r in reversed(rows.all())]


async def read_jobs(engine: AsyncEngine, now: datetime, since: datetime) -> JobsState:
    j = jobs.c
    async with engine.connect() as db:
        stuck = await db.execute(
            select(j.kind, j.attempts, j.locked_until).where(
                j.status == "running", j.locked_until < now - timedelta(minutes=5)
            )
        )
        overdue = await db.execute(
            select(j.kind, func.count().label("count"), func.min(j.run_at).label("oldest"))
            .where(j.status == "pending", j.run_at < now - timedelta(minutes=30))
            .group_by(j.kind)
        )
        last = await db.execute(
            select(j.kind, func.max(j.finished_at)).where(j.status == "done").group_by(j.kind)
        )
        failed = await db.execute(
            select(j.kind, func.count().label("count"), func.max(j.finished_at).label("last"))
            .where(j.status == "failed", j.finished_at >= since)
            .group_by(j.kind)
        )
        return JobsState(
            [dict(r._mapping) for r in stuck],
            [dict(r._mapping) for r in overdue],
            {k: at for k, at in last.all() if at is not None},
            [dict(r._mapping) for r in failed],
        )


async def read_state(engine: AsyncEngine, month_start: Any) -> dict[str, Any]:
    """Slow-changing things worth a look: broken mailboxes, search credits used this
    month, and the database's size."""
    async with engine.connect() as db:
        broken = await db.scalar(select(func.count()).where(email_connections.c.status == "broken"))
        credits = await db.execute(
            select(web_credits.c.product, web_credits.c.credits).where(
                web_credits.c.month == month_start
            )
        )
        size = await db.scalar(text("SELECT pg_database_size(current_database())"))
        return {
            "broken_mailboxes": int(broken or 0),
            "search_credits": {p: int(c) for p, c in credits.all()},
            "database_bytes": int(size or 0),
        }
