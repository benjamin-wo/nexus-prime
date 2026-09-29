from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from nexus.application import fx
from nexus.application.categories import require_category
from nexus.application.clock import utcnow
from nexus.application.fx import RateSource
from nexus.application.ports import (
    CategoryTotal,
    DirectionTotal,
    LedgerQuery,
    LedgerRepository,
    Page,
    UnitOfWork,
)
from nexus.domain.errors import Conflict, InvalidInput, NotFound, NothingToUndo
from nexus.domain.ledger import (
    Direction,
    RevisionKind,
    Source,
    Split,
    Transaction,
    TransactionStatus,
    User,
    UserId,
    apply_snapshot,
    clean_name,
    clean_text,
    require_aware,
    require_positive,
    snapshot,
)
from nexus.domain.money import Money
from nexus.domain.rules import CategoryRule, best_rule

MAX_PAGE = 500


class _Unset(Enum):
    UNSET = "unset"


UNSET = _Unset.UNSET
type Maybe[T] = T | Literal[_Unset.UNSET]


@dataclass(frozen=True, slots=True)
class NewTransaction:
    direction: Direction
    amount: Money
    occurred_at: datetime
    counterparty: str | None = None
    category_id: UUID | None = None
    notes: str | None = None
    status: TransactionStatus = TransactionStatus.CONFIRMED
    source: Source = Source.MANUAL
    # Set for anything ingested from outside (an email, a statement row).
    external_id: str | None = None
    # With no category given, file an expense by the user's category rules.
    apply_rules: bool = True
    # A best guess (e.g. the model's) used only when no category was given and no
    # rule matched. Failing that, expenses go to "Other" and income to "Income".
    fallback_category_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class TransactionChanges:
    """Fields to change. Leave a field UNSET to keep it; None clears it."""

    direction: Maybe[Direction] = UNSET
    amount: Maybe[Money] = UNSET
    occurred_at: Maybe[datetime] = UNSET
    counterparty: Maybe[str | None] = UNSET
    category_id: Maybe[UUID | None] = UNSET
    notes: Maybe[str | None] = UNSET
    status: Maybe[TransactionStatus] = UNSET


@dataclass(frozen=True, slots=True)
class UndoResult:
    undone: RevisionKind
    transaction: Transaction


@dataclass(frozen=True, slots=True)
class Summary:
    start: datetime
    end: datetime
    totals: list[DirectionTotal]
    spending_by_category: list[CategoryTotal]


async def create_transaction(
    repo: LedgerRepository, actor: UserId, cmd: NewTransaction, *, now: datetime
) -> Transaction:
    """Validate and store a new transaction with its source claim and revision.

    Shared by the use cases that create money movements; runs inside the
    caller's unit of work.
    """
    category_id, rule_id = cmd.category_id, None
    if category_id is not None:
        await require_category(repo, actor, category_id)
    elif Direction(cmd.direction) is Direction.OUT and cmd.apply_rules:
        rule = await matching_rule(repo, actor, cmd.counterparty, cmd.notes)
        if rule is not None:
            category_id, rule_id = rule.category_id, rule.id
    if category_id is None and cmd.fallback_category_id is not None:
        guess = await repo.get_category(actor, cmd.fallback_category_id)
        if guess is not None and guess.active:
            category_id = guess.id
    if category_id is None:
        category_id = await default_category(repo, actor, Direction(cmd.direction))
    tx = Transaction(
        id=uuid4(),
        user_id=actor,
        direction=Direction(cmd.direction),
        amount=require_positive(cmd.amount),
        occurred_at=require_aware(cmd.occurred_at, field_name="occurred_at"),
        counterparty=clean_text(cmd.counterparty, field_name="counterparty"),
        category_id=category_id,
        notes=clean_text(cmd.notes, field_name="notes"),
        status=TransactionStatus(cmd.status),
        source=Source(cmd.source),
        created_at=now,
        updated_at=now,
        category_rule_id=rule_id,
    )
    await repo.insert_transaction(tx)
    if cmd.external_id is not None:
        external_id = clean_name(cmd.external_id, field_name="external id")
        await repo.claim_source(actor, tx.source, external_id, tx.id)
    await repo.insert_revision(actor, tx.id, RevisionKind.CREATE, None, now)
    return tx


