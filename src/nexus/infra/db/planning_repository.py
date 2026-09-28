"""PostgreSQL budgets, budget alerts and the job queue. Every budget query filters on user_id."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.planning import Budget
from nexus.infra.db.tables import budget_alerts, budgets, jobs


def _budget(row: Row[Any]) -> Budget:
    return Budget(
        id=row.id,
        user_id=UserId(row.user_id),
        category_id=row.category_id,
        limit=Money(row.amount, row.currency),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlPlanningRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._db = connection

    async def upsert_budget(self, budget: Budget) -> Budget:
        b = budgets.c
        values = {
            "id": budget.id,
            "user_id": budget.user_id,
            "category_id": budget.category_id,
            "amount": budget.limit.amount,
            "currency": budget.limit.currency,
            "created_at": budget.created_at,
            "updated_at": budget.updated_at,
        }
        stmt = pg_insert(budgets).values(**values)
        if budget.category_id is None:
            stmt = stmt.on_conflict_do_update(
                index_elements=[b.user_id],
                index_where=b.category_id.is_(None),
                set_={
                    "amount": stmt.excluded.amount,
                    "currency": stmt.excluded.currency,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        else:
            stmt = stmt.on_conflict_do_update(
                index_elements=[b.user_id, b.category_id],
                index_where=b.category_id.is_not(None),
                set_={
                    "amount": stmt.excluded.amount,
                    "currency": stmt.excluded.currency,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        row = (await self._db.execute(stmt.returning(budgets))).one()
        return _budget(row)

    async def list_budgets(self, user_id: UserId) -> list[Budget]:
        b = budgets.c
        rows = await self._db.execute(
            select(budgets)
            .where(b.user_id == user_id)
            .order_by(b.category_id.is_not(None), b.created_at)
        )
        return [_budget(r) for r in rows]

    async def get_budget(self, user_id: UserId, budget_id: UUID) -> Budget | None:
        b = budgets.c
        row = (
            await self._db.execute(select(budgets).where(b.user_id == user_id, b.id == budget_id))
        ).first()
        return _budget(row) if row else None

    async def delete_budget(self, user_id: UserId, budget_id: UUID) -> bool:
        b = budgets.c
        result = await self._db.execute(
            delete(budgets).where(b.user_id == user_id, b.id == budget_id)
        )
        return bool(result.rowcount)

    async def users_with_budgets(self) -> list[UserId]:
        rows = await self._db.execute(select(budgets.c.user_id).distinct())
        return [UserId(r.user_id) for r in rows]

    async def record_alerts(
        self, user_id: UserId, budget_id: UUID, period: date, thresholds: list[int], at: datetime
    ) -> list[int]:
        if not thresholds:
            return []
        a = budget_alerts.c
        # Only a budget of this user may be alerted on (the foreign key includes user_id).
        stmt = (
            pg_insert(budget_alerts)
            .values(
                [
                    {
                        "budget_id": budget_id,
                        "user_id": user_id,
                        "period": period,
                        "threshold": t,
                        "reached_at": at,
                    }
                    for t in thresholds
                ]
            )
            .on_conflict_do_nothing()
            .returning(a.threshold)
        )
        return sorted(r.threshold for r in await self._db.execute(stmt))


class SqlJobQueue:
    def __init__(self, connection: AsyncConnection) -> None:
        self._db = connection

    async def enqueue(
        self, kind: str, payload: dict[str, Any], *, dedupe_key: str, run_at: datetime
    ) -> bool:
        stmt = (
            pg_insert(jobs)
            .values(
                kind=kind, dedupe_key=dedupe_key, payload=payload, run_at=run_at, status="pending"
            )
            .on_conflict_do_nothing(index_elements=[jobs.c.dedupe_key])
            .returning(jobs.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None
