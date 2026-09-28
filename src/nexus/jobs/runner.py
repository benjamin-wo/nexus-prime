"""Run queued jobs exactly once, however many app instances are up.

A job is claimed atomically with ``FOR UPDATE SKIP LOCKED`` and leased for a
while; a runner that dies mid-job loses the lease and the job is retried.
Recurring work is queued once per time slot under a unique dedupe key
("budgets.sweep@2026-09-28T12:10:00+00:00"), so two runners scheduling the
same slot create one job between them. No leader election is needed.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.clock import utcnow
from nexus.infra.db.tables import jobs

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
KEEP_DONE = timedelta(days=7)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Defer:
    """Returned by a handler to run the job again later without counting a failure."""

    until: datetime


type Handler = Callable[[dict[str, Any]], Awaitable[Defer | None]]


@dataclass(frozen=True, slots=True)
class Schedule:
    kind: str
    every: timedelta


@dataclass(frozen=True, slots=True)
class Claimed:
    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int


def slot_start(now: datetime, every: timedelta) -> datetime:
    """The start of the fixed-length slot containing ``now`` (aligned to the Unix epoch)."""
    return _EPOCH + ((now - _EPOCH) // every) * every


def backoff(attempts: int) -> timedelta:
    return timedelta(minutes=min(2**attempts, 60))


class JobRunner:
    def __init__(
        self,
        engine: AsyncEngine,
        handlers: dict[str, Handler],
        *,
        schedules: Sequence[Schedule] = (),
        clock: Callable[[], datetime] = utcnow,
        batch: int = 10,
        lease: timedelta = timedelta(minutes=5),
    ) -> None:
        self._engine = engine
        self._handlers = handlers
        self._schedules = schedules
        self._clock = clock
        self._batch = batch
        self._lease = lease

    async def tick(self) -> int:
        """Queue due recurring jobs, then claim and run what's due. Returns jobs run."""
        now = self._clock()
        await self._schedule(now)
        claimed = await self._claim(now)
        for job in claimed:
            await self._run(job)
        return len(claimed)

    async def run(self, stop: asyncio.Event, interval: float = 5.0) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("job runner tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), interval)

    async def _schedule(self, now: datetime) -> None:
        j = jobs.c
        async with self._engine.begin() as db:
            for s in self._schedules:
                start = slot_start(now, s.every)
                await db.execute(
                    pg_insert(jobs)
                    .values(
                        kind=s.kind,
                        dedupe_key=f"{s.kind}@{start.isoformat()}",
                        payload={},
                        run_at=start,
                        status="pending",
                    )
                    .on_conflict_do_nothing(index_elements=[j.dedupe_key])
                )
            await db.execute(
                delete(jobs).where(j.status == "done", j.finished_at < now - KEEP_DONE)
            )

    async def _claim(self, now: datetime) -> list[Claimed]:
        j = jobs.c
        due = (
            select(j.id)
            .where(
                or_(
                    and_(j.status == "pending", j.run_at <= now),
                    and_(j.status == "running", j.locked_until < now),  # lease expired
                )
            )
            .order_by(j.run_at)
            .limit(self._batch)
            .with_for_update(skip_locked=True)
        )
        async with self._engine.begin() as db:
            rows = await db.execute(
                update(jobs)
                .where(j.id.in_(due.scalar_subquery()))
                .values(status="running", attempts=j.attempts + 1, locked_until=now + self._lease)
                .returning(j.id, j.kind, j.payload, j.attempts)
            )
            return [Claimed(r.id, r.kind, r.payload, r.attempts) for r in rows]

    async def _run(self, job: Claimed) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            await self._finish(job, status="failed", error=f"no handler for {job.kind!r}")
            return
        try:
            outcome = await handler(job.payload)
        except Exception as exc:
            log.exception("job %s (%s) failed", job.id, job.kind)
            error = f"{type(exc).__name__}: {exc}"[:500]
            if job.attempts >= MAX_ATTEMPTS:
                await self._finish(job, status="failed", error=error)
            else:
                retry_at = self._clock() + backoff(job.attempts)
                await self._finish(job, status="pending", error=error, run_at=retry_at)
            return
        if isinstance(outcome, Defer):
            # Not a failure: give the attempt back.
            await self._finish(
                job, status="pending", run_at=outcome.until, attempts=job.attempts - 1
            )
        else:
            await self._finish(job, status="done")

    async def _finish(
        self,
        job: Claimed,
        *,
        status: str,
        error: str | None = None,
        run_at: datetime | None = None,
        attempts: int | None = None,
    ) -> None:
        j = jobs.c
        values: dict[str, Any] = {"status": status, "locked_until": None, "last_error": error}
        if status in {"done", "failed"}:
            values["finished_at"] = self._clock()
        if run_at is not None:
            values["run_at"] = run_at
        if attempts is not None:
            values["attempts"] = attempts
        async with self._engine.begin() as db:
            # Only while still ours: after a lost lease another runner owns it.
            await db.execute(
                update(jobs).where(j.id == job.id, j.status == "running").values(**values)
            )