# Where a transaction goes when nothing else decides: every one gets a category.
DEFAULT_FOR = {Direction.OUT: "other", Direction.IN: "income"}


async def default_category(
    repo: LedgerRepository, actor: UserId, direction: Direction
) -> UUID | None:
    """The user's "Other" (expenses) or "Income" category, if they still have it."""
    wanted = DEFAULT_FOR[direction]
    for c in await repo.list_categories(actor, include_inactive=False):
        if c.name.casefold() == wanted:
            return c.id
    return None


async def matching_rule(
    repo: LedgerRepository, actor: UserId, counterparty: str | None, notes: str | None
) -> CategoryRule | None:
    """The rule that would file an expense, skipping rules whose category is archived."""
    rules = await repo.list_category_rules(actor)
    if not rules:
        return None
    active = {c.id for c in await repo.list_categories(actor, include_inactive=False)}
    return best_rule((r for r in rules if r.category_id in active), counterparty, notes)


async def log_transaction(uow: UnitOfWork, actor: UserId, cmd: NewTransaction) -> Transaction:
    """Record money in or out.

    Raises DuplicateSource if ``external_id`` was seen before for this source,
    including when that transaction has since been deleted.
    """
    async with uow:
        tx = await create_transaction(uow.ledger, actor, cmd, now=utcnow())
        await uow.commit()
    return tx


async def _live_transaction(repo: LedgerRepository, actor: UserId, tx_id: UUID) -> Transaction:
    tx = await repo.get_transaction(actor, tx_id, for_update=True)
    if tx is None:
        raise NotFound("transaction not found")
    if tx.is_deleted:
        raise InvalidInput("this transaction is deleted; restore it first")
    return tx


def _owed(splits: list[Split], currency: str) -> Money:
    owed = Money.zero(currency)
    for split in splits:
        owed = owed + split.share
    return owed


async def edit_transaction(
    uow: UnitOfWork, actor: UserId, transaction_id: UUID, changes: TransactionChanges
) -> Transaction:
    async with uow:
        repo = uow.ledger
        tx = await _live_transaction(repo, actor, transaction_id)
        now = utcnow()
        updated = tx
        if changes.direction is not UNSET:
            updated = replace(updated, direction=Direction(changes.direction))
        if changes.amount is not UNSET:
            updated = replace(updated, amount=require_positive(changes.amount))
        if changes.occurred_at is not UNSET:
            updated = replace(
                updated, occurred_at=require_aware(changes.occurred_at, field_name="occurred_at")
            )
        if changes.counterparty is not UNSET:
            updated = replace(
                updated,
                counterparty=clean_text(changes.counterparty, field_name="counterparty"),
            )
        if changes.category_id is not UNSET:
            if changes.category_id is not None and changes.category_id != tx.category_id:
                await require_category(repo, actor, changes.category_id)
            if changes.category_id != tx.category_id:
                # The user chose the category, so no rule explains it any more.
                updated = replace(updated, category_id=changes.category_id, category_rule_id=None)
        if changes.notes is not UNSET:
            updated = replace(updated, notes=clean_text(changes.notes, field_name="notes"))
        if changes.status is not UNSET:
            updated = replace(updated, status=TransactionStatus(changes.status))
        if updated == tx:
            return tx

        splits = await repo.list_splits(actor, tx.id)
        if splits:
            if updated.direction is not Direction.OUT:
                raise Conflict("this bill is split with others; it must stay money out")
            if updated.amount.currency != tx.amount.currency:
                raise Conflict("this bill is split with others; its currency can't change")
            owed = _owed(splits, tx.amount.currency)
            if updated.amount < owed:
                raise Conflict(f"others owe {owed} on this bill; the amount can't go below that")

        updated = replace(updated, updated_at=now)
        await repo.update_transaction(updated)
        await repo.insert_revision(actor, tx.id, RevisionKind.EDIT, snapshot(tx), now)
        await uow.commit()
    return updated


