"""PostgreSQL implementation of the ledger port. Every query filters on user_id."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Date,
    Row,
    and_,
    case,
    cast,
    delete,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.application.ports import (
    CategoryTotal,
    DayTotal,
    DirectionTotal,
    LedgerQuery,
    Page,
    SortField,
)
from nexus.domain.access import Invite, Session
from nexus.domain.errors import Conflict, DuplicateSource
from nexus.domain.ledger import (
    Category,
    Direction,
    Lineage,
    Link,
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
from nexus.domain.receipts import RETENTION_AFTER_DELETE, UNCLAIMED_TTL, Receipt, purge_due
from nexus.domain.rules import CategoryRule
from nexus.infra.db.tables import (
    budgets,
    capability_gaps,
    categories,
    category_rules,
    duplicate_dismissals,
    inbound_events,
    invites,
    receipts,
    settlements,
    splits,
    transaction_revisions,
    transaction_sources,
    transactions,
    users,
    web_sessions,
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
        web_access_granted_at=row.web_access_granted_at,
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
        category_rule_id=row.category_rule_id,
    )


def _rule(row: Row[Any]) -> CategoryRule:
    return CategoryRule(
        id=row.id,
        user_id=UserId(row.user_id),
        pattern=row.pattern,
        category_id=row.category_id,
        explanation=row.explanation,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _receipt(row: Row[Any]) -> Receipt:
    return Receipt(
        id=row.id,
        user_id=UserId(row.user_id),
        transaction_id=row.transaction_id,
        object_key=row.object_key,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
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
        "category_rule_id": tx.category_rule_id,
    }


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _net_amount() -> ColumnElement[Any]:
    """A transaction's amount less what friends paid back on it: on a bill, the
    repayments against its shares; on money in, the part that repaid a bill. Only
    live transactions on the other side count, so deleting either undoes it."""
    t, sp, st = transactions.c, splits.c, settlements.c
    other = transactions.alias("other")
    shares = settlements.join(splits, and_(sp.id == st.split_id, sp.user_id == st.user_id))
    on_bill = (
        select(func.coalesce(func.sum(st.amount), 0))
        .select_from(
            shares.join(
                other,
                and_(other.c.id == st.income_transaction_id, other.c.user_id == st.user_id),
            )
        )
        .where(sp.transaction_id == t.id, sp.user_id == t.user_id, other.c.deleted_at.is_(None))
        .scalar_subquery()
    )
    by_income = (
        select(func.coalesce(func.sum(st.amount), 0))
        .select_from(
            shares.join(other, and_(other.c.id == sp.transaction_id, other.c.user_id == sp.user_id))
        )
        .where(
            st.income_transaction_id == t.id,
            st.user_id == t.user_id,
            other.c.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    return t.amount - case((t.direction == Direction.OUT.value, on_bill), else_=by_income)


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

    async def merge_category(
        self, user_id: UserId, source_id: UUID, target_id: UUID, now: datetime
    ) -> int:
        moved = await self._db.execute(
            update(transactions)
            .where(transactions.c.user_id == user_id, transactions.c.category_id == source_id)
            .values(category_id=target_id)
        )
        await self._db.execute(
            update(category_rules)
            .where(category_rules.c.user_id == user_id, category_rules.c.category_id == source_id)
            .values(category_id=target_id, updated_at=now)
        )
        # The target keeps its own budget if it has one; else the source's moves over.
        target_budget = exists().where(
            budgets.c.user_id == user_id, budgets.c.category_id == target_id
        )
        await self._db.execute(
            update(budgets)
            .where(budgets.c.user_id == user_id, budgets.c.category_id == source_id)
            .where(~target_budget)
            .values(category_id=target_id, updated_at=now)
        )
        await self._db.execute(
            update(categories)
            .where(categories.c.user_id == user_id, categories.c.id == source_id)
            .values(active=False)
        )
        return moved.rowcount

    # --- category rules -----------------------------------------------------------

    async def insert_category_rule(self, rule: CategoryRule) -> None:
        try:
            async with self._db.begin_nested():
                await self._db.execute(
                    insert(category_rules).values(
                        id=rule.id,
                        user_id=rule.user_id,
                        pattern=rule.pattern,
                        category_id=rule.category_id,
                        explanation=rule.explanation,
                        created_at=rule.created_at,
                        updated_at=rule.updated_at,
                        archived_at=rule.archived_at,
                    )
                )
        except IntegrityError as exc:
            if "uq_category_rules_user_id_pattern" in str(exc.orig):
                raise Conflict(f"there is already a rule for {rule.pattern!r}") from exc
            raise

    async def update_category_rule(self, rule: CategoryRule) -> None:
        await self._db.execute(
            update(category_rules)
            .where(category_rules.c.user_id == rule.user_id, category_rules.c.id == rule.id)
            .values(
                category_id=rule.category_id,
                explanation=rule.explanation,
                updated_at=rule.updated_at,
                archived_at=rule.archived_at,
            )
        )

    async def get_category_rule(self, user_id: UserId, rule_id: UUID) -> CategoryRule | None:
        row = (
            await self._db.execute(
                select(category_rules).where(
                    category_rules.c.user_id == user_id, category_rules.c.id == rule_id
                )
            )
        ).first()
        return _rule(row) if row else None

    async def list_category_rules(self, user_id: UserId) -> list[CategoryRule]:
        """Active rules, alphabetically by pattern."""
        rows = await self._db.execute(
            select(category_rules)
            .where(category_rules.c.user_id == user_id, category_rules.c.archived_at.is_(None))
            .order_by(category_rules.c.pattern)
        )
        return [_rule(row) for row in rows]

    # --- receipts -------------------------------------------------------------------

    async def insert_receipt(self, receipt: Receipt) -> None:
        await self._db.execute(
            insert(receipts).values(
                id=receipt.id,
                user_id=receipt.user_id,
                transaction_id=receipt.transaction_id,
                object_key=receipt.object_key,
                content_type=receipt.content_type,
                size_bytes=receipt.size_bytes,
                created_at=receipt.created_at,
            )
        )

    async def attach_receipt(
        self, user_id: UserId, receipt_id: UUID, transaction_id: UUID, *, stashed_after: datetime
    ) -> bool:
        """Claim an unclaimed receipt stored after ``stashed_after`` (older ones are
        about to be purged). False if there is none to claim."""
        result = await self._db.execute(
            update(receipts)
            .where(
                receipts.c.user_id == user_id,
                receipts.c.id == receipt_id,
                receipts.c.transaction_id.is_(None),
                receipts.c.created_at > stashed_after,
            )
            .values(transaction_id=transaction_id)
        )
        return bool(result.rowcount)

    async def live_receipt(self, user_id: UserId, transaction_id: UUID) -> Receipt | None:
        """The receipt of a transaction that isn't deleted."""
        row = (
            await self._db.execute(
                select(receipts)
                .join(
                    transactions,
                    and_(
                        transactions.c.id == receipts.c.transaction_id,
                        transactions.c.user_id == receipts.c.user_id,
                    ),
                )
                .where(
                    receipts.c.user_id == user_id,
                    receipts.c.transaction_id == transaction_id,
                    transactions.c.deleted_at.is_(None),
                )
            )
        ).first()
        return _receipt(row) if row else None

    async def transactions_with_receipts(
        self, user_id: UserId, transaction_ids: list[UUID]
    ) -> set[UUID]:
        if not transaction_ids:
            return set()
        rows = await self._db.execute(
            select(receipts.c.transaction_id).where(
                receipts.c.user_id == user_id, receipts.c.transaction_id.in_(transaction_ids)
            )
        )
        return {row[0] for row in rows}

    async def receipts_to_purge(self, now: datetime, limit: int) -> list[Receipt]:
        """Across all users: receipts due to be erased (see nexus.domain.receipts)."""
        t = transactions.c
        rows = await self._db.execute(
            select(receipts, t.deleted_at.label("tx_deleted_at"))
            .outerjoin(
                transactions,
                and_(t.id == receipts.c.transaction_id, t.user_id == receipts.c.user_id),
            )
            .where(
                or_(
                    and_(
                        receipts.c.transaction_id.is_(None),
                        receipts.c.created_at <= now - UNCLAIMED_TTL,
                    ),
                    t.deleted_at <= now - RETENTION_AFTER_DELETE,
                )
            )
            .order_by(receipts.c.created_at)
            .limit(limit)
        )
        found = [(_receipt(row), row.tx_deleted_at) for row in rows]
        return [r for r, deleted_at in found if purge_due(r, deleted_at, now)]

    async def delete_receipt(self, user_id: UserId, receipt_id: UUID) -> None:
        await self._db.execute(
            delete(receipts).where(receipts.c.user_id == user_id, receipts.c.id == receipt_id)
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

    async def outgoing_since(
        self, user_id: UserId, start: datetime, *, limit: int
    ) -> list[Transaction]:
        t = transactions.c
        rows = await self._db.execute(
            select(transactions)
            .where(
                t.user_id == user_id,
                t.deleted_at.is_(None),
                t.direction == Direction.OUT.value,
                t.counterparty.is_not(None),
                t.occurred_at >= start,
            )
            .order_by(t.occurred_at.desc())
            .limit(limit)
        )
        return [_transaction(r) for r in rows]

    async def logged_between(
        self, user_id: UserId, start: datetime, end: datetime, *, limit: int
    ) -> list[Transaction]:
        t = transactions.c
        rows = await self._db.execute(
            select(transactions)
            .where(
                t.user_id == user_id,
                t.deleted_at.is_(None),
                t.created_at >= start,
                t.created_at < end,
            )
            .order_by(t.created_at)
            .limit(limit)
        )
        return [_transaction(r) for r in rows]

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
        self, user_id: UserId, start: datetime, end: datetime, *, net: bool = True
    ) -> list[DirectionTotal]:
        t = transactions.c
        amount = _net_amount() if net else t.amount
        rows = await self._db.execute(
            select(t.direction, t.currency, func.sum(amount), func.count())
            .where(self._counted(user_id, start, end), *([amount != 0] if net else []))
            .group_by(t.direction, t.currency)
            .order_by(t.direction, t.currency)
        )
        return [
            DirectionTotal(Direction(direction), Money(total, currency), count)
            for direction, currency, total, count in rows
        ]

    async def totals_by_day(
        self, user_id: UserId, start: datetime, end: datetime, timezone: str, *, net: bool = True
    ) -> list[DayTotal]:
        t = transactions.c
        amount = _net_amount() if net else t.amount
        day = cast(func.timezone(timezone, t.occurred_at), Date)
        rows = await self._db.execute(
            select(
                t.direction,
                t.category_id,
                categories.c.name,
                day,
                t.currency,
                func.sum(amount),
                func.count(),
            )
            .select_from(
                transactions.outerjoin(
                    categories,
                    and_(categories.c.id == t.category_id, categories.c.user_id == t.user_id),
                )
            )
            .where(self._counted(user_id, start, end), *([amount != 0] if net else []))
            .group_by(t.direction, t.category_id, categories.c.name, day, t.currency)
            .order_by(day)
        )
        return [
            DayTotal(Direction(direction), category_id, name, on, Money(total, currency), count)
            for direction, category_id, name, on, currency, total, count in rows
        ]

    async def spending_by_category(
        self, user_id: UserId, start: datetime, end: datetime, *, net: bool = True
    ) -> list[CategoryTotal]:
        t = transactions.c
        amount = _net_amount() if net else t.amount
        total = func.sum(amount)
        rows = await self._db.execute(
            select(t.category_id, categories.c.name, t.currency, total, func.count())
            .select_from(
                transactions.outerjoin(
                    categories,
                    and_(categories.c.id == t.category_id, categories.c.user_id == t.user_id),
                )
            )
            .where(
                self._counted(user_id, start, end),
                t.direction == Direction.OUT.value,
                *([amount != 0] if net else []),
            )
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

    async def lineage(self, user_id: UserId, transaction_ids: list[UUID]) -> dict[UUID, Lineage]:
        if not transaction_ids:
            return {}
        sp, st = splits.c, settlements.c
        bill, income = transactions.alias("bill"), transactions.alias("income")
        t = transactions.c
        share_rows = await self._db.execute(
            select(splits, t.currency)
            .join(transactions, and_(t.id == sp.transaction_id, t.user_id == sp.user_id))
            .where(sp.user_id == user_id, sp.transaction_id.in_(transaction_ids))
            .order_by(sp.created_at, sp.participant_name)
        )
        link_rows = await self._db.execute(
            select(
                bill.c.id,
                bill.c.counterparty,
                bill.c.occurred_at,
                income.c.id,
                income.c.occurred_at,
                sp.participant_name,
                st.amount,
                bill.c.currency,
            )
            .select_from(
                settlements.join(splits, and_(sp.id == st.split_id, sp.user_id == st.user_id))
                .join(bill, and_(bill.c.id == sp.transaction_id, bill.c.user_id == sp.user_id))
                .join(
                    income,
                    and_(income.c.id == st.income_transaction_id, income.c.user_id == st.user_id),
                )
            )
            .where(
                st.user_id == user_id,
                bill.c.deleted_at.is_(None),
                income.c.deleted_at.is_(None),
                or_(bill.c.id.in_(transaction_ids), income.c.id.in_(transaction_ids)),
            )
            .order_by(income.c.occurred_at)
        )
        found: dict[UUID, Lineage] = {}

        def entry(tx_id: UUID) -> Lineage:
            return found.setdefault(tx_id, Lineage([], []))

        for r in share_rows:
            entry(r.transaction_id).shares.append(
                Split(
                    r.id,
                    UserId(r.user_id),
                    r.transaction_id,
                    r.participant_name,
                    Money(r.share_amount, r.currency),
                )
            )
        wanted = set(transaction_ids)
        for b_id, b_who, b_at, i_id, i_at, name, amount, currency in link_rows:
            link = Link(b_id, b_who, b_at, i_id, i_at, name, Money(amount, currency))
            for tx_id in {b_id, i_id} & wanted:
                entry(tx_id).links.append(link)
        return found

    async def dismissed_pairs(self, user_id: UserId, ids: list[UUID]) -> set[tuple[str, str]]:
        if not ids:
            return set()
        d = duplicate_dismissals.c
        rows = await self._db.execute(
            select(d.first_id, d.second_id).where(
                d.user_id == user_id, or_(d.first_id.in_(ids), d.second_id.in_(ids))
            )
        )
        return {(str(r.first_id), str(r.second_id)) for r in rows}

    async def dismiss_pair(self, user_id: UserId, pair: tuple[str, str], at: datetime) -> None:
        await self._db.execute(
            pg_insert(duplicate_dismissals)
            .values(user_id=user_id, first_id=UUID(pair[0]), second_id=UUID(pair[1]), created_at=at)
            .on_conflict_do_nothing()
        )

    async def has_settlements_for_income(self, user_id: UserId, income_id: UUID) -> bool:
        stmt = select(
            exists().where(
                settlements.c.user_id == user_id,
                settlements.c.income_transaction_id == income_id,
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

    # --- web access -------------------------------------------------------------------

    async def grant_web_access(self, user_id: UserId, at: datetime) -> None:
        await self._db.execute(
            update(users)
            .where(users.c.id == user_id, users.c.web_access_granted_at.is_(None))
            .values(web_access_granted_at=at)
        )

    async def insert_invite(self, invite: Invite) -> None:
        await self._db.execute(
            insert(invites).values(
                id=invite.id,
                token_hash=invite.token_hash,
                created_by=invite.created_by,
                created_at=invite.created_at,
                expires_at=invite.expires_at,
            )
        )

    async def get_invite(self, token_hash: str, *, for_update: bool = False) -> Invite | None:
        stmt = select(invites).where(invites.c.token_hash == token_hash)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return Invite(
            id=row.id,
            token_hash=row.token_hash,
            created_by=UserId(row.created_by),
            created_at=row.created_at,
            expires_at=row.expires_at,
            redeemed_at=row.redeemed_at,
            redeemed_by=UserId(row.redeemed_by) if row.redeemed_by else None,
        )

    async def redeem_invite(self, invite_id: UUID, user_id: UserId, at: datetime) -> None:
        await self._db.execute(
            update(invites)
            .where(invites.c.id == invite_id, invites.c.redeemed_at.is_(None))
            .values(redeemed_at=at, redeemed_by=user_id)
        )

    async def insert_session(self, session: Session) -> None:
        await self._db.execute(
            insert(web_sessions).values(
                token_hash=session.token_hash,
                user_id=session.user_id,
                csrf_token=session.csrf_token,
                created_at=session.created_at,
                expires_at=session.expires_at,
            )
        )

    async def get_session(self, token_hash: str) -> Session | None:
        row = (
            await self._db.execute(
                select(web_sessions).where(web_sessions.c.token_hash == token_hash)
            )
        ).first()
        if row is None:
            return None
        return Session(
            token_hash=row.token_hash,
            user_id=UserId(row.user_id),
            csrf_token=row.csrf_token,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )

    async def revoke_session(self, token_hash: str, at: datetime) -> None:
        await self._db.execute(
            update(web_sessions)
            .where(web_sessions.c.token_hash == token_hash, web_sessions.c.revoked_at.is_(None))
            .values(revoked_at=at)
        )
