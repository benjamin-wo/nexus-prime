"""PostgreSQL implementation of the ledger port. Every query filters on user_id."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, and_, delete, exists, func, insert, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.application.ports import (
    CategoryTotal,
    DirectionTotal,
    LedgerQuery,
    Page,
    SortField,
)
from nexus.domain.errors import Conflict, DuplicateSource
from nexus.domain.ledger import (
    Category,
    Direction,
    OpenIou,
    Revision,
    RevisionKind,
    Role,
    Settlement,
    Source,
    Split,
    Transaction,
    TransactionStatus,
    User,
    UserId,
)
from nexus.domain.money import Money
from nexus.infra.db.tables import (
    capability_gaps,
    categories,
    inbound_events,
    settlements,
    splits,
    transaction_revisions,
    transaction_sources,
    transactions,
    users,
)


def _user(row: Row[Any]) -> User:
    return User(
        id=UserId(row.id),
        telegram_user_id=row.telegram_user_id,
        telegram_chat_id=row.telegram_chat_id,
        timezone=row.timezone,
        home_currency=row.home_currency,
        role=Role(row.role),
        created_at=row.created_at,
    )


def _category(row: Row[Any]) -> Category:
    return Category(id=row.id, user_id=UserId(row.user_id), name=row.name, active=row.active)


def _transaction(row: Row[Any]) -> Transaction:
    return Transaction(
        id=row.id,
        user_id=UserId(row.user_id),
        direction=Direction(row.direction),
        amount=Money(row.amount, row.currency),
        occurred_at=row.occurred_at,
        counterparty=row.counterparty,
        category_id=row.category_id,
        notes=row.notes,
        status=TransactionStatus(row.status),
        source=Source(row.source),
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def _transaction_values(tx: Transaction) -> dict[str, Any]:
    return {
        "direction": tx.direction.value,
        "amount": tx.amount.amount,
        "currency": tx.amount.currency,
        "occurred_at": tx.occurred_at,
        "counterparty": tx.counterparty,
        "category_id": tx.category_id,
        "notes": tx.notes,
        "status": tx.status.value,
        "source": tx.source.value,
        "updated_at": tx.updated_at,
        "deleted_at": tx.deleted_at,
    }


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqlLedgerRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._db = connection

    # --- users ----------------------------------------------------------------

    async def insert_user_if_absent(self, user: User) -> bool:
        stmt = (
            pg_insert(users)
            .values(
                id=user.id,
                telegram_user_id=user.telegram_user_id,
                telegram_chat_id=user.telegram_chat_id,
                timezone=user.timezone,
                home_currency=user.home_currency,
                role=user.role.value,
                created_at=user.created_at,
            )
            .on_conflict_do_nothing(index_elements=[users.c.telegram_user_id])
            .returning(users.c.id)
        )
        return (await self._db.execute(stmt)).first() is not None

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        row = (
            await self._db.execute(
                select(users).where(users.c.telegram_user_id == telegram_user_id)
            )
        ).first()
        return _user(row) if row else None

    async def get_user(self, user_id: UserId) -> User | None:
        row = (await self._db.execute(select(users).where(users.c.id == user_id))).first()
        return _user(row) if row else None

    # --- categories -------------------------------------------------------------

    async def _write_category(self, stmt: Any) -> None:
        try:
            async with self._db.begin_nested():
                await self._db.execute(stmt)
        except IntegrityError as exc:
            if "uq_categories_user_id_lower_name" in str(exc.orig):
                raise Conflict("a category with that name already exists") from exc
            raise

    async def insert_category(self, category: Category) -> None:
        await self._write_category(
            insert(categories).values(
                id=category.id,
                user_id=category.user_id,
                name=category.name,
                active=category.active,
            )
        )

    async def get_category(self, user_id: UserId, category_id: UUID) -> Category | None:
        row = (
            await self._db.execute(
                select(categories).where(
                    categories.c.user_id == user_id, categories.c.id == category_id
                )
            )
        ).first()
        return _category(row) if row else None

    async def list_categories(self, user_id: UserId, *, include_inactive: bool) -> list[Category]:
        stmt = select(categories).where(categories.c.user_id == user_id)
        if not include_inactive:
            stmt = stmt.where(categories.c.active.is_(True))
        rows = await self._db.execute(stmt.order_by(func.lower(categories.c.name)))
        return [_category(r) for r in rows]

    async def update_category(self, category: Category) -> None:
        await self._write_category(
            update(categories)
            .where(categories.c.user_id == category.user_id, categories.c.id == category.id)
            .values(name=category.name, active=category.active)
        )

    # --- transactions -------------------------------------------------------------

    async def insert_transaction(self, tx: Transaction) -> None:
        await self._db.execute(
            insert(transactions).values(
                id=tx.id, user_id=tx.user_id, created_at=tx.created_at, **_transaction_values(tx)
            )
        )

    async def get_transaction(
        self, user_id: UserId, transaction_id: UUID, *, for_update: bool = False
    ) -> Transaction | None:
        stmt = select(transactions).where(
            transactions.c.user_id == user_id, transactions.c.id == transaction_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._db.execute(stmt)).first()
        return _transaction(row) if row else None

    async def update_transaction(self, tx: Transaction) -> None:
        await self._db.execute(
            update(transactions)
            .where(transactions.c.user_id == tx.user_id, transactions.c.id == tx.id)
            .values(**_transaction_values(tx))
        )

    async def list_transactions(self, user_id: UserId, query: LedgerQuery) -> Page:
        t = transactions.c
        conditions: list[Any] = [t.user_id == user_id]
        if query.only_deleted:
            conditions.append(t.deleted_at.is_not(None))
        elif not query.include_deleted:
            conditions.append(t.deleted_at.is_(None))
        if query.direction is not None:
            conditions.append(t.direction == query.direction.value)
        if query.start is not None:
            conditions.append(t.occurred_at >= query.start)
        if query.end is not None:
            conditions.append(t.occurred_at < query.end)
        if query.category_id is not None:
            conditions.append(t.category_id == query.category_id)
        if query.uncategorized:
            conditions.append(t.category_id.is_(None))
        if query.source is not None:
            conditions.append(t.source == query.source.value)
        if query.status is not None:
            conditions.append(t.status == query.status.value)
        if query.search:
            pattern = f"%{_escape_like(query.search)}%"
            conditions.append(
                or_(
                    t.counterparty.ilike(pattern, escape="\\"),
                    t.notes.ilike(pattern, escape="\\"),
                )
            )
        where = and_(*conditions)

        total = (
            await self._db.execute(select(func.count()).select_from(transactions).where(where))
        ).scalar_one()
        sort_col = t.amount if query.sort is SortField.AMOUNT else t.occurred_at
        order = [sort_col.desc(), t.id.desc()] if query.descending else [sort_col.asc(), t.id.asc()]
        rows = await self._db.execute(
            select(transactions)
            .where(where)
            .order_by(*order)
            .limit(query.limit)
            .offset(query.offset)
        )
        return Page([_transaction(r) for r in rows], total)

    def _counted(self, user_id: UserId, start: datetime, end: datetime) -> Any:
        t = transactions.c
        return and_(
            t.user_id == user_id,
            t.deleted_at.is_(None),
            t.status == TransactionStatus.CONFIRMED.value,
            t.occurred_at >= start,
            t.occurred_at < end,
        )

    async def totals_by_direction(
        self, user_id: UserId, start: datetime, end: datetime
    ) -> list[DirectionTotal]:
        t = transactions.c
        rows = await self._db.execute(
            select(t.direction, t.currency, func.sum(t.amount), func.count())
            .where(self._counted(user_id, start, end))
            .group_by(t.direction, t.currency)
            .order_by(t.direction, t.currency)
        )
        return [
            DirectionTotal(Direction(direction), Money(total, currency), count)
            for direction, currency, total, count in rows
        ]

    async def spending_by_category(
        self, user_id: UserId, start: datetime, end: datetime
    ) -> list[CategoryTotal]:
        t = transactions.c
        total = func.sum(t.amount)
        rows = await self._db.execute(
            select(t.category_id, categories.c.name, t.currency, total, func.count())
            .select_from(
                transactions.outerjoin(
                    categories,
                    and_(categories.c.id == t.category_id, categories.c.user_id == t.user_id),
                )
            )
            .where(self._counted(user_id, start, end), t.direction == Direction.OUT.value)
            .group_by(t.category_id, categories.c.name, t.currency)
            .order_by(t.currency, total.desc())
        )
        return [
            CategoryTotal(category_id, name, Money(amount, currency), count)
            for category_id, name, currency, amount, count in rows
        ]

    # --- sources --------------------------------------------------------------------

    async def source_claimed(self, user_id: UserId, source: Source, external_id: str) -> bool:
        s = transaction_sources.c
        stmt = select(
            exists().where(
                s.user_id == user_id, s.source == source.value, s.external_id == external_id
            )
        )
        return bool((await self._db.execute(stmt)).scalar_one())

    async def claim_source(
        self, user_id: UserId, source: Source, external_id: str, transaction_id: UUID | None
    ) -> None:
        s = transaction_sources.c
        claimed = (
            await self._db.execute(
                pg_insert(transaction_sources)
                .values(
                    user_id=user_id,
                    source=source.value,
                    external_id=external_id,
                    transaction_id=transaction_id,
                )
                .on_conflict_do_nothing(index_elements=[s.user_id, s.source, s.external_id])
                .returning(s.id)
            )
        ).first()
        if claimed is None:
            existing = (
                await self._db.execute(
                    select(s.transaction_id).where(
                        s.user_id == user_id, s.source == source.value, s.external_id == external_id
                    )
                )
            ).scalar_one_or_none()
            raise DuplicateSource(source.value, external_id, existing)

    # --- revisions ------------------------------------------------------------------

    async def insert_revision(
        self,
        user_id: UserId,
        transaction_id: UUID,
        kind: RevisionKind,
        before: dict[str, Any] | None,
        created_at: datetime,
    ) -> None:
        await self._db.execute(
            insert(transaction_revisions).values(
                user_id=user_id,
                transaction_id=transaction_id,
                kind=kind.value,
                before=before,
                created_at=created_at,
            )
        )

    async def latest_open_revision(self, user_id: UserId) -> Revision | None:
        r = transaction_revisions.c
        row = (
            await self._db.execute(
                select(transaction_revisions)
                .where(r.user_id == user_id, r.undone_at.is_(None))
                .order_by(r.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).first()
        if row is None:
            return None
        return Revision(
            id=row.id,
            user_id=UserId(row.user_id),
            transaction_id=row.transaction_id,
            kind=RevisionKind(row.kind),
            before=row.before,
            created_at=row.created_at,
            undone_at=row.undone_at,
        )

    async def mark_undone(self, user_id: UserId, revision_id: int, at: datetime) -> None:
        r = transaction_revisions.c
        await self._db.execute(
            update(transaction_revisions)
            .where(r.user_id == user_id, r.id == revision_id)
            .values(undone_at=at)
        )

    # --- splits and settlements -----------------------------------------------------

    async def list_splits(self, user_id: UserId, transaction_id: UUID) -> list[Split]:
        rows = await self._db.execute(
            select(splits, transactions.c.currency)
            .join(
                transactions,
                and_(
                    transactions.c.id == splits.c.transaction_id,
                    transactions.c.user_id == splits.c.user_id,
                ),
            )
            .where(splits.c.user_id == user_id, splits.c.transaction_id == transaction_id)
            .order_by(splits.c.created_at, splits.c.participant_name)
        )
        return [
            Split(
                r.id,
                UserId(r.user_id),
                r.transaction_id,
                r.participant_name,
                Money(r.share_amount, r.currency),
            )
            for r in rows
        ]

    async def has_settlements(self, user_id: UserId, transaction_id: UUID) -> bool:
        stmt = select(
            exists().where(
                settlements.c.user_id == user_id,
                settlements.c.split_id == splits.c.id,
                splits.c.user_id == user_id,
                splits.c.transaction_id == transaction_id,
            )
        )
        return bool((await self._db.execute(stmt)).scalar_one())

    async def replace_splits(
        self, user_id: UserId, transaction_id: UUID, new_splits: list[Split]
    ) -> None:
        await self._db.execute(
            delete(splits).where(
                splits.c.user_id == user_id, splits.c.transaction_id == transaction_id
            )
        )
        if new_splits:
            await self._db.execute(
                insert(splits),
                [
                    {
                        "id": s.id,
                        "user_id": user_id,
                        "transaction_id": transaction_id,
                        "participant_name": s.participant_name,
                        "share_amount": s.share.amount,
                    }
                    for s in new_splits
                ],
            )

    async def open_ious(
        self, user_id: UserId, *, participant_name: str | None = None, for_update: bool = False
    ) -> list[OpenIou]:
        s, t = splits.c, transactions.c
        income = transactions.alias("income")
        name_filter = (
            [func.lower(s.participant_name) == func.lower(literal(participant_name))]
            if participant_name is not None
            else []
        )
        if for_update:
            # Serialise concurrent repayments for the same participant.
            await self._db.execute(
                select(s.id).where(s.user_id == user_id, *name_filter).with_for_update()
            )
        repaid = func.coalesce(
            func.sum(settlements.c.amount).filter(income.c.deleted_at.is_(None)), 0
        )
        outstanding = s.share_amount - repaid
        rows = await self._db.execute(
            select(splits, t.currency, t.occurred_at.label("expense_occurred_at"), outstanding)
            .select_from(
                splits.join(transactions, and_(t.id == s.transaction_id, t.user_id == s.user_id))
                .outerjoin(
                    settlements,
                    and_(settlements.c.split_id == s.id, settlements.c.user_id == s.user_id),
                )
                .outerjoin(
                    income,
                    and_(
                        income.c.id == settlements.c.income_transaction_id,
                        income.c.user_id == settlements.c.user_id,
                    ),
                )
            )
            .where(s.user_id == user_id, t.deleted_at.is_(None), *name_filter)
            .group_by(s.id, t.currency, t.occurred_at)
            .having(outstanding > 0)
            .order_by(t.occurred_at, s.id)
        )
        return [
            OpenIou(
                split=Split(
                    r.id,
                    UserId(r.user_id),
                    r.transaction_id,
                    r.participant_name,
                    Money(r.share_amount, r.currency),
                ),
                outstanding=Money(r[-1], r.currency),
                expense_occurred_at=r.expense_occurred_at,
            )
            for r in rows
        ]

    async def insert_settlements(self, new_settlements: list[Settlement]) -> None:
        if not new_settlements:
            return
        await self._db.execute(
            insert(settlements),
            [
                {
                    "id": st.id,
                    "user_id": st.user_id,
                    "split_id": st.split_id,
                    "income_transaction_id": st.income_transaction_id,
                    "amount": st.amount.amount,
                }
                for st in new_settlements
            ],
        )

    # --- channel bookkeeping --------------------------------------------------------

    async def claim_inbound_event(self, channel: str, event_id: str) -> bool:
        claimed = await self._db.execute(
            pg_insert(inbound_events)
            .values(channel=channel, event_id=event_id)
            .on_conflict_do_nothing()
            .returning(inbound_events.c.event_id)
        )
        return claimed.first() is not None

    async def insert_capability_gap(
        self, user_id: UserId, request: str, intent: str, channel: str
    ) -> None:
        await self._db.execute(
            insert(capability_gaps).values(
                user_id=user_id, request=request[:1000], intent=intent, channel=channel
            )
        )
