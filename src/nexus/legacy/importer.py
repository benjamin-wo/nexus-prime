"""Map a legacy snapshot into the new schema, one user per transaction.

Every imported row is claimed as ``import`` / ``legacy-<kind>:<old id>``, so a
second run skips what's already there. Dry-run (the default) does all the work
and checks, then rolls back. Imports record no undo revisions: "undo" never
reaches back into history.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexus.application.users import DEFAULT_CATEGORIES
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Category,
    Direction,
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
from nexus.infra.db.ledger_repository import SqlLedgerRepository
from nexus.infra.db.tables import transaction_sources, transactions
from nexus.legacy.reader import LegacyExpense, LegacyIncome, LegacySnapshot, LegacyUser

_FOUR_DP = Decimal("0.0001")
_TOLERANCE = Decimal("0.01")
_GENERIC_SOURCES = {"", "employer", "friend", "insurer", "other", "unknown"}

type TotalKey = tuple[str, str]  # (direction, currency)


@dataclass
class UserReport:
    telegram_user_id: int
    new_user: bool = False
    expenses: int = 0
    incomes: int = 0
    already_imported: int = 0
    splits: int = 0
    settlements: int = 0
    assumed_repayments: int = 0
    tombstones: int = 0
    rounded: int = 0
    currency_assumed: int = 0
    skipped: list[str] = field(default_factory=list)
    expected: dict[TotalKey, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    expected_count: int = 0
    actual: dict[TotalKey, Decimal] = field(default_factory=dict)
    actual_count: int = 0

    @property
    def matches(self) -> bool:
        keys = set(self.expected) | set(self.actual)
        return self.expected_count == self.actual_count and all(
            abs(self.expected.get(k, Decimal(0)) - self.actual.get(k, Decimal(0))) < _TOLERANCE
            for k in keys
        )


@dataclass
class ImportReport:
    applied: bool
    users: list[UserReport] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(u.matches for u in self.users)

    def render(self) -> str:
        mode = "APPLIED" if self.applied else "DRY RUN (nothing written)"
        lines = [f"Legacy import: {mode}"]
        for u in self.users:
            status = "MATCH" if u.matches else "MISMATCH"
            lines.append(
                f"\nUser {u.telegram_user_id}{' (new)' if u.new_user else ''}: {status}"
                f"\n  expenses {u.expenses}, income {u.incomes}, already imported "
                f"{u.already_imported}\n  splits {u.splits}, settlements {u.settlements} "
                f"(of which assumed repayments {u.assumed_repayments}), "
                f"deleted-email tombstones {u.tombstones}"
                f"\n  amounts rounded to 4 dp: {u.rounded}; currency assumed: {u.currency_assumed}"
                f"\n  rows: old {u.expected_count} / new {u.actual_count}"
            )
            for key in sorted(set(u.expected) | set(u.actual)):
                old = u.expected.get(key, Decimal(0))
                new = u.actual.get(key, Decimal(0))
                lines.append(f"  money {key[0]} {key[1]}: old {old:.4f} / new {new:.4f}")
            lines += [f"  skipped: {reason}" for reason in u.skipped]
        lines += [f"\nNot imported: {o}" for o in self.orphans]
        lines.append(f"\nResult: {'OK' if self.ok else 'TOTALS DO NOT MATCH'}")
        return "\n".join(lines)


def _decimal(value: float, report: UserReport) -> Decimal:
    exact = Decimal(repr(value))
    rounded = exact.quantize(_FOUR_DP, rounding=ROUND_HALF_EVEN)
    if rounded != exact:
        report.rounded += 1
    return rounded


def _money(value: float, currency: str | None, home: str, report: UserReport) -> Money:
    amount = _decimal(value, report)
    code = (currency or "").strip().upper()
    try:
        return Money(amount, code)
    except InvalidInput:
        report.currency_assumed += 1
        return Money(amount, home)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _text(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned[:limit] or None


class _UserImport:
    def __init__(
        self,
        conn: AsyncConnection,
        legacy: LegacyUser,
        report: UserReport,
        *,
        owner_telegram_id: int | None,
        default_currency: str,
        default_timezone: str,
    ) -> None:
        self.conn = conn
        self.repo = SqlLedgerRepository(conn)
        self.legacy = legacy
        self.report = report
        self.owner = owner_telegram_id
        self.default_currency = default_currency
        self.default_timezone = default_timezone
        self.user: User
        self.categories: dict[str, UUID] = {}
        self.expense_ids: dict[int, Transaction] = {}  # old id -> new tx (this run)
        self.repayments: dict[str, tuple[Transaction, Decimal]] = {}

    async def _ensure_user(self) -> None:
        tz = self.legacy.timezone or self.default_timezone
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            tz = self.default_timezone
        try:
            currency = Money.zero((self.legacy.home_currency or "").strip().upper()).currency
        except InvalidInput:
            currency = self.default_currency
        candidate = User(
            id=UserId(uuid4()),
            telegram_user_id=self.legacy.telegram_user_id,
            telegram_chat_id=self.legacy.telegram_chat_id,
            timezone=tz,
            home_currency=currency,
            role=Role.OWNER if self.legacy.telegram_user_id == self.owner else Role.MEMBER,
            created_at=datetime.now(UTC),
        )
        self.report.new_user = await self.repo.insert_user_if_absent(candidate)
        user = await self.repo.get_user_by_telegram_id(self.legacy.telegram_user_id)
        if user is None:  # pragma: no cover - just inserted or already present
            raise RuntimeError("user vanished during import")
        self.user = user
        existing = await self.repo.list_categories(user.id, include_inactive=True)
        self.categories = {c.name.casefold(): c.id for c in existing}
        if self.report.new_user and not existing:
            for name in DEFAULT_CATEGORIES:
                await self._category(name)

    async def _category(self, name: str | None) -> UUID | None:
        cleaned = _text(name, 100)
        if cleaned is None:
            return None
        key = cleaned.casefold()
        if key not in self.categories:
            category = Category(uuid4(), self.user.id, cleaned, True)
            await self.repo.insert_category(category)
            self.categories[key] = category.id
        return self.categories[key]

    async def _claimed(self, key: str) -> bool:
        return await self.repo.source_claimed(self.user.id, Source.IMPORT, key)

    async def _insert(self, tx: Transaction, key: str) -> None:
        await self.repo.insert_transaction(tx)
        await self.repo.claim_source(self.user.id, Source.IMPORT, key, tx.id)

    def _new_tx(
        self,
        direction: Direction,
        money: Money,
        occurred_at: datetime,
        *,
        counterparty: str | None,
        category_id: UUID | None,
        notes: str | None,
        status: TransactionStatus = TransactionStatus.CONFIRMED,
    ) -> Transaction:
        now = datetime.now(UTC)
        return Transaction(
            id=uuid4(),
            user_id=self.user.id,
            direction=direction,
            amount=money,
            occurred_at=_aware(occurred_at),
            counterparty=counterparty,
            category_id=category_id,
            notes=notes,
            status=status,
            source=Source.IMPORT,
            created_at=now,
            updated_at=now,
        )

    async def expense(self, old: LegacyExpense) -> None:
        money = _money(old.amount, old.currency, self.user.home_currency, self.report)
        if not money.is_positive:
            self.report.skipped.append(f"expense {old.id}: amount {old.amount} is not positive")
            return
        self._expect(Direction.OUT, money)
        key = f"legacy-expense:{old.id}"
        if await self._claimed(key):
            self.report.already_imported += 1
            return
        tx = self._new_tx(
            Direction.OUT,
            money,
            old.occurred_at,
            counterparty=_text(old.merchant),
            category_id=await self._category(old.category),
            notes=_text(old.notes),
            status=TransactionStatus.CONFIRMED if old.verified else TransactionStatus.PENDING,
        )
        await self._insert(tx, key)
        message_id = _text(old.source_message_id)
        if message_id and not message_id.startswith("iou:"):
            if not await self.repo.source_claimed(self.user.id, Source.EMAIL, message_id):
                await self.repo.claim_source(self.user.id, Source.EMAIL, message_id, tx.id)
        self.expense_ids[old.id] = tx
        self.report.expenses += 1

    async def income(self, old: LegacyIncome) -> None:
        money = _money(old.amount, old.currency, self.user.home_currency, self.report)
        if not money.is_positive:
            self.report.skipped.append(f"income {old.id}: amount {old.amount} is not positive")
            return
        self._expect(Direction.IN, money)
        key = f"legacy-income:{old.id}"
        if await self._claimed(key):
            self.report.already_imported += 1
            return
        source = _text(old.source, 200)
        counterparty = None if (source or "").casefold() in _GENERIC_SOURCES else source
        category = "Income" if (old.category or "").casefold() == "salary" else None
        notes = _text(old.notes) or _text(old.category)
        tx = self._new_tx(
            Direction.IN,
            money,
            old.occurred_at,
            counterparty=counterparty,
            category_id=await self._category(category),
            notes=notes,
        )
        await self._insert(tx, key)
        message_id = _text(old.source_message_id)
        if message_id and message_id.startswith("iou:"):
            self.repayments[message_id.casefold()] = (tx, money.amount)
        self.report.incomes += 1

    def _expect(self, direction: Direction, money: Money) -> None:
        """Every importable old row counts, whether imported now or on an earlier run."""
        self.report.expected[(direction.value, money.currency)] += money.amount
        self.report.expected_count += 1

    async def splits(self, old: LegacyExpense, tasks: list[tuple[str, float | None, bool]]) -> None:
        tx = self.expense_ids.get(old.id)
        if tx is None:
            return
        data = old.split_data
        shares: dict[str, Any] = dict(data.get("share_amounts") or data.get("custom_amounts") or {})
        paid_amounts: dict[str, Any] = dict(data.get("paid_amounts") or {})
        paid_status: dict[str, Any] = dict(data.get("paid_status") or {})
        for friend, amount, done in tasks:
            if friend not in shares and amount:
                shares[friend] = amount
            if done:
                paid_status.setdefault(friend, True)
        shares.pop("Me", None)

        new_splits: list[Split] = []
        paid: dict[str, Decimal] = {}
        seen: set[str] = set()
        for friend, raw in shares.items():
            name = _text(friend, 100)
            if name is None or name.casefold() in seen:
                continue
            try:
                share = Money(_decimal(float(raw), self.report), tx.amount.currency)
            except (TypeError, ValueError, InvalidInput):
                self.report.skipped.append(f"split on expense {old.id} for {friend}: bad share")
                continue
            if not share.is_positive:
                continue
            seen.add(name.casefold())
            new_splits.append(Split(uuid4(), self.user.id, tx.id, name, share))
            recorded = paid_amounts.get(friend)
            amount_paid = (
                _decimal(float(recorded), self.report) if recorded not in (None, "") else Decimal(0)
            )
            if paid_status.get(friend) is True and amount_paid < share.amount:
                amount_paid = share.amount
            paid[name] = min(amount_paid, share.amount)
        owed = sum((s.share.amount for s in new_splits), Decimal(0))
        if owed > tx.amount.amount:
            self.report.skipped.append(
                f"splits on expense {old.id}: shares {owed} exceed the bill {tx.amount.amount}"
            )
            return
        if not new_splits:
            return
        await self.repo.replace_splits(self.user.id, tx.id, new_splits)
        self.report.splits += len(new_splits)
        for split in new_splits:
            if paid[split.participant_name] > 0:
                await self._settle(old.id, split, paid[split.participant_name])

    async def _settle(self, expense_id: int, split: Split, amount: Decimal) -> None:
        key = f"iou:{expense_id}:{split.participant_name.casefold()}"
        match = self.repayments.get(key)
        if match is not None:
            income, available = match
            settled = min(amount, available)
            income_id = income.id
        else:
            # Paid in the old app with no repayment row: record it so the IOU
            # doesn't reopen, and say so in the report.
            income = self._new_tx(
                Direction.IN,
                Money(amount, split.share.currency),
                datetime.now(UTC),
                counterparty=split.participant_name,
                category_id=None,
                notes="Repayment recorded before the rebuild",
            )
            await self._insert(income, f"legacy-repayment:{expense_id}:{split.participant_name}")
            self.report.assumed_repayments += 1
            settled, income_id = amount, income.id
        await self.repo.insert_settlements(
            [
                Settlement(
                    uuid4(), self.user.id, split.id, income_id, Money(settled, split.share.currency)
                )
            ]
        )
        self.report.settlements += 1

    async def tombstones(self, message_ids: list[str]) -> None:
        for message_id in message_ids:
            cleaned = _text(message_id)
            if cleaned and not await self.repo.source_claimed(self.user.id, Source.EMAIL, cleaned):
                await self.repo.claim_source(self.user.id, Source.EMAIL, cleaned, None)
                self.report.tombstones += 1

    async def verify(self) -> None:
        """Totals of everything imported for this user, from the database itself."""
        t, s = transactions.c, transaction_sources.c
        rows = await self.conn.execute(
            select(t.direction, t.currency, func.sum(t.amount), func.count())
            .select_from(
                transactions.join(
                    transaction_sources, and_(s.transaction_id == t.id, s.user_id == t.user_id)
                )
            )
            .where(
                t.user_id == self.user.id,
                s.source == Source.IMPORT.value,
                s.external_id.like("legacy-expense:%") | s.external_id.like("legacy-income:%"),
            )
            .group_by(t.direction, t.currency)
        )
        for direction, currency, total, count in rows:
            self.report.actual[(direction, currency)] = total
            self.report.actual_count += count


async def import_legacy(
    engine: AsyncEngine,
    snapshot: LegacySnapshot,
    *,
    apply: bool,
    owner_telegram_id: int | None,
    default_currency: str = "SGD",
    default_timezone: str = "Asia/Singapore",
) -> ImportReport:
    report = ImportReport(applied=apply)
    known = {u.telegram_user_id for u in snapshot.users}
    for kind, rows in (("expense", snapshot.expenses), ("income", snapshot.incomes)):
        report.orphans += [
            f"{kind} {r.id}: unknown user {r.user_id}" for r in rows if r.user_id not in known
        ]

    for legacy in sorted(snapshot.users, key=lambda u: u.telegram_user_id):
        user_report = UserReport(legacy.telegram_user_id)
        report.users.append(user_report)
        async with engine.connect() as conn:
            transaction = await conn.begin()
            job = _UserImport(
                conn,
                legacy,
                user_report,
                owner_telegram_id=owner_telegram_id,
                default_currency=default_currency,
                default_timezone=default_timezone,
            )
            await job._ensure_user()
            mine = legacy.telegram_user_id
            expenses = sorted(
                (e for e in snapshot.expenses if e.user_id == mine), key=lambda e: e.id
            )
            for income in sorted(
                (i for i in snapshot.incomes if i.user_id == mine), key=lambda i: i.id
            ):
                await job.income(income)
            for expense in expenses:
                await job.expense(expense)
            tasks: dict[int, list[tuple[str, float | None, bool]]] = defaultdict(list)
            for task in snapshot.iou_tasks:
                if task.user_id == mine:
                    tasks[task.expense_id].append((task.friend, task.amount, task.done))
            for expense in expenses:
                await job.splits(expense, tasks.get(expense.id, []))
            await job.tombstones([m for uid, m in snapshot.tombstones if uid == mine])
            await job.verify()
            if apply and user_report.matches:
                await transaction.commit()
            else:
                await transaction.rollback()
    return report
