"""Possible duplicates in the ledger: finding them, merging a pair into one, and
remembering a pair the user says is two payments.

Merging never happens on a guess: the user taps Merge (or "Same one" on an email).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import transactions as tx_cases
from nexus.application.ports import LedgerQuery, UnitOfWork
from nexus.domain.duplicates import (
    NEAR_DAYS,
    Candidate,
    better_name,
    candidate,
    likely_same,
    pair_key,
)
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Transaction, User, UserId

type UowFactory = Callable[[], UnitOfWork]

# How many transactions around a date range are looked through for matches.
_POOL = 2_000


@dataclass(frozen=True, slots=True)
class Pair:
    first: Transaction
    second: Transaction


async def _pool(
    tx: UnitOfWork, user_id: UserId, start: datetime, end: datetime
) -> list[Transaction]:
    page = await tx.ledger.list_transactions(
        user_id, LedgerQuery(start=start, end=end, limit=_POOL)
    )
    return page.items


def _closest(
    item: Candidate, pool: Iterable[Transaction], tz: ZoneInfo, skip: Callable[[Transaction], bool]
) -> Transaction | None:
    found = [t for t in pool if not skip(t) and likely_same(item, candidate(t), tz)]
    return min(found, key=lambda t: abs(t.occurred_at - item.occurred_at), default=None)


async def matches(uow: UnitOfWork, user: User, items: list[Transaction]) -> dict[UUID, Transaction]:
    """For each of these live transactions, the one it most likely duplicates, if
    any, leaving out pairs the user said are two payments."""
    live = [t for t in items if not t.is_deleted]
    if not live:
        return {}
    tz = ZoneInfo(user.timezone)
    margin = timedelta(days=NEAR_DAYS + 1)
    async with uow:
        pool = await _pool(
            uow,
            user.id,
            min(t.occurred_at for t in live) - margin,
            max(t.occurred_at for t in live) + margin,
        )
        dismissed = await uow.ledger.dismissed_pairs(user.id, [t.id for t in live])
    found: dict[UUID, Transaction] = {}
    for tx in live:

        def skip(t: Transaction, mine: Transaction = tx) -> bool:
            return t.id == mine.id or pair_key(t.id, mine.id) in dismissed

        other = _closest(candidate(tx), pool, tz, skip)
        if other is not None:
            found[tx.id] = other
    return found


async def find_pairs(uow: UowFactory, user: User, start: datetime, end: datetime) -> list[Pair]:
    """Possible duplicates logged in [start, end), each pair once, newest first."""
    async with uow() as tx:
        items = await _pool(tx, user.id, start, end)
    found = await matches(uow(), user, items)
    pairs: dict[tuple[str, str], Pair] = {}
    for tx_id, other in found.items():
        mine = next(t for t in items if t.id == tx_id)
        first, second = sorted((mine, other), key=lambda t: t.occurred_at, reverse=True)
        pairs.setdefault(pair_key(mine.id, other.id), Pair(first, second))
    return sorted(pairs.values(), key=lambda p: p.first.occurred_at, reverse=True)


async def check(uow: UnitOfWork, user: User, item: Candidate) -> Transaction | None:
    """The live transaction a payment about to be logged most likely duplicates."""
    tz = ZoneInfo(user.timezone)
    margin = timedelta(days=NEAR_DAYS + 1)
    async with uow:
        pool = await _pool(uow, user.id, item.occurred_at - margin, item.occurred_at + margin)
    return _closest(item, pool, tz, lambda _: False)


async def dismiss(uow: UnitOfWork, user_id: UserId, a: UUID, b: UUID, *, now: datetime) -> None:
    """The user says these are two payments: never flag the pair again."""
    if a == b:
        raise InvalidInput("those are the same transaction")
    async with uow:
        for tx_id in (a, b):
            if await uow.ledger.get_transaction(user_id, tx_id) is None:
                raise NotFound("transaction not found")
        await uow.ledger.dismiss_pair(user_id, pair_key(a, b), now)
        await uow.commit()


@dataclass(frozen=True, slots=True)
class Merged:
    kept: Transaction
    removed: Transaction


async def merge(uow: UowFactory, user_id: UserId, a: UUID, b: UUID) -> Merged:
    """Keep one of two records of the same payment, under the more readable name, and
    delete the other (it can be restored, or undone). The one kept is the one a
    split, repayment or receipt hangs on; otherwise the one logged first."""
    if a == b:
        raise InvalidInput("those are the same transaction")
    first = await tx_cases.get_transaction(uow(), user_id, a)
    second = await tx_cases.get_transaction(uow(), user_id, b)
    if first.is_deleted or second.is_deleted:
        raise InvalidInput("one of those is already deleted")
    if first.direction is not second.direction or first.amount != second.amount:
        raise InvalidInput("those aren't the same amount, so they can't be one payment")
    async with uow() as tx:
        moved = await tx.ledger.lineage(user_id, [a, b])
        kept_receipts = await tx.ledger.transactions_with_receipts(user_id, [a, b])
    tied = [t for t in (first, second) if t.id in moved]
    if len(tied) == 2:
        raise InvalidInput(
            "both are part of split bills or repayments; delete the one you don't want by hand"
        )

    def rank(t: Transaction) -> tuple[bool, bool, datetime]:
        return (t.id not in moved, t.id not in kept_receipts, t.created_at)

    keep, drop = sorted((first, second), key=rank)
    name = better_name(keep.counterparty, drop.counterparty)
    if name != keep.counterparty:
        keep = await tx_cases.edit_transaction(
            uow(), user_id, keep.id, tx_cases.TransactionChanges(counterparty=name)
        )
    removed = await tx_cases.delete_transaction(uow(), user_id, drop.id)
    return Merged(keep, removed)
