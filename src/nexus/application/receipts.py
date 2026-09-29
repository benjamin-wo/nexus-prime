"""The receipt archive: store a receipt, attach it to its expense, hand out
short-lived download links, and erase what's due."""

import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from nexus.application.ports import ReceiptStore, UnitOfWork
from nexus.application.transactions import NewTransaction, create_transaction
from nexus.domain.errors import NotFound
from nexus.domain.ledger import Transaction, UserId
from nexus.domain.receipts import LINK_TTL, UNCLAIMED_TTL, Receipt, check_file, object_key

log = logging.getLogger(__name__)
PURGE_BATCH = 100

type UowFactory = Callable[[], UnitOfWork]


async def stash(
    uow: UnitOfWork,
    store: ReceiptStore,
    actor: UserId,
    data: bytes,
    content_type: str,
    *,
    now: datetime,
) -> Receipt:
    """Keep a receipt file before its expense is confirmed. If the expense is never
    saved, the purge job erases the file after a day."""
    kind = check_file(data, content_type)
    receipt_id = uuid4()
    receipt = Receipt(receipt_id, actor, None, object_key(actor, receipt_id), kind, len(data), now)
    await store.put(receipt.object_key, data, kind)
    try:
        async with uow:
            await uow.ledger.insert_receipt(receipt)
            await uow.commit()
    except Exception:
        await store.delete(receipt.object_key)
        raise
    return receipt


async def log_with_receipt(
    uow: UnitOfWork,
    actor: UserId,
    cmd: NewTransaction,
    receipt_id: UUID | None,
    *,
    now: datetime,
) -> Transaction:
    """Save an expense and attach its stored receipt, together or not at all."""
    async with uow:
        tx = await create_transaction(uow.ledger, actor, cmd, now=now)
        if receipt_id is not None:
            attached = await uow.ledger.attach_receipt(
                actor, receipt_id, tx.id, stashed_after=now - UNCLAIMED_TTL
            )
            if not attached:
                raise NotFound("that receipt photo has expired; please send it again")
        await uow.commit()
    return tx


async def download_link(
    uow: UnitOfWork, store: ReceiptStore, actor: UserId, transaction_id: UUID
) -> str:
    """A link to the receipt of the user's own, undeleted transaction, valid for minutes."""
    async with uow:
        receipt = await uow.ledger.live_receipt(actor, transaction_id)
    if receipt is None:
        raise NotFound("no receipt for that transaction")
    return store.download_url(receipt.object_key, filename=receipt.filename, expires=LINK_TTL)


async def with_receipts(uow: UnitOfWork, actor: UserId, transaction_ids: list[UUID]) -> set[UUID]:
    async with uow:
        return await uow.ledger.transactions_with_receipts(actor, transaction_ids)


async def purge(uow: UowFactory, store: ReceiptStore, *, now: datetime) -> int:
    """Erase receipts that are due: the file first, then its row, so a failure is
    retried on the next run instead of leaving an untracked file behind."""
    async with uow() as tx:
        due = await tx.ledger.receipts_to_purge(now, PURGE_BATCH)
    erased = 0
    for receipt in due:
        try:
            await store.delete(receipt.object_key)
            async with uow() as tx:
                await tx.ledger.delete_receipt(receipt.user_id, receipt.id)
                await tx.commit()
            erased += 1
        except Exception:
            log.exception("could not purge a receipt")
    return erased
