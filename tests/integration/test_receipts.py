"""The receipt archive: photos kept with their expense, hidden when it's deleted,
purged 30 days later, and never reachable by another user."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.receipts import ReceiptDraft
from nexus.agent.service import AgentService
from nexus.application import receipts as receipt_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import (
    NewTransaction,
    delete_transaction,
    list_ledger,
    restore_transaction,
)
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, Source, UserId
from nexus.domain.money import Money
from nexus.infra.db.tables import receipts
from tests.fakes import NOW, FakeBucket, FakeReceipts, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration

DRAFT = ReceiptDraft(is_receipt=True, amount="23.40", merchant="FairPrice", date="2026-09-27")


def agent(uow: UowFactory, bucket: FakeBucket, draft: ReceiptDraft = DRAFT) -> AgentService:
    return build(uow, scripted(), FakeReceipts(draft), bucket)


async def photo(agent: AgentService, user: UserId, ref: str = "telegram-photo:u1") -> str:
    """Send a receipt photo; returns the confirmation id."""
    reply = only(await agent.handle_photo(user, b"\xff\xd8jpeg", "image/jpeg", None, ref))
    assert reply.text == "Log 23.40 SGD at FairPrice on 2026-09-27 from this receipt?"
    return reply.buttons[0][0].data.split(":")[1]


async def only_tx(uow: UowFactory, user: UserId, **query: object) -> UUID:
    page = await list_ledger(uow(), user, LedgerQuery(**query))  # type: ignore[arg-type]
    assert page.total == 1
    return page.items[0].id


async def test_a_confirmed_photo_is_kept_with_its_expense(uow: UowFactory, alice: UserId) -> None:
    bucket = FakeBucket()
    bot = agent(uow, bucket)
    await bot.resolve(alice, await photo(bot, alice), True)
    tx_id = await only_tx(uow, alice)

    [(key, (data, kind))] = bucket.objects.items()
    assert key.startswith(f"receipts/{alice}/") and data == b"\xff\xd8jpeg"
    assert kind == "image/jpeg"
    assert await receipt_cases.with_receipts(uow(), alice, [tx_id]) == {tx_id}
    link = await receipt_cases.download_link(uow(), bucket, alice, tx_id)
    assert link.startswith(f"https://bucket.test/{key}?expires=300&name=receipt-")


async def test_a_declined_photo_is_purged_after_a_day(uow: UowFactory, alice: UserId) -> None:
    bucket = FakeBucket()
    bot = agent(uow, bucket)
    await bot.resolve(alice, await photo(bot, alice), False)
    assert len(bucket.objects) == 1
    assert await receipt_cases.purge(uow, bucket, now=NOW + timedelta(hours=23)) == 0
    assert await receipt_cases.purge(uow, bucket, now=NOW + timedelta(days=1)) == 1
    assert bucket.objects == {}


async def test_deleted_expenses_hide_then_purge_their_receipt(
    uow: UowFactory, alice: UserId
) -> None:
    bucket = FakeBucket()
    bot = agent(uow, bucket)
    await bot.resolve(alice, await photo(bot, alice), True)
    tx_id = await only_tx(uow, alice)
    deleted = await delete_transaction(uow(), alice, tx_id)
    assert deleted.deleted_at is not None
    with pytest.raises(NotFound):  # hidden while deleted
        await receipt_cases.download_link(uow(), bucket, alice, tx_id)

    # Restoring brings it back.
    await restore_transaction(uow(), alice, tx_id)
    assert await receipt_cases.download_link(uow(), bucket, alice, tx_id)

    deleted = await delete_transaction(uow(), alice, tx_id)
    assert deleted.deleted_at is not None
    too_soon = deleted.deleted_at + timedelta(days=29, hours=23)
    assert await receipt_cases.purge(uow, bucket, now=too_soon) == 0
    assert len(bucket.objects) == 1
    due = deleted.deleted_at + timedelta(days=30)
    assert await receipt_cases.purge(uow, bucket, now=due) == 1
    assert bucket.objects == {}
    assert await receipt_cases.with_receipts(uow(), alice, [tx_id]) == set()
    # The expense stays deleted and restorable; only the file is gone.
    await restore_transaction(uow(), alice, tx_id)
    with pytest.raises(NotFound):
        await receipt_cases.download_link(uow(), bucket, alice, tx_id)


async def test_a_failed_purge_is_retried(uow: UowFactory, alice: UserId) -> None:
    bucket = FakeBucket(fail_deletes=True)
    await receipt_cases.stash(uow(), bucket, alice, b"x", "image/png", now=NOW)
    later = NOW + timedelta(days=2)
    assert await receipt_cases.purge(uow, bucket, now=later) == 0
    bucket.fail_deletes = False
    assert await receipt_cases.purge(uow, bucket, now=later) == 1
    assert bucket.objects == {}


async def test_receipts_are_private(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    bucket = FakeBucket()
    bot = agent(uow, bucket)
    await bot.resolve(alice, await photo(bot, alice), True)
    tx_id = await only_tx(uow, alice)
    with pytest.raises(NotFound):
        await receipt_cases.download_link(uow(), bucket, bob, tx_id)
    assert await receipt_cases.with_receipts(uow(), bob, [tx_id]) == set()

    # Bob can't claim a receipt Alice stored, even knowing its id.
    stored = await receipt_cases.stash(uow(), bucket, alice, b"x", "image/png", now=NOW)
    cmd = NewTransaction(Direction.OUT, Money.of("5", "SGD"), NOW, source=Source.PHOTO)
    with pytest.raises(NotFound):
        await receipt_cases.log_with_receipt(uow(), bob, cmd, stored.id, now=NOW)
    assert (await list_ledger(uow(), bob, LedgerQuery())).total == 0  # rolled back

    # And the database refuses to link Bob's expense to Alice's receipt.
    theirs = await receipt_cases.log_with_receipt(uow(), bob, cmd, None, now=NOW)
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                update(receipts)
                .where(receipts.c.id == stored.id)
                .values(transaction_id=theirs.id)  # still Alice's row
            )


async def test_a_receipt_is_claimed_once_and_only_while_fresh(
    uow: UowFactory, alice: UserId
) -> None:
    bucket = FakeBucket()
    stored = await receipt_cases.stash(uow(), bucket, alice, b"x", "image/png", now=NOW)
    cmd = NewTransaction(Direction.OUT, Money.of("5", "SGD"), NOW)
    stale = NOW + timedelta(days=1, minutes=1)
    with pytest.raises(NotFound, match="expired"):
        await receipt_cases.log_with_receipt(uow(), alice, cmd, stored.id, now=stale)
    await receipt_cases.log_with_receipt(uow(), alice, cmd, stored.id, now=NOW)
    with pytest.raises(NotFound):
        await receipt_cases.log_with_receipt(uow(), alice, cmd, stored.id, now=NOW)
    with pytest.raises(NotFound):
        await receipt_cases.log_with_receipt(uow(), alice, cmd, uuid4(), now=NOW)


async def test_without_a_bucket_photos_still_log(uow: UowFactory, alice: UserId) -> None:
    bot = build(uow, scripted(), FakeReceipts(DRAFT))
    await bot.resolve(alice, await photo(bot, alice), True)
    tx_id = await only_tx(uow, alice)
    assert await receipt_cases.with_receipts(uow(), alice, [tx_id]) == set()


async def test_storage_trouble_doesnt_lose_the_expense(uow: UowFactory, alice: UserId) -> None:
    class BrokenBucket(FakeBucket):
        async def put(self, key: str, data: bytes, content_type: str) -> None:
            raise OSError("bucket unavailable")

    bot = build(uow, scripted(), FakeReceipts(DRAFT), BrokenBucket())
    await bot.resolve(alice, await photo(bot, alice), True)
    await only_tx(uow, alice)


async def test_bad_files_are_refused(uow: UowFactory, alice: UserId) -> None:
    bucket = FakeBucket()
    for data, kind in (
        (b"", "image/png"),
        (b"x", "text/html"),
        (b"x" * (10 * 2**20 + 1), "image/png"),
    ):
        with pytest.raises(InvalidInput):
            await receipt_cases.stash(uow(), bucket, alice, data, kind, now=NOW)
    assert bucket.objects == {}
