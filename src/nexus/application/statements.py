"""Importing a bank statement: preview what would be added, then add only the rows
the user ticked, all at once, and allow undoing the whole import.

Nothing is saved by a preview. Each row gets a fingerprint, claimed as its source
id when imported, so the same file can't be imported twice. Money in from a
statement is filed as income, never as salary: payday and the usual salary are
the user's to set.
"""

import csv
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.ports import LedgerQuery, LedgerRepository, UnitOfWork
from nexus.application.transactions import NewTransaction, create_transaction, default_category
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import (
    Direction,
    RevisionKind,
    Source,
    Transaction,
    TransactionStatus,
    User,
    UserId,
    clean_name,
    snapshot,
)
from nexus.domain.money import Money
from nexus.domain.rules import best_rule
from nexus.domain.statement_pdf import Kind, read_statement_lines
from nexus.domain.statements import (
    DateOrder,
    Mapping,
    RowStatus,
    SavedMapping,
    StatementImport,
    StatementRow,
    Table,
    fingerprints,
    mapping_to_json,
    read_rows,
    read_table,
    suggest_mapping,
)

type UowFactory = Callable[[], UnitOfWork]

DUPLICATE_DAYS = 1  # a logged transaction this close, same amount and direction


class Verdict(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"  # looks like one already in the ledger
    IMPORTED = "imported"  # this very row came in with an earlier import
    UNCLEAR = "unclear"  # the date or amount couldn't be read


@dataclass(frozen=True, slots=True)
class PreviewRow:
    row: StatementRow
    verdict: Verdict
    money: Money | None = None
    category: str | None = None  # where it would be filed
    matches: Transaction | None = None  # the likely duplicate


@dataclass(frozen=True, slots=True)
class Preview:
    table: Table
    mapping: Mapping | None  # None: the columns couldn't be guessed; the user picks
    saved_as: str | None  # the name of the saved layout used, if any
    rows: list[PreviewRow]


@dataclass(frozen=True, slots=True)
class Imported:
    record: StatementImport
    skipped: int  # ticked rows left out: unreadable or already imported


def _local_noon(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(12), tzinfo=tz)


async def _layout(
    repo: UnitOfWork, user: User, table: Table, chosen: Mapping | None
) -> tuple[Mapping | None, str | None]:
    if chosen is not None:
        return chosen, None
    saved = await repo.statements.mapping_for(user.id, table.header_key)
    if saved is not None and _fits(saved.mapping, table):
        return saved.mapping, saved.name
    return suggest_mapping(table), None


def _fits(mapping: Mapping, table: Table) -> bool:
    try:
        mapping.check(len(table.headers))
    except InvalidInput:
        return False
    return True


async def _category_names(repo: LedgerRepository, user: User) -> Callable[[StatementRow], str]:
    cats = {c.id: c.name for c in await repo.list_categories(user.id, include_inactive=False)}
    rules = [r for r in await repo.list_category_rules(user.id) if r.category_id in cats]
    defaults = {
        d: cats.get(await default_category(repo, user.id, d) or UUID(int=0), "") for d in Direction
    }

    def name(row: StatementRow) -> str:
        if row.direction is Direction.OUT:
            rule = best_rule(rules, row.description, None)
            if rule is not None:
                return cats[rule.category_id]
        return defaults[row.direction or Direction.OUT]

    return name


def _duplicates(
    rows: Iterable[tuple[StatementRow, Money]], existing: list[Transaction], tz: ZoneInfo
) -> dict[int, Transaction]:
    """Pair each row with at most one live transaction of the same amount and
    direction within a day, and each transaction with at most one row."""
    free = list(existing)
    found: dict[int, Transaction] = {}
    for row, money in rows:
        if row.day is None:
            continue
        for tx in free:
            near = abs((tx.occurred_at.astimezone(tz).date() - row.day).days) <= DUPLICATE_DAYS
            if near and tx.direction is row.direction and tx.amount == money:
                found[row.index] = tx
                free.remove(tx)
                break
    return found


async def preview(
    uow_factory: UowFactory, user: User, text: str, mapping: Mapping | None = None
) -> Preview:
    table = read_table(text)
    tz = ZoneInfo(user.timezone)
    async with uow_factory() as db:
        chosen, saved_as = await _layout(db, user, table, mapping)
        if chosen is None:
            return Preview(table, None, None, [])
        rows = read_rows(table, chosen)
        prints = fingerprints(rows)
        imported = await db.statements.claimed(user.id, Source.IMPORT, list(prints.values()))
        category = await _category_names(db.ledger, user)
        readable = [r for r in rows if r.status is RowStatus.READY and r.day is not None]
        existing: list[Transaction] = []
        if readable:
            first = min(r.day for r in readable if r.day) - timedelta(days=DUPLICATE_DAYS + 1)
            last = max(r.day for r in readable if r.day) + timedelta(days=DUPLICATE_DAYS + 2)
            page = await db.ledger.list_transactions(
                user.id,
                LedgerQuery(start=_local_noon(first, tz), end=_local_noon(last, tz), limit=10_000),
            )
            existing = page.items
    money = {r.index: _money(r, user) for r in readable}
    fresh = [(r, money[r.index]) for r in readable if prints[r.index] not in imported]
    doubles = _duplicates(fresh, existing, tz)
    result: list[PreviewRow] = []
    for row in rows:
        if row.status is not RowStatus.READY:
            result.append(PreviewRow(row, Verdict.UNCLEAR))
        elif prints[row.index] in imported:
            result.append(PreviewRow(row, Verdict.IMPORTED, money[row.index], category(row)))
        elif row.index in doubles:
            result.append(
                PreviewRow(
                    row, Verdict.DUPLICATE, money[row.index], category(row), doubles[row.index]
                )
            )
        else:
            result.append(PreviewRow(row, Verdict.NEW, money[row.index], category(row)))
    return Preview(table, chosen, saved_as, result)


def _money(row: StatementRow, user: User) -> Money:
    if row.amount is None:  # pragma: no cover - only readable rows get here
        raise InvalidInput("the row has no amount")
    return Money.of(row.amount, row.currency or user.home_currency)


async def confirm(
    uow_factory: UowFactory,
    user: User,
    text: str,
    mapping: Mapping,
    include: set[int],
    *,
    file_name: str,
    save_as: str | None = None,
    now: datetime,
) -> Imported:
    """Add the ticked rows as one import. Rows that can't be read, or that an
    earlier import already added, are skipped rather than failing the rest."""
    table = read_table(text)
    rows = read_rows(table, mapping)
    if not include:
        raise InvalidInput("tick at least one row to import")
    if not include <= {r.index for r in rows}:
        raise InvalidInput("a ticked row isn't in the file")
    prints = fingerprints(rows)
    tz = ZoneInfo(user.timezone)
    name = clean_name(file_name, field_name="file name")[:120]
    added: list[UUID] = []
    skipped = 0
    async with uow_factory() as db:
        claimed = await db.statements.claimed(user.id, Source.IMPORT, list(prints.values()))
        for row in rows:
            if row.index not in include:
                continue
            fingerprint = prints.get(row.index)
            if row.day is None or row.direction is None or fingerprint is None:
                skipped += 1
                continue
            if fingerprint in claimed:
                skipped += 1
                continue
            tx = await create_transaction(
                db.ledger,
                user.id,
                NewTransaction(
                    direction=row.direction,
                    amount=_money(row, user),
                    occurred_at=_local_noon(row.day, tz),
                    counterparty=row.description or None,
                    source=Source.IMPORT,
                    status=TransactionStatus.CONFIRMED,
                    external_id=fingerprint,
                ),
                now=now,
            )
            claimed.add(fingerprint)
            added.append(tx.id)
        record = StatementImport(uuid4(), user.id, name, added, now)
        if added:
            await db.statements.insert_import(record)
        if save_as is not None:
            await db.statements.save_mapping(
                SavedMapping(
                    uuid4(), user.id, clean_name(save_as, field_name="name")[:60],
                    table.header_key, mapping, now,
                ),
                mapping_to_json(mapping),
            )  # fmt: skip
        await db.commit()
    return Imported(record, skipped)


async def undo_import(uow: UnitOfWork, actor: UserId, import_id: UUID, *, now: datetime) -> int:
    """Delete (restorably) every transaction the import added that's still there."""
    async with uow:
        record = await uow.statements.get_import(actor, import_id, for_update=True)
        if record is None:
            raise NotFound("no such import")
        if record.undone_at is not None:
            raise InvalidInput("that import was already undone")
        removed = 0
        for tx_id in record.transaction_ids:
            tx = await uow.ledger.get_transaction(actor, tx_id, for_update=True)
            if tx is None or tx.is_deleted:
                continue
            await uow.ledger.update_transaction(replace(tx, deleted_at=now, updated_at=now))
            await uow.ledger.insert_revision(actor, tx.id, RevisionKind.DELETE, snapshot(tx), now)
            removed += 1
        await uow.statements.mark_undone(actor, import_id, now)
        await uow.commit()
    return removed


async def list_imports(uow: UnitOfWork, actor: UserId) -> list[StatementImport]:
    async with uow:
        return await uow.statements.list_imports(actor)


async def list_layouts(uow: UnitOfWork, actor: UserId) -> list[SavedMapping]:
    async with uow:
        return await uow.statements.list_mappings(actor)


async def forget_layout(uow: UnitOfWork, actor: UserId, mapping_id: UUID) -> None:
    async with uow:
        if not await uow.statements.delete_mapping(actor, mapping_id):
            raise NotFound("no such saved layout")
        await uow.commit()


# --- PDF statements -------------------------------------------------------------------------

PDF_LAYOUT = Mapping(date=0, description=(1,), amount=2, date_order=DateOrder.YMD)


@dataclass(frozen=True, slots=True)
class PdfRead:
    """A PDF statement's transactions as CSV, for the same preview and import."""

    csv: str
    kind: Kind
    statement_date: date | None
    rows: int
    reconciles: bool | None  # the rows add up to the statement's own totals


def read_pdf(lines: list[str]) -> PdfRead:
    """From the PDF's text lines; InvalidInput when it has no readable transactions
    (a scan, or a layout this reader doesn't know)."""
    found = read_statement_lines(lines)
    if not found.rows:
        raise InvalidInput(
            "couldn't find any transactions in that PDF. If it's a scan, your bank's CSV "
            "export will work instead"
        )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Description", "Amount"])
    for row in found.rows:
        writer.writerow([row.day.isoformat(), row.description, str(row.amount)])
    return PdfRead(
        out.getvalue(), found.kind, found.statement_date, len(found.rows), found.reconciles
    )
