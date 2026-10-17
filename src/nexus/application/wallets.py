"""Wallets (named places money sits) and moves of money between them.

Nexus only records moves; it never moves money. A move is never spending and never income.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.clock import utcnow
from nexus.application.ports import LedgerQuery, LedgerRepository, UnitOfWork
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.ledger import (
    Direction,
    RevisionKind,
    Source,
    Transaction,
    TransactionStatus,
    UserId,
    Wallet,
    WalletKind,
    clean_name,
    clean_text,
    require_aware,
    require_positive,
    snapshot,
)
from nexus.domain.money import Money
from nexus.domain.wallets import match_wallet

SPENDING_NAME = "Spending"
MAX_MATCH_WORDS = 20
MAX_MATCH_WORD = 60


def new_spending_wallet(user_id: UserId) -> Wallet:
    """The wallet every user starts with: their main account, the one the budget watches."""
    return Wallet(uuid4(), user_id, SPENDING_NAME, WalletKind.SPENDING)


def _kind(value: WalletKind | str) -> WalletKind:
    try:
        return WalletKind(value)
    except ValueError as exc:
        kinds = ", ".join(k.value for k in WalletKind if k is not WalletKind.SPENDING)
        raise InvalidInput(f"wallet kind must be one of: {kinds}") from exc


def _match_words(words: Iterable[str]) -> tuple[str, ...]:
    cleaned: dict[str, str] = {}
    for word in words:
        text = clean_text(word, field_name="match word", limit=MAX_MATCH_WORD)
        if text is not None:
            cleaned.setdefault(text.casefold(), text)
    if len(cleaned) > MAX_MATCH_WORDS:
        raise InvalidInput(f"a wallet can have at most {MAX_MATCH_WORDS} match words")
    return tuple(cleaned.values())


async def require_wallet(repo: LedgerRepository, actor: UserId, wallet_id: UUID) -> Wallet:
    wallet = await repo.get_wallet(actor, wallet_id)
    if wallet is None:
        raise NotFound("wallet not found")
    return wallet


async def _spending(repo: LedgerRepository, actor: UserId) -> Wallet:
    wallet = await repo.spending_wallet(actor)
    if wallet is None:  # pragma: no cover - every user is given one
        raise InvalidInput("there is no Spending wallet")
    return wallet


async def list_wallets(uow: UnitOfWork, actor: UserId) -> list[Wallet]:
    """Spending first, then the rest by name."""
    async with uow:
        return await uow.ledger.list_wallets(actor)


async def add_wallet(
    uow: UnitOfWork,
    actor: UserId,
    name: str,
    kind: WalletKind | str,
    match_words: Iterable[str] = (),
) -> Wallet:
    wallet_kind = _kind(kind)
    if wallet_kind is WalletKind.SPENDING:
        raise InvalidInput("everyone has one Spending wallet already")
    wallet = Wallet(
        uuid4(),
        actor,
        clean_name(name, field_name="wallet name"),
        wallet_kind,
        _match_words(match_words),
    )
    async with uow:
        await uow.ledger.insert_wallet(wallet)
        await uow.commit()
    return wallet


async def update_wallet(
    uow: UnitOfWork,
    actor: UserId,
    wallet_id: UUID,
    *,
    name: str | None = None,
    kind: WalletKind | str | None = None,
    match_words: Iterable[str] | None = None,
) -> Wallet:
    """Change what's given. The Spending wallet keeps its kind, and no other wallet can
    become it."""
    async with uow:
        wallet = await require_wallet(uow.ledger, actor, wallet_id)
        updated = wallet
        if name is not None:
            updated = replace(updated, name=clean_name(name, field_name="wallet name"))
        if kind is not None:
            new_kind = _kind(kind)
            if new_kind is not wallet.kind and WalletKind.SPENDING in (new_kind, wallet.kind):
                raise InvalidInput("the Spending wallet can't change kind, and no other can be it")
            updated = replace(updated, kind=new_kind)
        if match_words is not None:
            updated = replace(updated, match_words=_match_words(match_words))
        if updated != wallet:
            await uow.ledger.update_wallet(updated)
            await uow.commit()
    return updated


async def rename_wallet(uow: UnitOfWork, actor: UserId, wallet_id: UUID, name: str) -> Wallet:
    return await update_wallet(uow, actor, wallet_id, name=name)


_NEEDS_ANOTHER = "this wallet has moves or scheduled payments; pick another wallet to move them to"


@dataclass(frozen=True, slots=True)
class WalletDeleted:
    wallet: Wallet
    into: Wallet | None  # where its moves went, if it had any
    moved: int  # moves now pointing at ``into``
    removed: int  # moves between the two, which would have been from a wallet to itself
    bills: int = 0  # scheduled payments that moved money to it, now pointing at ``into``


async def delete_wallet(
    uow: UnitOfWork,
    actor: UserId,
    wallet_id: UUID,
    move_to: UUID | None = None,
    *,
    now: datetime | None = None,
) -> WalletDeleted:
    """Delete a wallet. Moves into or out of it, and scheduled payments that move money to
    it, need ``move_to``, another wallet of the user's, to point at instead; those moves
    between the two are removed (there's nothing to record about money moved from a wallet
    to itself). Scheduled payments moved to Spending would go nowhere, so they stay as
    plain not-spending ones. Not undoable."""
    if move_to == wallet_id:
        raise InvalidInput("pick a different wallet to move its moves to")
    async with uow:
        repo = uow.ledger
        wallet = await require_wallet(repo, actor, wallet_id)
        if wallet.kind is WalletKind.SPENDING:
            raise InvalidInput("the Spending wallet can't be deleted")
        into = await require_wallet(repo, actor, move_to) if move_to is not None else None
        has_moves = await repo.count_moves(actor, wallet.id) > 0
        scheduled = await uow.planning.count_bills_for_wallet(actor, wallet.id)
        moved = removed = 0
        if has_moves or scheduled:
            if into is None:
                raise InvalidInput(_NEEDS_ANOTHER)
            if has_moves:
                moved, removed = await repo.repoint_moves(
                    actor, wallet.id, into.id, now or utcnow()
                )
        # Archived scheduled payments still name it, so they go along (or lose it).
        target = into.id if into is not None and into.kind is not WalletKind.SPENDING else None
        await uow.planning.repoint_bills(actor, wallet.id, target)
        await repo.delete_wallet(actor, wallet.id)
        await uow.commit()
    return WalletDeleted(
        wallet, into if has_moves or scheduled else None, moved, removed, scheduled
    )


async def preview_delete_wallet(
    uow: UnitOfWork, actor: UserId, wallet_id: UUID, move_to: UUID | None = None
) -> WalletDeleted:
    """What ``delete_wallet`` would do with the same arguments, without doing it: the same
    checks, the same counts. Read-only."""
    if move_to == wallet_id:
        raise InvalidInput("pick a different wallet to move its moves to")
    async with uow:
        repo = uow.ledger
        wallet = await require_wallet(repo, actor, wallet_id)
        if wallet.kind is WalletKind.SPENDING:
            raise InvalidInput("the Spending wallet can't be deleted")
        into = await require_wallet(repo, actor, move_to) if move_to is not None else None
        total = await repo.count_moves(actor, wallet.id)
        scheduled = await uow.planning.count_bills_for_wallet(actor, wallet.id)
        if total == 0 and scheduled == 0:
            return WalletDeleted(wallet, None, 0, 0)
        if into is None:
            raise InvalidInput(_NEEDS_ANOTHER)
        between = 0
        for origin, target in ((wallet.id, into.id), (into.id, wallet.id)) if total else ():
            page = await repo.list_transactions(
                actor,
                LedgerQuery(
                    direction=Direction.MOVE,
                    from_wallet_id=origin,
                    to_wallet_id=target,
                    include_deleted=True,
                    limit=1,
                ),
            )
            between += page.total
    return WalletDeleted(wallet, into, total - between, between, scheduled)


async def create_move(
    repo: LedgerRepository,
    actor: UserId,
    *,
    amount: Money,
    origin: Wallet,
    target: Wallet,
    occurred_at: datetime,
    now: datetime,
    received_amount: Money | None = None,
    notes: str | None = None,
    counterparty: str | None = None,
    source: Source = Source.MANUAL,
    external_id: str | None = None,
) -> Transaction:
    """Validate and store a new move with its revision (and its source claim, for one
    that came from a statement or an email). Runs inside the caller's unit of work, which
    commits; ``log_move`` is the use case for one move. Raises DuplicateSource if
    ``external_id`` was seen before for this source."""
    amount = require_positive(amount)
    if received_amount is not None:
        require_positive(received_amount)
    occurred_at = require_aware(occurred_at, field_name="occurred_at")
    if origin.id == target.id:
        raise InvalidInput("a move needs two different wallets")
    tx = Transaction(
        id=uuid4(),
        user_id=actor,
        direction=Direction.MOVE,
        amount=amount,
        occurred_at=occurred_at,
        counterparty=clean_text(counterparty, field_name="counterparty"),
        category_id=None,
        notes=clean_text(notes, field_name="notes"),
        status=TransactionStatus.CONFIRMED,
        source=Source(source),
        created_at=now,
        updated_at=now,
        from_wallet_id=origin.id,
        to_wallet_id=target.id,
        received_amount=received_amount,
    )
    await repo.insert_transaction(tx)
    if external_id is not None:
        await repo.claim_source(
            actor, tx.source, clean_name(external_id, field_name="external id"), tx.id
        )
    await repo.insert_revision(actor, tx.id, RevisionKind.CREATE, None, now)
    return tx


async def log_move(
    uow: UnitOfWork,
    actor: UserId,
    *,
    amount: Money,
    to_wallet_id: UUID,
    occurred_at: datetime,
    from_wallet_id: UUID | None = None,
    received_amount: Money | None = None,
    notes: str | None = None,
    counterparty: str | None = None,
    source: Source = Source.MANUAL,
    external_id: str | None = None,
) -> Transaction:
    """Record money moved between two of the user's wallets (from Spending unless said
    otherwise). ``received_amount`` is what arrived, if that isn't ``amount`` (another
    currency, or a fee). Undoable like any new transaction. With an ``external_id`` the
    same one is recorded once: a second try raises DuplicateSource."""
    async with uow:
        repo = uow.ledger
        origin = (
            await require_wallet(repo, actor, from_wallet_id)
            if from_wallet_id is not None
            else await _spending(repo, actor)
        )
        target = await require_wallet(repo, actor, to_wallet_id)
        tx = await create_move(
            repo,
            actor,
            amount=amount,
            origin=origin,
            target=target,
            occurred_at=occurred_at,
            now=utcnow(),
            received_amount=received_amount,
            notes=notes,
            counterparty=counterparty,
            source=source,
            external_id=external_id,
        )
        await uow.commit()
    return tx


async def mark_as_move(
    uow: UnitOfWork, actor: UserId, transaction_id: UUID, wallet_id: UUID
) -> Transaction:
    """Turn money out into a move from Spending to ``wallet_id``, or money in into a move
    from it to Spending (say a salary-day transfer to savings that was logged as spending).
    The category goes; undo brings the original back. Refused for a bill split with others
    and for money in that paid back an IOU."""
    async with uow:
        repo = uow.ledger
        tx = await repo.get_transaction(actor, transaction_id, for_update=True)
        if tx is None:
            raise NotFound("transaction not found")
        if tx.is_deleted:
            raise InvalidInput("this transaction is deleted; restore it first")
        if tx.direction is Direction.MOVE:
            raise InvalidInput("this is already a move")
        wallet = await require_wallet(repo, actor, wallet_id)
        if wallet.kind is WalletKind.SPENDING:
            raise InvalidInput("pick a wallet other than Spending to move it to or from")
        if await repo.list_splits(actor, tx.id):
            raise Conflict("this bill is split with others, so it can't be a move")
        if await repo.has_settlements(actor, tx.id) or await repo.has_settlements_for_income(
            actor, tx.id
        ):
            raise Conflict("this money paid back what friends owed, so it can't be a move")
        spending = await _spending(repo, actor)
        sent, received = (spending, wallet) if tx.direction is Direction.OUT else (wallet, spending)
        now = utcnow()
        moved = replace(
            tx,
            direction=Direction.MOVE,
            category_id=None,
            category_rule_id=None,
            from_wallet_id=sent.id,
            to_wallet_id=received.id,
            updated_at=now,
        )
        await repo.update_transaction(moved)
        await repo.insert_revision(actor, tx.id, RevisionKind.EDIT, snapshot(tx), now)
        await uow.commit()
    return moved


# --- entries that look like moves ------------------------------------------------------

LIKELY_MONTHS = 6  # how far back to look
REGULAR_RUN = 3  # months in a row, the same payee and amount, before it looks regular


@dataclass(frozen=True, slots=True)
class LikelyMove:
    """An entry that may really have been a move. Only a suggestion: nothing is changed
    until the user says so (``mark_as_move``)."""

    transaction: Transaction
    wallet: Wallet | None  # where it would go; None when only the pattern suggests a move
    reason: str


def _month(when: datetime, tz: ZoneInfo) -> int:
    day = when.astimezone(tz)
    return day.year * 12 + day.month - 1


def _regular_runs(txs: list[Transaction], tz: ZoneInfo, now: datetime) -> list[Transaction]:
    """Entries that are part of a run of ``REGULAR_RUN`` or more months in a row with one
    payment of the same amount to the same payee each (a month with two such payments
    doesn't count), a run that is still going: it reaches this month or the last."""
    groups: dict[tuple[str, str, str], list[Transaction]] = {}
    for tx in txs:
        if tx.direction is Direction.OUT and tx.counterparty and tx.category_rule_id is None:
            key = (tx.counterparty.casefold(), str(tx.amount.amount), tx.amount.currency)
            groups.setdefault(key, []).append(tx)
    this_month = _month(now, tz)
    found: list[Transaction] = []
    for group in groups.values():
        by_month: dict[int, list[Transaction]] = {}
        for tx in group:
            by_month.setdefault(_month(tx.occurred_at, tz), []).append(tx)
        months = sorted(m for m, items in by_month.items() if len(items) == 1)
        run: list[int] = []  # the latest unbroken run of months; only it can still be going
        for m in months:
            run = [*run, m] if run and run[-1] == m - 1 else [m]
        if len(run) >= REGULAR_RUN and run[-1] >= this_month - 1:
            found.extend(by_month[m][0] for m in run)
    return found


async def likely_moves(uow: UnitOfWork, actor: UserId, *, now: datetime) -> list[LikelyMove]:
    """Money in or out of the last six months that may have been a move, newest first:
    entries naming one of the user's wallets (by its match words), and a payment of the
    same amount to the same payee every month for three months or more (a regular
    transfer). Splits, repayments of IOUs, deleted entries and moves are never offered.
    Read-only."""
    async with uow:
        repo = uow.ledger
        user = await repo.get_user(actor)
        if user is None:
            raise NotFound("user not found")
        tz = ZoneInfo(user.timezone)
        wallets = await repo.list_wallets(actor)
        page = await repo.list_transactions(
            actor,
            LedgerQuery(
                start=now - timedelta(days=30 * LIKELY_MONTHS),
                end=now,
                status=TransactionStatus.CONFIRMED,
                limit=10_000,
            ),
        )
        live = [t for t in page.items if t.direction in (Direction.IN, Direction.OUT)]
        reasons: dict[UUID, tuple[Wallet | None, str]] = {}
        for tx in live:
            found = match_wallet([tx.counterparty, tx.notes], wallets)
            if found is not None:
                reasons[tx.id] = (found.wallet, f"matches '{found.word}'")
        for tx in _regular_runs([t for t in live if t.id not in reasons], tz, now):
            reasons[tx.id] = (
                None,
                f"looks like a regular transfer: {tx.amount} to {tx.counterparty} "
                f"every month for {REGULAR_RUN}+ months",
            )
        offered: list[LikelyMove] = []
        for tx in live:
            if tx.id not in reasons:
                continue
            if await repo.list_splits(actor, tx.id):
                continue
            if await repo.has_settlements(actor, tx.id) or await repo.has_settlements_for_income(
                actor, tx.id
            ):
                continue
            wallet, reason = reasons[tx.id]
            offered.append(LikelyMove(tx, wallet, reason))
    return sorted(offered, key=lambda m: m.transaction.occurred_at, reverse=True)
