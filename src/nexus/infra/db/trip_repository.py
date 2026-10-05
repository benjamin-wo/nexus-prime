"""PostgreSQL storage for trips. Every query filters on user_id."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, Row, and_, cast, delete, exists, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.application.ports import TripExpense
from nexus.domain.bookings import Booking, BookingDraft
from nexus.domain.ledger import Direction, TransactionStatus, UserId
from nexus.domain.money import Money
from nexus.domain.trips import Trip
from nexus.infra.db.ledger_repository import _transaction
from nexus.infra.db.tables import (
    categories,
    splits,
    transactions,
    trip_bookings,
    trip_links,
    trip_reminders,
    trips,
)


def _trip(row: Row[Any]) -> Trip:
    home = row.home_currency
    return Trip(
        id=row.id,
        user_id=UserId(row.user_id),
        destination=row.destination,
        start=row.start_on,
        end=row.end_on,
        currency=row.currency,
        budget=Money(row.budget, home) if row.budget is not None else None,
        companions=tuple(row.companions),
        set_aside=Money(row.set_aside, home) if row.set_aside is not None else None,
        planned={k: Money(Decimal(v), home) for k, v in row.planned.items()},
        created_at=row.created_at,
        updated_at=row.updated_at,
        notes=row.notes,
    )


def _values(trip: Trip, home: str) -> dict[str, Any]:
    return {
        "destination": trip.destination,
        "start_on": trip.start,
        "end_on": trip.end,
        "currency": trip.currency,
        "home_currency": home,
        "budget": trip.budget.amount if trip.budget else None,
        "set_aside": trip.set_aside.amount if trip.set_aside else None,
        "companions": list(trip.companions),
        "planned": {k: str(v.amount) for k, v in trip.planned.items()},
        "notes": trip.notes,
        "updated_at": trip.updated_at,
    }


class SqlTripRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._db = connection

    async def insert_trip(self, trip: Trip, home: str) -> None:
        await self._db.execute(
            insert(trips).values(
                id=trip.id, user_id=trip.user_id, created_at=trip.created_at, **_values(trip, home)
            )
        )

    async def update_trip(self, trip: Trip, home: str) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == trip.user_id, trips.c.id == trip.id)
            .values(**_values(trip, home))
        )

    async def delete_trip(self, user_id: UserId, trip_id: UUID) -> bool:
        # Its bookings stay, without a trip.
        await self._db.execute(
            update(trip_bookings)
            .where(trip_bookings.c.user_id == user_id, trip_bookings.c.trip_id == trip_id)
            .values(trip_id=None)
        )
        result = await self._db.execute(
            delete(trips).where(trips.c.user_id == user_id, trips.c.id == trip_id)
        )
        return bool(result.rowcount)

    async def get_trip(self, user_id: UserId, trip_id: UUID) -> Trip | None:
        row = (
            await self._db.execute(
                select(trips).where(trips.c.user_id == user_id, trips.c.id == trip_id)
            )
        ).first()
        return _trip(row) if row else None

    async def list_trips(self, user_id: UserId) -> list[Trip]:
        rows = await self._db.execute(
            select(trips)
            .where(trips.c.user_id == user_id)
            .order_by(trips.c.start_on.desc(), trips.c.created_at.desc())
        )
        return [_trip(r) for r in rows]

    async def set_link(
        self, user_id: UserId, trip_id: UUID, transaction_id: UUID, *, included: bool, at: datetime
    ) -> None:
        stmt = pg_insert(trip_links).values(
            user_id=user_id,
            trip_id=trip_id,
            transaction_id=transaction_id,
            included=included,
            created_at=at,
        )
        await self._db.execute(
            stmt.on_conflict_do_update(
                index_elements=[trip_links.c.trip_id, trip_links.c.transaction_id],
                set_={"included": included, "created_at": at},
            )
        )

    async def remove_link(self, user_id: UserId, trip_id: UUID, transaction_id: UUID) -> None:
        await self._db.execute(
            delete(trip_links).where(
                trip_links.c.user_id == user_id,
                trip_links.c.trip_id == trip_id,
                trip_links.c.transaction_id == transaction_id,
            )
        )

    async def trip_expenses(
        self, user_id: UserId, trip: Trip, timezone: str, *, limit: int
    ) -> list[TripExpense]:
        """Live, confirmed money out on the trip: added by hand, or in the trip's
        currency on one of its days (local time), unless taken off by hand."""
        t, link = transactions.c, trip_links.c
        day = cast(func.timezone(timezone, t.occurred_at), Date)

        def linked(included: bool) -> Any:
            return exists().where(
                link.trip_id == trip.id,
                link.user_id == t.user_id,
                link.transaction_id == t.id,
                link.included.is_(included),
            )

        others = (
            select(func.coalesce(func.sum(splits.c.share_amount), 0))
            .where(splits.c.transaction_id == t.id, splits.c.user_id == t.user_id)
            .scalar_subquery()
        )
        by_dates = and_(t.currency == trip.currency, day >= trip.start, day <= trip.end)
        rows = await self._db.execute(
            select(
                transactions,
                others.label("others"),
                categories.c.name.label("category"),
                linked(True).label("linked"),
                day.label("local_day"),
            )
            .select_from(
                transactions.outerjoin(
                    categories,
                    and_(categories.c.id == t.category_id, categories.c.user_id == t.user_id),
                )
            )
            .where(
                t.user_id == user_id,
                t.deleted_at.is_(None),
                t.status == TransactionStatus.CONFIRMED.value,
                t.direction == Direction.OUT.value,
                or_(linked(True), and_(by_dates, ~linked(False))),
            )
            .order_by(t.occurred_at, t.id)
            .limit(limit)
        )
        return [
            TripExpense(
                transaction=_transaction(r),
                others=Money(r.others, r.currency),
                category=r.category,
                linked=bool(r.linked),
                day=r.local_day,
            )
            for r in rows
        ]

    async def trips_on(self, user_id: UserId, day: date) -> list[Trip]:
        rows = await self._db.execute(
            select(trips).where(
                trips.c.user_id == user_id, trips.c.start_on <= day, trips.c.end_on >= day
            )
        )
        return [_trip(r) for r in rows]

    # --- bookings ---------------------------------------------------------------------

    async def insert_booking(self, booking: Booking) -> bool:
        """False when that email's booking is already saved."""
        d = booking.draft
        stmt = (
            pg_insert(trip_bookings)
            .values(
                id=booking.id,
                user_id=booking.user_id,
                trip_id=booking.trip_id,
                email_id=booking.email_id,
                kind=d.kind.value,
                title=d.title,
                start_on=booking.starts,
                end_on=d.ends,
                details=d.as_dict(),
                amount=booking.cost.amount if booking.cost else None,
                currency=booking.cost.currency if booking.cost else None,
                transaction_id=booking.transaction_id,
                created_at=booking.created_at,
            )
            .on_conflict_do_nothing()
            .returning(trip_bookings.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None

    async def get_booking(self, user_id: UserId, booking_id: UUID) -> Booking | None:
        row = (
            await self._db.execute(
                select(trip_bookings).where(
                    trip_bookings.c.user_id == user_id, trip_bookings.c.id == booking_id
                )
            )
        ).first()
        return _booking(row) if row else None

    async def booking_for_email(self, user_id: UserId, email_id: UUID) -> Booking | None:
        row = (
            await self._db.execute(
                select(trip_bookings).where(
                    trip_bookings.c.user_id == user_id, trip_bookings.c.email_id == email_id
                )
            )
        ).first()
        return _booking(row) if row else None

    async def list_bookings(
        self, user_id: UserId, *, trip_id: UUID | None = None, unattached: bool = False
    ) -> list[Booking]:
        b = trip_bookings.c
        conditions: list[Any] = [b.user_id == user_id]
        if trip_id is not None:
            conditions.append(b.trip_id == trip_id)
        if unattached:
            conditions.append(b.trip_id.is_(None))
        rows = await self._db.execute(
            select(trip_bookings).where(*conditions).order_by(b.start_on, b.created_at)
        )
        return [_booking(r) for r in rows]

    async def upcoming_bookings(self, user_id: UserId, since: date) -> list[Booking]:
        b = trip_bookings.c
        rows = await self._db.execute(
            select(trip_bookings)
            .where(b.user_id == user_id, func.coalesce(b.end_on, b.start_on) >= since)
            .order_by(b.start_on)
        )
        return [_booking(r) for r in rows]

    async def set_booking(
        self,
        user_id: UserId,
        booking_id: UUID,
        *,
        trip_id: UUID | None,
        transaction_id: UUID | None,
    ) -> None:
        await self._db.execute(
            update(trip_bookings)
            .where(trip_bookings.c.user_id == user_id, trip_bookings.c.id == booking_id)
            .values(trip_id=trip_id, transaction_id=transaction_id)
        )

    async def update_booking(self, booking: Booking) -> None:
        d = booking.draft
        await self._db.execute(
            update(trip_bookings)
            .where(trip_bookings.c.user_id == booking.user_id, trip_bookings.c.id == booking.id)
            .values(
                kind=d.kind.value,
                title=d.title,
                start_on=booking.starts,
                end_on=d.ends,
                details=d.as_dict(),
                amount=booking.cost.amount if booking.cost else None,
                currency=booking.cost.currency if booking.cost else None,
            )
        )

    async def delete_booking(self, user_id: UserId, booking_id: UUID) -> bool:
        result = await self._db.execute(
            delete(trip_bookings).where(
                trip_bookings.c.user_id == user_id, trip_bookings.c.id == booking_id
            )
        )
        return bool(result.rowcount)

    # --- reminders --------------------------------------------------------------------

    async def claim_reminder(self, user_id: UserId, key: str, at: datetime) -> bool:
        """True the first time only: the reminder is then the caller's to send."""
        stmt = (
            pg_insert(trip_reminders)
            .values(user_id=user_id, key=key, sent_at=at)
            .on_conflict_do_nothing()
            .returning(trip_reminders.c.key)
        )
        return (await self._db.execute(stmt)).first() is not None

    async def travellers(self, since: date) -> list[UserId]:
        """Users with a trip not yet over or a booking still ahead."""
        rows = await self._db.execute(
            select(trips.c.user_id)
            .where(trips.c.end_on >= since)
            .union(
                select(trip_bookings.c.user_id).where(
                    func.coalesce(trip_bookings.c.end_on, trip_bookings.c.start_on) >= since
                )
            )
        )
        return [UserId(r[0]) for r in rows]


def _booking(row: Row[Any]) -> Booking:
    draft = BookingDraft.from_dict(row.details)
    if draft is None:  # pragma: no cover - only valid drafts are stored
        raise ValueError(f"booking {row.id} has unreadable details")
    return Booking(
        id=row.id,
        user_id=UserId(row.user_id),
        trip_id=row.trip_id,
        email_id=row.email_id,
        draft=draft,
        cost=Money(row.amount, row.currency) if row.amount is not None else None,
        transaction_id=row.transaction_id,
        created_at=row.created_at,
    )