async def delete_transaction(uow: UnitOfWork, actor: UserId, transaction_id: UUID) -> Transaction:
    """Soft delete. Its source claim stays, so the item is never re-imported."""
    async with uow:
        repo = uow.ledger
        tx = await repo.get_transaction(actor, transaction_id, for_update=True)
        if tx is None:
            raise NotFound("transaction not found")
        if tx.is_deleted:
            return tx
        now = utcnow()
        deleted = replace(tx, deleted_at=now, updated_at=now)
        await repo.update_transaction(deleted)
        await repo.insert_revision(actor, tx.id, RevisionKind.DELETE, snapshot(tx), now)
        await uow.commit()
    return deleted


async def restore_transaction(uow: UnitOfWork, actor: UserId, transaction_id: UUID) -> Transaction:
    async with uow:
        repo = uow.ledger
        tx = await repo.get_transaction(actor, transaction_id, for_update=True)
        if tx is None:
            raise NotFound("transaction not found")
        if not tx.is_deleted:
            return tx
        now = utcnow()
        restored = replace(tx, deleted_at=None, updated_at=now)
        await repo.update_transaction(restored)
        await repo.insert_revision(actor, tx.id, RevisionKind.RESTORE, snapshot(tx), now)
        await uow.commit()
    return restored


async def undo_last(uow: UnitOfWork, actor: UserId) -> UndoResult:
    """Reverse this user's most recent write that hasn't been undone.

    Repeated calls walk further back. An undo is not itself undoable.
    """
    async with uow:
        repo = uow.ledger
        revision = await repo.latest_open_revision(actor)
        if revision is None:
            raise NothingToUndo("there is nothing to undo")
        tx = await repo.get_transaction(actor, revision.transaction_id, for_update=True)
        if tx is None:  # pragma: no cover - revisions only point at this user's rows
            raise NotFound("transaction not found")
        now = utcnow()

        if revision.kind is RevisionKind.CREATE:
            reverted = replace(tx, deleted_at=now, updated_at=now)
        elif revision.kind is RevisionKind.SPLIT:
            if await repo.has_settlements(actor, tx.id):
                raise Conflict("repayments were recorded against this split, so it can't be undone")
            previous = (revision.before or {}).get("splits", [])
            await repo.replace_splits(
                actor,
                tx.id,
                [
                    Split(
                        uuid4(),
                        actor,
                        tx.id,
                        item["participant_name"],
                        Money.of(item["share"], tx.amount.currency),
                    )
                    for item in previous
                ],
            )
            reverted = tx
        else:
            if revision.before is None:  # pragma: no cover - only CREATE has no snapshot
                raise NothingToUndo("this change can't be undone")
            reverted = apply_snapshot(tx, revision.before, now=now)

        if reverted != tx:
            await repo.update_transaction(reverted)
        await repo.mark_undone(actor, revision.id, now)
        await uow.commit()
    return UndoResult(revision.kind, reverted)


async def get_transaction(uow: UnitOfWork, actor: UserId, transaction_id: UUID) -> Transaction:
    async with uow:
        tx = await uow.ledger.get_transaction(actor, transaction_id)
    if tx is None:
        raise NotFound("transaction not found")
    return tx


def _check_range(start: datetime | None, end: datetime | None) -> None:
    if start is not None:
        require_aware(start, field_name="start")
    if end is not None:
        require_aware(end, field_name="end")
    if start is not None and end is not None and start >= end:
        raise InvalidInput("start must be before end")


async def list_ledger(uow: UnitOfWork, actor: UserId, query: LedgerQuery) -> Page:
    if not 1 <= query.limit <= MAX_PAGE:
        raise InvalidInput(f"limit must be between 1 and {MAX_PAGE}")
    if query.offset < 0:
        raise InvalidInput("offset must not be negative")
    if query.uncategorized and query.category_id is not None:
        raise InvalidInput("choose a category or uncategorized, not both")
    _check_range(query.start, query.end)
    cleaned = replace(query, search=clean_text(query.search, field_name="search", limit=100))
    async with uow:
        return await uow.ledger.list_transactions(actor, cleaned)


@dataclass(frozen=True, slots=True)
class HomeTotal:
    direction: Direction
    total: Money  # in the home currency, including converted foreign amounts
    count: int
    converted: list[Money]  # foreign originals included in ``total``, per currency
    unconverted: list[Money]  # foreign amounts left out for want of a rate


@dataclass(frozen=True, slots=True)
class HomeCategoryTotal:
    category_id: UUID | None
    category_name: str | None
    total: Money
    count: int


