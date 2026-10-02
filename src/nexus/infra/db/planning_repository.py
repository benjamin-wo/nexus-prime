"""PostgreSQL budgets, budget alerts and the job queue. Every budget query filters on user_id."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.notifications import DAILY_AT, Frequency, NotificationSettings
from nexus.domain.planning import Bill, BillOccurrence, Budget, Cadence, PayRule, SalarySchedule
from nexus.domain.recurring import Subscription, SubscriptionStatus
from nexus.infra.db.tables import (
    bill_occurrences,
    bills,
    budget_alerts,
    budgets,
    jobs,
    notification_settings,
    salary_schedules,
    subscriptions,
    users,
)


def _budget(row: Row[Any]) -> Budget:
    return Budget(
        id=row.id,
        user_id=UserId(row.user_id),
        category_id=row.category_id,
        limit=Money(row.amount, row.currency),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _bill(row: Row[Any]) -> Bill:
    return Bill(
        id=row.id,
        user_id=UserId(row.user_id),
        name=row.name,
        amount=Money(row.amount, row.currency) if row.amount is not None else None,
        cadence=Cadence(row.cadence),
        anchor=row.anchor,
        created_at=row.created_at,
        archived_at=row.archived_at,
    )


def _occurrence(row: Row[Any]) -> BillOccurrence:
    return BillOccurrence(
        id=row.id,
        user_id=UserId(row.user_id),
        bill_id=row.bill_id,
        due=row.due,
        paid_at=row.paid_at,
        snoozed_until=row.snoozed_until,
        reminded_offset=row.reminded_offset,
    )


def _subscription(row: Row[Any]) -> Subscription:
    return Subscription(
        id=row.id,
        user_id=UserId(row.user_id),
        key=row.key,
        name=row.name,
        cadence=Cadence(row.cadence),
        amount=Money(row.amount, row.currency),
        last_charged_on=row.last_charged_on,
        status=SubscriptionStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        previous_amount=(
            Money(row.previous_amount, row.currency) if row.previous_amount is not None else None
        ),
        price_changed_on=row.price_changed_on,
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

    # --- bills ------------------------------------------------------------------------

    async def insert_bill(self, bill: Bill) -> None:
        await self._db.execute(
            insert(bills).values(
                id=bill.id,
                user_id=bill.user_id,
                name=bill.name,
                amount=bill.amount.amount if bill.amount else None,
                currency=bill.amount.currency if bill.amount else None,
                cadence=bill.cadence.value,
                anchor=bill.anchor,
                created_at=bill.created_at,
                archived_at=bill.archived_at,
            )
        )

    async def list_bills(self, user_id: UserId) -> list[Bill]:
        b = bills.c
        rows = await self._db.execute(
            select(bills)
            .where(b.user_id == user_id, b.archived_at.is_(None))
            .order_by(b.anchor, b.name)
        )
        return [_bill(r) for r in rows]

    async def get_bill(self, user_id: UserId, bill_id: UUID) -> Bill | None:
        b = bills.c
        row = (
            await self._db.execute(select(bills).where(b.user_id == user_id, b.id == bill_id))
        ).first()
        return _bill(row) if row else None

    async def archive_bill(self, user_id: UserId, bill_id: UUID, at: datetime) -> bool:
        b = bills.c
        result = await self._db.execute(
            update(bills)
            .where(b.user_id == user_id, b.id == bill_id, b.archived_at.is_(None))
            .values(archived_at=at)
        )
        return bool(result.rowcount)

    async def users_with_bills(self) -> list[UserId]:
        b = bills.c
        rows = await self._db.execute(select(b.user_id).where(b.archived_at.is_(None)).distinct())
        return [UserId(r.user_id) for r in rows]

    async def occurrences(
        self, user_id: UserId, bill_id: UUID, since: date
    ) -> list[BillOccurrence]:
        o = bill_occurrences.c
        rows = await self._db.execute(
            select(bill_occurrences)
            .where(o.user_id == user_id, o.bill_id == bill_id, o.due >= since)
            .order_by(o.due)
        )
        return [_occurrence(r) for r in rows]

    async def get_occurrence(self, user_id: UserId, occurrence_id: UUID) -> BillOccurrence | None:
        o = bill_occurrences.c
        row = (
            await self._db.execute(
                select(bill_occurrences).where(o.user_id == user_id, o.id == occurrence_id)
            )
        ).first()
        return _occurrence(row) if row else None

    async def save_occurrence(self, occurrence: BillOccurrence) -> BillOccurrence:
        o = bill_occurrences.c
        stmt = pg_insert(bill_occurrences).values(
            id=occurrence.id,
            user_id=occurrence.user_id,
            bill_id=occurrence.bill_id,
            due=occurrence.due,
            paid_at=occurrence.paid_at,
            snoozed_until=occurrence.snoozed_until,
            reminded_offset=occurrence.reminded_offset,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[o.bill_id, o.due],
            set_={
                "paid_at": stmt.excluded.paid_at,
                "snoozed_until": stmt.excluded.snoozed_until,
                "reminded_offset": stmt.excluded.reminded_offset,
            },
            # Only this user's row (the bill's foreign key includes user_id).
            where=o.user_id == occurrence.user_id,
        )
        row = (await self._db.execute(stmt.returning(bill_occurrences))).one()
        return _occurrence(row)

    # --- salary -----------------------------------------------------------------------

    async def get_salary_schedule(self, user_id: UserId) -> SalarySchedule | None:
        s = salary_schedules.c
        row = (await self._db.execute(select(salary_schedules).where(s.user_id == user_id))).first()
        if row is None:
            return None
        return SalarySchedule(
            user_id=UserId(row.user_id),
            rule=PayRule(row.rule),
            day=row.day,
            anchor=row.anchor,
            baseline=Money(row.amount, row.currency) if row.amount is not None else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save_salary_schedule(self, schedule: SalarySchedule) -> None:
        values = {
            "rule": schedule.rule.value,
            "day": schedule.day,
            "anchor": schedule.anchor,
            "amount": schedule.baseline.amount if schedule.baseline else None,
            "currency": schedule.baseline.currency if schedule.baseline else None,
            "updated_at": schedule.updated_at,
        }
        stmt = pg_insert(salary_schedules).values(
            user_id=schedule.user_id, created_at=schedule.created_at, **values
        )
        await self._db.execute(
            stmt.on_conflict_do_update(index_elements=[salary_schedules.c.user_id], set_=values)
        )

    async def delete_salary_schedule(self, user_id: UserId) -> bool:
        s = salary_schedules.c
        result = await self._db.execute(delete(salary_schedules).where(s.user_id == user_id))
        return bool(result.rowcount)

    async def users_with_salary_schedules(self) -> list[UserId]:
        rows = await self._db.execute(select(salary_schedules.c.user_id))
        return [UserId(r.user_id) for r in rows]

    # subscriptions

    async def list_subscriptions(self, user_id: UserId) -> list[Subscription]:
        rows = await self._db.execute(
            select(subscriptions)
            .where(subscriptions.c.user_id == user_id)
            .order_by(subscriptions.c.name)
        )
        return [_subscription(r) for r in rows]

    async def get_subscription(
        self, user_id: UserId, subscription_id: UUID, *, for_update: bool = False
    ) -> Subscription | None:
        s = subscriptions.c
        stmt = select(subscriptions).where(s.user_id == user_id, s.id == subscription_id)
        row = (await self._db.execute(stmt.with_for_update() if for_update else stmt)).first()
        return _subscription(row) if row else None

    async def insert_subscription(self, subscription: Subscription) -> bool:
        """False if this merchant already has a row (proposed, tracked or dismissed)."""
        stmt = (
            pg_insert(subscriptions)
            .values(
                id=subscription.id,
                user_id=subscription.user_id,
                key=subscription.key,
                name=subscription.name,
                cadence=subscription.cadence.value,
                amount=subscription.amount.amount,
                currency=subscription.amount.currency,
                last_charged_on=subscription.last_charged_on,
                status=subscription.status.value,
                created_at=subscription.created_at,
                updated_at=subscription.updated_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    subscriptions.c.user_id,
                    subscriptions.c.key,
                    subscriptions.c.currency,
                ]
            )
            .returning(subscriptions.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None

    async def update_subscription(self, subscription: Subscription) -> None:
        s = subscriptions.c
        await self._db.execute(
            update(subscriptions)
            .where(s.user_id == subscription.user_id, s.id == subscription.id)
            .values(
                name=subscription.name,
                cadence=subscription.cadence.value,
                amount=subscription.amount.amount,
                last_charged_on=subscription.last_charged_on,
                status=subscription.status.value,
                previous_amount=(
                    subscription.previous_amount.amount if subscription.previous_amount else None
                ),
                price_changed_on=subscription.price_changed_on,
                updated_at=subscription.updated_at,
            )
        )

    # notifications

    async def get_notifications(
        self, user_id: UserId, *, for_update: bool = False
    ) -> NotificationSettings:
        n = notification_settings.c
        stmt = select(notification_settings).where(n.user_id == user_id)
        row = (await self._db.execute(stmt.with_for_update() if for_update else stmt)).first()
        if row is None:
            return NotificationSettings(user_id)
        return NotificationSettings(
            user_id,
            Frequency(row.frequency),
            row.notified_until,
            row.daily_at if row.daily_at is not None else DAILY_AT,
        )

    async def save_notifications(self, settings: NotificationSettings, now: datetime) -> None:
        values = {
            "frequency": settings.frequency.value,
            "notified_until": settings.notified_until,
            "daily_at": settings.daily_at,
            "updated_at": now,
        }
        stmt = pg_insert(notification_settings).values(user_id=settings.user_id, **values)
        await self._db.execute(
            stmt.on_conflict_do_update(
                index_elements=[notification_settings.c.user_id], set_=values
            )
        )

    async def users_to_notify(self) -> list[UserId]:
        rows = await self._db.execute(
            select(users.c.id).where(users.c.telegram_chat_id.is_not(None))
        )
        return [UserId(r.id) for r in rows]


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

    async def cancel(self, dedupe_key: str) -> bool:
        stmt = (
            delete(jobs)
            .where(jobs.c.dedupe_key == dedupe_key, jobs.c.status == "pending")
            .returning(jobs.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None
