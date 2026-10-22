"""PostgreSQL record of Telegram messages. Every query filters on user_id."""

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.ledger import UserId
from nexus.domain.notifications import Level, Notification, Status
from nexus.infra.db.tables import notifications


def _notification(row: Row[Any]) -> Notification:
    return Notification(
        id=row.id,
        user_id=UserId(row.user_id),
        kind=row.kind,
        level=Level(row.level),
        text=row.text,
        link=row.link,
        has_buttons=row.has_buttons,
        created_at=row.created_at,
        status=Status(row.status),
        sent_at=row.sent_at,
        held_until=row.held_until,
        digest_id=row.digest_id,
    )


class SqlNotificationRepository:
    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def insert(self, record: Notification) -> None:
        await self._db.execute(
            insert(notifications).values(
                id=record.id,
                user_id=record.user_id,
                kind=record.kind,
                level=record.level.value,
                text=record.text,
                link=record.link,
                has_buttons=record.has_buttons,
                created_at=record.created_at,
                status=record.status.value,
                sent_at=record.sent_at,
                held_until=record.held_until,
                digest_id=record.digest_id,
            )
        )

    async def get(
        self, user_id: UserId, notification_id: UUID, *, for_update: bool = False
    ) -> Notification | None:
        n = notifications.c
        stmt = select(notifications).where(n.user_id == user_id, n.id == notification_id)
        row = (await self._db.execute(stmt.with_for_update() if for_update else stmt)).first()
        return _notification(row) if row is not None else None

    async def update(self, record: Notification) -> None:
        n = notifications.c
        await self._db.execute(
            update(notifications)
            .where(n.user_id == record.user_id, n.id == record.id)
            .values(
                status=record.status.value,
                sent_at=record.sent_at,
                held_until=record.held_until,
                digest_id=record.digest_id,
            )
        )

    async def count_sent(
        self,
        user_id: UserId,
        start: datetime,
        end: datetime,
        *,
        except_kinds: Collection[str],
    ) -> int:
        n = notifications.c
        count = await self._db.scalar(
            select(func.count())
            .select_from(notifications)
            .where(
                n.user_id == user_id,
                n.status == Status.SENT.value,
                n.level != Level.URGENT.value,
                n.kind.not_in(list(except_kinds)),
                n.sent_at >= start,
                n.sent_at < end,
            )
        )
        return int(count or 0)

    async def users_with_digest_due(self, now: datetime) -> list[UserId]:
        n = notifications.c
        rows = await self._db.execute(
            select(n.user_id)
            .where(n.status == Status.HELD.value, ~n.has_buttons, n.held_until <= now)
            .distinct()
        )
        return [UserId(r.user_id) for r in rows]

    async def due_for_digest(self, user_id: UserId, now: datetime) -> list[Notification]:
        n = notifications.c
        rows = await self._db.execute(
            select(notifications)
            .where(
                n.user_id == user_id,
                n.status == Status.HELD.value,
                ~n.has_buttons,
                n.held_until <= now,
            )
            .order_by(n.created_at, n.id)
            .with_for_update()
        )
        return [_notification(r) for r in rows]

    async def close_held(
        self,
        user_id: UserId,
        ids: Collection[UUID],
        status: Status,
        *,
        at: datetime,
        digest_id: UUID | None = None,
    ) -> None:
        """Mark held messages told in a digest, or dropped."""
        n = notifications.c
        await self._db.execute(
            update(notifications)
            .where(n.user_id == user_id, n.id.in_(list(ids)), n.status == Status.HELD.value)
            .values(
                status=status.value,
                sent_at=at if status is Status.DIGESTED else None,
                held_until=None,
                digest_id=digest_id,
            )
        )

    async def recent(
        self, user_id: UserId, since: datetime, limit: int = 500
    ) -> list[Notification]:
        """Newest first."""
        n = notifications.c
        rows = await self._db.execute(
            select(notifications)
            .where(n.user_id == user_id, n.created_at >= since)
            .order_by(n.created_at.desc(), n.id)
            .limit(limit)
        )
        return [_notification(r) for r in rows]

    async def prune(self, before: datetime) -> int:
        """Across all users: forget what was made before ``before``."""
        gone = await self._db.execute(
            delete(notifications).where(notifications.c.created_at < before)
        )
        return gone.rowcount
