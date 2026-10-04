"""PostgreSQL storage for department runs. Every query filters on user_id."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.departments import FINISHED, Run, RunStatus, Usage
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import department_runs


def _run(row: Row[Any]) -> Run:
    return Run(
        id=row.id,
        user_id=UserId(row.user_id),
        department=row.department,
        kind=row.kind,
        title=row.title,
        status=RunStatus(row.status),
        task=row.task,
        outputs=row.outputs,
        steps_done=row.steps_done,
        steps_total=row.steps_total,
        progress=row.progress,
        spent=row.spent,
        created_at=row.created_at,
        updated_at=row.updated_at,
        result=row.result,
        error=row.error,
        chat_id=row.chat_id,
        message_id=row.message_id,
        finished_at=row.finished_at,
    )


def _values(run: Run) -> dict[str, Any]:
    return {
        "status": run.status.value,
        "outputs": run.outputs,
        "steps_done": run.steps_done,
        "progress": run.progress,
        "spent": run.spent,
        "result": run.result,
        "error": run.error,
        "chat_id": run.chat_id,
        "message_id": run.message_id,
        "updated_at": run.updated_at,
        "finished_at": run.finished_at,
    }


class SqlRunRepository:
    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def insert_run(self, run: Run) -> None:
        await self._db.execute(
            insert(department_runs).values(
                id=run.id,
                user_id=run.user_id,
                department=run.department,
                kind=run.kind,
                title=run.title,
                task=run.task,
                steps_total=run.steps_total,
                created_at=run.created_at,
                **_values(run),
            )
        )

    async def get_run(
        self, user_id: UserId, run_id: UUID, *, for_update: bool = False
    ) -> Run | None:
        r = department_runs.c
        stmt = select(department_runs).where(r.user_id == user_id, r.id == run_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._db.execute(stmt)).first()
        return _run(row) if row else None

    async def update_run(self, run: Run) -> None:
        r = department_runs.c
        await self._db.execute(
            update(department_runs)
            .where(r.user_id == run.user_id, r.id == run.id)
            .values(**_values(run))
        )

    async def list_runs(self, user_id: UserId, *, since: datetime, limit: int) -> list[Run]:
        """Unfinished runs, then the latest finished since ``since``, newest first."""
        r = department_runs.c
        open_ = r.status.notin_([s.value for s in FINISHED])
        rows = await self._db.execute(
            select(department_runs)
            .where(r.user_id == user_id, open_ | (r.created_at >= since))
            .order_by(open_.desc(), r.created_at.desc())
            .limit(limit)
        )
        return [_run(row) for row in rows]

    async def usage(self, user_id: UserId, since: datetime) -> Usage:
        r = department_runs.c
        open_ = r.status.notin_([s.value for s in FINISHED])
        row = (
            await self._db.execute(
                select(
                    func.count().filter(open_),
                    func.count().filter(r.created_at >= since),
                    func.coalesce(func.sum(r.spent).filter(r.created_at >= since), 0),
                ).where(r.user_id == user_id)
            )
        ).one()
        return Usage(int(row[0]), int(row[1]), Decimal(row[2]))