@dataclass(frozen=True, slots=True)
class HomeSummary:
    start: datetime
    end: datetime
    currency: str
    totals: list[HomeTotal]  # one per direction, out first
    spending_by_category: list[HomeCategoryTotal]  # largest first


def _by_currency(amounts: list[Money]) -> list[Money]:
    merged: dict[str, Money] = {}
    for m in amounts:
        merged[m.currency] = merged[m.currency] + m if m.currency in merged else m
    return [merged[c] for c in sorted(merged)]


async def summarize_in_home(
    uow: UnitOfWork, rates: RateSource, user: User, start: datetime, end: datetime
) -> HomeSummary:
    """Totals in [start, end) in the user's home currency.

    Foreign amounts convert per local day at that day's rate (or the latest one
    before it). Amounts with no available rate are reported, not guessed.
    """
    _check_range(start, end)
    home = user.home_currency
    async with uow:
        days = await uow.ledger.totals_by_day(user.id, start, end, user.timezone)
    found = await fx.rates_for(rates, home, ((d.total.currency, d.day) for d in days))
    totals: list[HomeTotal] = []
    for direction in (Direction.OUT, Direction.IN):
        total, count = Money.zero(home), 0
        converted: list[Money] = []
        unconverted: list[Money] = []
        for d in days:
            if d.direction is not direction:
                continue
            result = fx.convert(d.total, d.day, home, found)
            if result.home is None:
                unconverted.append(d.total)
                continue
            total, count = total + result.home, count + d.count
            if d.total.currency != home:
                converted.append(d.total)
        totals.append(
            HomeTotal(direction, total, count, _by_currency(converted), _by_currency(unconverted))
        )
    categories: dict[UUID | None, HomeCategoryTotal] = {}
    for d in days:
        if d.direction is not Direction.OUT:
            continue
        amount = fx.convert(d.total, d.day, home, found).home
        if amount is None:
            continue
        prior = categories.get(d.category_id)
        categories[d.category_id] = HomeCategoryTotal(
            d.category_id,
            d.category_name,
            prior.total + amount if prior else amount,
            (prior.count if prior else 0) + d.count,
        )
    ranked = sorted(categories.values(), key=lambda c: (-c.total.amount, c.category_name or ""))
    return HomeSummary(start, end, home, totals, ranked)


async def summarize(uow: UnitOfWork, actor: UserId, start: datetime, end: datetime) -> Summary:
    """Confirmed, non-deleted totals in [start, end), per currency.

    Currencies are never mixed; ``summarize_in_home`` converts to one currency.
    """
    _check_range(start, end)
    async with uow:
        totals = await uow.ledger.totals_by_direction(actor, start, end)
        by_category = await uow.ledger.spending_by_category(actor, start, end)
    return Summary(start, end, totals, by_category)


MAX_BULK = 500


async def _bulk(
    uow: UnitOfWork, actor: UserId, ids: list[UUID], *, delete: bool
) -> list[Transaction]:
    unique = list(dict.fromkeys(ids))
    if not 1 <= len(unique) <= MAX_BULK:
        raise InvalidInput(f"choose between 1 and {MAX_BULK} transactions")
    changed: list[Transaction] = []
    async with uow:
        repo = uow.ledger
        now = utcnow()
        for tx_id in unique:
            tx = await repo.get_transaction(actor, tx_id, for_update=True)
            if tx is None:
                raise NotFound("transaction not found")  # all or nothing
            if tx.is_deleted == delete:
                continue
            updated = replace(tx, deleted_at=now if delete else None, updated_at=now)
            await repo.update_transaction(updated)
            kind = RevisionKind.DELETE if delete else RevisionKind.RESTORE
            await repo.insert_revision(actor, tx.id, kind, snapshot(tx), now)
            changed.append(updated)
        await uow.commit()
    return changed


async def bulk_delete(uow: UnitOfWork, actor: UserId, ids: list[UUID]) -> list[Transaction]:
    """Soft-delete several at once. Undo with bulk_restore on the same ids."""
    return await _bulk(uow, actor, ids, delete=True)


async def bulk_restore(uow: UnitOfWork, actor: UserId, ids: list[UUID]) -> list[Transaction]:
    return await _bulk(uow, actor, ids, delete=False)
