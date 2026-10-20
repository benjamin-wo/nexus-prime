"""PostgreSQL storage for trips. Every query filters on user_id."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Date, Row, and_, cast, delete, exists, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.application.ports import TripExpense
from nexus.domain.bookings import Booking, BookingDraft
from nexus.domain.destination_photos import DestinationPhoto, Season
from nexus.domain.ledger import Direction, TransactionStatus, UserId
from nexus.domain.money import Money
from nexus.domain.packing import PackItem, from_rows
from nexus.domain.prep import Cover, CoverDraft, CoverKind, Todo
from nexus.domain.prep import from_rows as todos_from_rows
from nexus.domain.settle import PaidByOther
from nexus.domain.trip_access import (
    UNKNOWN_NAME,
    Activity,
    DigestState,
    TripAccess,
    TripInvite,
    TripMember,
    TripRole,
)
from nexus.domain.trips import GettingAround, Share, Stop, Trip
from nexus.infra.db.ledger_repository import _transaction
from nexus.infra.db.tables import (
    categories,
    destination_photos,
    splits,
    transactions,
    trip_activity,
    trip_bookings,
    trip_covers,
    trip_invites,
    trip_links,
    trip_members,
    trip_paid_by_others,
    trip_reminders,
    trip_shares,
    trips,
    users,
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
        day_labels={date.fromisoformat(k): v for k, v in (row.day_labels or {}).items()},
        photo_id=row.photo_id,
        photo_off=row.photo_off,
        packing=from_rows(row.packing),
        getting_around=GettingAround(row.getting_around),
        hop_modes={k: v for k, v in (row.hop_modes or {}).items() if isinstance(v, str)},
        stops=tuple(
            Stop(r["name"], date.fromisoformat(r["start"]), date.fromisoformat(r["end"]))
            for r in (row.stops or [])
        ),
        split_evenly=row.split_evenly,
        not_split=tuple(UUID(i) for i in (row.not_split or [])),
        todos=todos_from_rows(row.todos),
        prep_dismissed=tuple(k for k in (row.prep_dismissed or []) if isinstance(k, str)),
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
        "day_labels": {k.isoformat(): v for k, v in sorted(trip.day_labels.items())},
        "getting_around": trip.getting_around.value,
        "hop_modes": trip.hop_modes,
        "stops": [
            {"name": s.name, "start": s.start.isoformat(), "end": s.end.isoformat()}
            for s in trip.stops
        ],
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
                start_on=d.starts,
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

    async def get_share(self, user_id: UserId, trip_id: UUID) -> Share | None:
        row = (
            await self._db.execute(
                select(trip_shares.c.token, trip_shares.c.show_bookings).where(
                    trip_shares.c.user_id == user_id, trip_shares.c.trip_id == trip_id
                )
            )
        ).first()
        return Share(row.token, row.show_bookings) if row else None

    async def set_share(self, user_id: UserId, trip_id: UUID, share: Share, at: datetime) -> None:
        values = {
            "trip_id": trip_id,
            "user_id": user_id,
            "token": share.token,
            "show_bookings": share.show_bookings,
            "created_at": at,
        }
        await self._db.execute(
            pg_insert(trip_shares)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[trip_shares.c.trip_id],
                set_={
                    "token": share.token,
                    "show_bookings": share.show_bookings,
                    "created_at": at,
                },
            )
        )

    async def set_show_bookings(self, user_id: UserId, trip_id: UUID, show: bool) -> None:
        await self._db.execute(
            update(trip_shares)
            .where(trip_shares.c.user_id == user_id, trip_shares.c.trip_id == trip_id)
            .values(show_bookings=show)
        )

    async def remove_share(self, user_id: UserId, trip_id: UUID) -> bool:
        result = await self._db.execute(
            delete(trip_shares).where(
                trip_shares.c.user_id == user_id, trip_shares.c.trip_id == trip_id
            )
        )
        return bool(result.rowcount)

    async def shared_trip(self, token: str) -> tuple[Trip, Share] | None:
        row = (
            await self._db.execute(
                select(trips, trip_shares.c.show_bookings)
                .join(trip_shares, trip_shares.c.trip_id == trips.c.id)
                .where(trip_shares.c.token == token)
            )
        ).first()
        return (_trip(row), Share(token, row.show_bookings)) if row else None

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
                start_on=d.starts,
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

    # --- splitting costs and settling up ---------------------------------------------

    async def set_split_evenly(self, user_id: UserId, trip_id: UUID, on: bool) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(split_evenly=on)
        )

    async def set_not_split(self, user_id: UserId, trip_id: UUID, ids: tuple[UUID, ...]) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(not_split=[str(i) for i in ids])
        )

    async def insert_payment(self, payment: PaidByOther) -> None:
        await self._db.execute(insert(trip_paid_by_others).values(**_payment_values(payment)))

    async def update_payment(self, payment: PaidByOther) -> None:
        values = _payment_values(payment)
        for fixed in ("id", "user_id", "trip_id", "created_at"):
            del values[fixed]
        await self._db.execute(
            update(trip_paid_by_others)
            .where(
                trip_paid_by_others.c.user_id == payment.user_id,
                trip_paid_by_others.c.trip_id == payment.trip_id,
                trip_paid_by_others.c.id == payment.id,
            )
            .values(**values)
        )

    async def get_payment(
        self, user_id: UserId, trip_id: UUID, payment_id: UUID, *, for_update: bool = False
    ) -> PaidByOther | None:
        p = trip_paid_by_others.c
        query = select(trip_paid_by_others).where(
            p.user_id == user_id, p.trip_id == trip_id, p.id == payment_id
        )
        row = (await self._db.execute(query.with_for_update() if for_update else query)).first()
        return _payment(row) if row else None

    async def list_payments(self, user_id: UserId, trip_id: UUID) -> list[PaidByOther]:
        p = trip_paid_by_others.c
        rows = await self._db.execute(
            select(trip_paid_by_others)
            .where(p.user_id == user_id, p.trip_id == trip_id)
            .order_by(p.paid_on, p.created_at, p.id)
        )
        return [_payment(r) for r in rows]

    async def delete_payment(self, user_id: UserId, trip_id: UUID, payment_id: UUID) -> bool:
        p = trip_paid_by_others.c
        result = await self._db.execute(
            delete(trip_paid_by_others).where(
                p.user_id == user_id, p.trip_id == trip_id, p.id == payment_id
            )
        )
        return bool(result.rowcount)

    async def set_payment_settled(
        self, user_id: UserId, trip_id: UUID, payment_id: UUID, at: datetime | None
    ) -> None:
        p = trip_paid_by_others.c
        await self._db.execute(
            update(trip_paid_by_others)
            .where(p.user_id == user_id, p.trip_id == trip_id, p.id == payment_id)
            .values(settled_at=at)
        )

    # --- sharing a trip's plan with other people --------------------------------------

    async def trip_access(self, actor_id: UserId, trip_id: UUID) -> TripAccess | None:
        row = (
            await self._db.execute(
                select(trips.c.user_id, trip_members.c.member_id)
                .select_from(
                    trips.outerjoin(
                        trip_members,
                        and_(
                            trip_members.c.trip_id == trips.c.id,
                            trip_members.c.member_id == actor_id,
                        ),
                    )
                )
                .where(
                    trips.c.id == trip_id,
                    or_(trips.c.user_id == actor_id, trip_members.c.member_id.is_not(None)),
                )
            )
        ).first()
        if row is None:
            return None
        owner = UserId(row.user_id)
        role = TripRole.OWNER if owner == actor_id else TripRole.MEMBER
        return TripAccess(owner, actor_id, role, trip_id)

    async def booking_access(self, actor_id: UserId, booking_id: UUID) -> TripAccess | None:
        b = trip_bookings.c
        row = (
            await self._db.execute(select(b.user_id, b.trip_id).where(b.id == booking_id))
        ).first()
        if row is None:
            return None
        owner = UserId(row.user_id)
        if owner == actor_id:
            return TripAccess(owner, actor_id, TripRole.OWNER, row.trip_id)
        if row.trip_id is None:
            return None
        found = await self.trip_access(actor_id, row.trip_id)
        # Only through the booking's own trip: the trip ids must agree on the owner.
        return found if found is not None and found.owner_id == owner else None

    async def list_member_trips(self, member_id: UserId) -> list[tuple[Trip, str | None]]:
        rows = await self._db.execute(
            select(trips, users.c.display_name.label("owner_name"))
            .select_from(
                trips.join(
                    trip_members,
                    and_(
                        trip_members.c.trip_id == trips.c.id,
                        trip_members.c.owner_id == trips.c.user_id,
                    ),
                ).join(users, users.c.id == trips.c.user_id)
            )
            .where(trip_members.c.member_id == member_id)
            .order_by(trips.c.start_on.desc(), trips.c.created_at.desc())
        )
        return [(_trip(r), r.owner_name) for r in rows]

    async def owner_name(self, owner_id: UserId) -> str | None:
        return (
            await self._db.execute(select(users.c.display_name).where(users.c.id == owner_id))
        ).scalar_one_or_none()

    async def list_members(self, owner_id: UserId, trip_id: UUID) -> list[TripMember]:
        owner_name = await self.owner_name(owner_id)
        members = [TripMember(owner_id, owner_name or UNKNOWN_NAME, TripRole.OWNER, None)]
        rows = await self._db.execute(
            select(trip_members.c.member_id, trip_members.c.added_at, users.c.display_name)
            .join(users, users.c.id == trip_members.c.member_id)
            .where(trip_members.c.owner_id == owner_id, trip_members.c.trip_id == trip_id)
            .order_by(trip_members.c.added_at, trip_members.c.id)
        )
        members += [
            TripMember(
                UserId(r.member_id), r.display_name or UNKNOWN_NAME, TripRole.MEMBER, r.added_at
            )
            for r in rows
        ]
        return members

    async def count_members(self, trip_id: UUID) -> int:
        return int(
            (
                await self._db.execute(
                    select(func.count())
                    .select_from(trip_members)
                    .where(trip_members.c.trip_id == trip_id)
                )
            ).scalar_one()
        )

    async def add_member(
        self,
        owner_id: UserId,
        trip_id: UUID,
        member_id: UserId,
        invite_id: UUID | None,
        at: datetime,
    ) -> bool:
        stmt = (
            pg_insert(trip_members)
            .values(
                id=uuid4(),
                trip_id=trip_id,
                owner_id=owner_id,
                member_id=member_id,
                added_at=at,
                added_by_invite=invite_id,
            )
            .on_conflict_do_nothing(
                index_elements=[trip_members.c.trip_id, trip_members.c.member_id]
            )
            .returning(trip_members.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None

    async def remove_member(self, owner_id: UserId, trip_id: UUID, member_id: UserId) -> bool:
        result = await self._db.execute(
            delete(trip_members).where(
                trip_members.c.owner_id == owner_id,
                trip_members.c.trip_id == trip_id,
                trip_members.c.member_id == member_id,
            )
        )
        return bool(result.rowcount)

    async def insert_trip_invite(self, invite: TripInvite) -> None:
        await self._db.execute(
            insert(trip_invites).values(
                id=invite.id,
                token_hash=invite.token_hash,
                trip_id=invite.trip_id,
                owner_id=invite.owner_id,
                created_at=invite.created_at,
                expires_at=invite.expires_at,
                may_create_guest=invite.may_create_guest,
            )
        )

    async def get_trip_invite(
        self, token_hash: str, *, for_update: bool = False
    ) -> TripInvite | None:
        query = select(trip_invites).where(trip_invites.c.token_hash == token_hash)
        row = (await self._db.execute(query.with_for_update() if for_update else query)).first()
        return _trip_invite(row) if row else None

    async def list_open_trip_invites(
        self, owner_id: UserId, trip_id: UUID, now: datetime
    ) -> list[TripInvite]:
        i = trip_invites.c
        rows = await self._db.execute(
            select(trip_invites)
            .where(
                i.owner_id == owner_id,
                i.trip_id == trip_id,
                i.redeemed_at.is_(None),
                i.revoked_at.is_(None),
                i.expires_at > now,
            )
            .order_by(i.created_at, i.id)
        )
        return [_trip_invite(r) for r in rows]

    async def revoke_trip_invite(
        self, owner_id: UserId, trip_id: UUID, invite_id: UUID, at: datetime
    ) -> bool:
        i = trip_invites.c
        result = await self._db.execute(
            update(trip_invites)
            .where(
                i.owner_id == owner_id,
                i.trip_id == trip_id,
                i.id == invite_id,
                i.redeemed_at.is_(None),
                i.revoked_at.is_(None),
            )
            .values(revoked_at=at)
        )
        return bool(result.rowcount)

    async def redeem_trip_invite(self, invite_id: UUID, user_id: UserId, at: datetime) -> bool:
        i = trip_invites.c
        result = await self._db.execute(
            update(trip_invites)
            .where(i.id == invite_id, i.redeemed_at.is_(None), i.revoked_at.is_(None))
            .values(redeemed_at=at, redeemed_by=user_id)
        )
        return bool(result.rowcount)

    async def add_activity(
        self, owner_id: UserId, trip_id: UUID, actor_id: UserId, summary: str, at: datetime
    ) -> None:
        await self._db.execute(
            insert(trip_activity).values(
                id=uuid4(),
                trip_id=trip_id,
                owner_id=owner_id,
                actor_id=actor_id,
                summary=summary,
                at=at,
            )
        )

    async def list_activity(self, owner_id: UserId, trip_id: UUID, *, limit: int) -> list[Activity]:
        a = trip_activity.c
        rows = await self._db.execute(
            select(a.summary, a.at, users.c.display_name)
            .join(users, users.c.id == a.actor_id)
            .where(a.owner_id == owner_id, a.trip_id == trip_id)
            .order_by(a.at.desc(), a.id)
            .limit(limit)
        )
        return [Activity(r.display_name or UNKNOWN_NAME, r.summary, r.at) for r in rows]

    async def digest_state(self, trip_id: UUID, *, for_update: bool = False) -> DigestState | None:
        stmt = select(trips.c.user_id, trips.c.destination, trips.c.activity_digest_at).where(
            trips.c.id == trip_id
        )
        if for_update:
            stmt = stmt.with_for_update(
                key_share=True
            )  # FOR NO KEY UPDATE: foreign keys still work
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return DigestState(UserId(row.user_id), row.destination, row.activity_digest_at)

    async def set_digest_at(self, trip_id: UUID, at: datetime) -> None:
        await self._db.execute(
            update(trips).where(trips.c.id == trip_id).values(activity_digest_at=at)
        )

    async def changes_by_others(
        self, owner_id: UserId, trip_id: UUID, *, after: datetime | None, until: datetime | None
    ) -> list[Activity]:
        a = trip_activity.c
        stmt = (
            select(a.summary, a.at, users.c.display_name)
            .join(users, users.c.id == a.actor_id)
            .where(a.owner_id == owner_id, a.trip_id == trip_id, a.actor_id != owner_id)
            .order_by(a.at, a.id)
        )
        if after is not None:
            stmt = stmt.where(a.at > after)
        if until is not None:
            stmt = stmt.where(a.at <= until)
        rows = await self._db.execute(stmt)
        return [Activity(r.display_name or UNKNOWN_NAME, r.summary, r.at) for r in rows]

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

    # --- header photos (shared by every user's trips to a place) -------------------

    async def place_photos(self, place_key: str) -> list[DestinationPhoto]:
        rows = await self._db.execute(
            select(*_PHOTO_COLUMNS).where(destination_photos.c.place_key == place_key)
        )
        return [_photo(r) for r in rows]

    async def save_photo(
        self, photo: DestinationPhoto, data: bytes | None, mime: str | None
    ) -> DestinationPhoto:
        """Keep a photo, or the note that none was found. A note is replaced by a
        later find; a photo already kept for the place and season stays, and is
        returned instead."""
        values = {
            "place_key": photo.place_key,
            "season": photo.season.value,
            "status": "ready" if photo.found else "none",
            "latitude": photo.latitude,
            "spot": photo.spot,
            "author": photo.author,
            "licence": photo.licence,
            "licence_url": photo.licence_url,
            "page": photo.page,
            "mime": mime,
            "data": data,
            "created_at": photo.created_at,
            "rank": photo.rank,
        }
        stmt = (
            pg_insert(destination_photos)
            .values(id=photo.id, **values)
            .on_conflict_do_update(
                index_elements=["place_key", "season", "rank"],
                set_=values,
                where=destination_photos.c.status == "none",
            )
            .returning(*_PHOTO_COLUMNS)
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            row = (
                await self._db.execute(
                    select(*_PHOTO_COLUMNS).where(
                        destination_photos.c.place_key == photo.place_key,
                        destination_photos.c.season == photo.season.value,
                        destination_photos.c.rank == photo.rank,
                    )
                )
            ).one()
        return _photo(row)

    async def photos(self, ids: list[UUID]) -> dict[UUID, DestinationPhoto]:
        if not ids:
            return {}
        rows = await self._db.execute(
            select(*_PHOTO_COLUMNS).where(destination_photos.c.id.in_(ids))
        )
        return {r.id: _photo(r) for r in rows}

    async def photo_file(self, photo_id: UUID) -> tuple[bytes, str] | None:
        row = (
            await self._db.execute(
                select(destination_photos.c.data, destination_photos.c.mime).where(
                    destination_photos.c.id == photo_id, destination_photos.c.status == "ready"
                )
            )
        ).first()
        return (bytes(row.data), row.mime) if row else None

    async def trips_needing_photos(
        self, since: date, tried_before: datetime, *, limit: int
    ) -> list[Trip]:
        """Trips not yet over, without a photo, not looked for since ``tried_before``;
        across users, the soonest first."""
        rows = await self._db.execute(
            select(trips)
            .where(
                trips.c.end_on >= since,
                trips.c.photo_id.is_(None),
                trips.c.photo_off.is_(False),
                or_(trips.c.photo_tried_at.is_(None), trips.c.photo_tried_at < tried_before),
            )
            .order_by(trips.c.start_on, trips.c.id)
            .limit(limit)
        )
        return [_trip(r) for r in rows]

    async def set_trip_photo(self, trip_id: UUID, photo_id: UUID | None, at: datetime) -> None:
        await self._db.execute(
            update(trips).where(trips.c.id == trip_id).values(photo_id=photo_id, photo_tried_at=at)
        )

    async def set_photo_choice(
        self, user_id: UserId, trip_id: UUID, photo_id: UUID | None, *, off: bool
    ) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(photo_id=photo_id, photo_off=off)
        )

    async def set_packing(
        self, user_id: UserId, trip_id: UUID, items: tuple[PackItem, ...], at: datetime
    ) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(packing=[i.to_dict() for i in items], updated_at=at)
        )

    # --- the Prep tab: to-dos, dismissed suggestions and cover ---------------------------

    async def set_todos(
        self, user_id: UserId, trip_id: UUID, todos: tuple[Todo, ...], at: datetime
    ) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(todos=[t.to_dict() for t in todos], updated_at=at)
        )

    async def set_prep_dismissed(
        self, user_id: UserId, trip_id: UUID, keys: tuple[str, ...], at: datetime
    ) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(prep_dismissed=list(keys), updated_at=at)
        )

    async def insert_cover(self, cover: Cover) -> None:
        await self._db.execute(insert(trip_covers).values(**_cover_values(cover)))

    async def update_cover(self, cover: Cover) -> None:
        values = _cover_values(cover)
        for fixed in ("id", "user_id", "trip_id", "created_at"):
            del values[fixed]
        c = trip_covers.c
        await self._db.execute(
            update(trip_covers)
            .where(c.user_id == cover.user_id, c.trip_id == cover.trip_id, c.id == cover.id)
            .values(**values)
        )

    async def get_cover(
        self, user_id: UserId, trip_id: UUID, cover_id: UUID, *, for_update: bool = False
    ) -> Cover | None:
        c = trip_covers.c
        query = select(trip_covers).where(
            c.user_id == user_id, c.trip_id == trip_id, c.id == cover_id
        )
        row = (await self._db.execute(query.with_for_update() if for_update else query)).first()
        return _cover(row) if row else None

    async def list_covers(self, user_id: UserId, trip_id: UUID) -> list[Cover]:
        c = trip_covers.c
        rows = await self._db.execute(
            select(trip_covers)
            .where(c.user_id == user_id, c.trip_id == trip_id)
            .order_by(c.created_at, c.id)
        )
        return [_cover(r) for r in rows]

    async def delete_cover(self, user_id: UserId, trip_id: UUID, cover_id: UUID) -> bool:
        c = trip_covers.c
        result = await self._db.execute(
            delete(trip_covers).where(c.user_id == user_id, c.trip_id == trip_id, c.id == cover_id)
        )
        return bool(result.rowcount)

    async def set_hop_modes(self, user_id: UserId, trip_id: UUID, modes: dict[str, str]) -> None:
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(hop_modes=modes)
        )

    async def clear_trip_photo(self, user_id: UserId, trip_id: UUID) -> None:
        """Look for a photo again: where or when the trip goes has changed."""
        await self._db.execute(
            update(trips)
            .where(trips.c.user_id == user_id, trips.c.id == trip_id)
            .values(photo_id=None, photo_tried_at=None)
        )


# Everything but the image bytes.
_PHOTO_COLUMNS = [c for c in destination_photos.c if c.name != "data"]


def _photo(row: Row[Any]) -> DestinationPhoto:
    return DestinationPhoto(
        id=row.id,
        place_key=row.place_key,
        season=Season(row.season),
        latitude=float(row.latitude) if row.latitude is not None else None,
        found=row.status == "ready",
        spot=row.spot,
        author=row.author,
        licence=row.licence,
        licence_url=row.licence_url,
        page=row.page,
        created_at=row.created_at,
        rank=row.rank,
    )


def _payment_values(payment: PaidByOther) -> dict[str, Any]:
    return {
        "id": payment.id,
        "user_id": payment.user_id,
        "trip_id": payment.trip_id,
        "person": payment.person,
        "amount": payment.amount.amount,
        "currency": payment.amount.currency,
        "note": payment.note,
        "paid_on": payment.paid_on,
        "split_with": list(payment.split_with),
        "settled_at": payment.settled_at,
        "created_at": payment.created_at,
    }


def _payment(row: Row[Any]) -> PaidByOther:
    return PaidByOther(
        id=row.id,
        user_id=UserId(row.user_id),
        trip_id=row.trip_id,
        person=row.person,
        amount=Money(row.amount, row.currency),
        note=row.note,
        paid_on=row.paid_on,
        split_with=tuple(row.split_with),
        settled_at=row.settled_at,
        created_at=row.created_at,
    )


def _cover_values(cover: Cover) -> dict[str, Any]:
    d = cover.draft
    return {
        "id": cover.id,
        "user_id": cover.user_id,
        "trip_id": cover.trip_id,
        "kind": d.kind.value,
        "name": d.name,
        "reference": d.reference,
        "phone": d.phone,
        "starts": d.starts,
        "ends": d.ends,
        "cost_amount": d.cost.amount if d.cost else None,
        "cost_currency": d.cost.currency if d.cost else None,
        "logged_transaction_id": cover.logged_transaction_id,
        "note": d.note,
        "created_at": cover.created_at,
        "updated_at": cover.updated_at,
    }


def _cover(row: Row[Any]) -> Cover:
    return Cover(
        id=row.id,
        user_id=UserId(row.user_id),
        trip_id=row.trip_id,
        draft=CoverDraft(
            kind=CoverKind(row.kind),
            name=row.name,
            reference=row.reference,
            phone=row.phone,
            starts=row.starts,
            ends=row.ends,
            cost=Money(row.cost_amount, row.cost_currency) if row.cost_amount is not None else None,
            note=row.note,
        ),
        logged_transaction_id=row.logged_transaction_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _trip_invite(row: Row[Any]) -> TripInvite:
    return TripInvite(
        id=row.id,
        token_hash=row.token_hash,
        trip_id=row.trip_id,
        owner_id=UserId(row.owner_id),
        created_at=row.created_at,
        expires_at=row.expires_at,
        may_create_guest=row.may_create_guest,
        redeemed_at=row.redeemed_at,
        redeemed_by=UserId(row.redeemed_by) if row.redeemed_by else None,
        revoked_at=row.revoked_at,
    )


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
