"""Every read and write is scoped to the acting user.

Another user's data behaves exactly as if it did not exist.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.categories import (
    create_category,
    list_categories,
    rename_category,
    set_category_active,
)
from nexus.application.ports import LedgerQuery
from nexus.application.splits import list_open_ious, settle_iou, split_bill
from nexus.application.transactions import (
    NewTransaction,
    TransactionChanges,
    delete_transaction,
    edit_transaction,
    get_transaction,
    list_ledger,
    log_transaction,
    restore_transaction,
    summarize,
    undo_last,
)
from nexus.domain.errors import NotFound, NothingToUndo
from nexus.domain.ledger import Direction, ShareRequest, Source, UserId
from nexus.domain.money import Money
from nexus.infra.db.tables import transactions
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 1, tzinfo=UTC)
SPEND = NewTransaction(Direction.OUT, Money.of("40", "SGD"), T0)


async def test_other_users_transactions_do_not_exist(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    tx = await log_transaction(uow(), alice, SPEND)
    for attempt in (
        get_transaction(uow(), bob, tx.id),
        edit_transaction(uow(), bob, tx.id, TransactionChanges(notes="mine now")),
        delete_transaction(uow(), bob, tx.id),
        restore_transaction(uow(), bob, tx.id),
        split_bill(uow(), bob, tx.id, [ShareRequest("Ann")]),
    ):
        with pytest.raises(NotFound):
            await attempt
    assert (await list_ledger(uow(), bob, LedgerQuery(include_deleted=True))).total == 0
    assert (await summarize(uow(), bob, T0, datetime(2027, 1, 1, tzinfo=UTC))).totals == []
    assert await get_transaction(uow(), alice, tx.id) == tx


async def test_undo_only_touches_own_writes(uow: UowFactory, alice: UserId, bob: UserId) -> None:
    tx = await log_transaction(uow(), alice, SPEND)
    with pytest.raises(NothingToUndo):
        await undo_last(uow(), bob)
    assert not (await get_transaction(uow(), alice, tx.id)).is_deleted


async def test_other_users_categories_do_not_exist(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    category = await create_category(uow(), alice, "Private")
    with pytest.raises(NotFound):
        await log_transaction(
            uow(),
            bob,
            NewTransaction(Direction.OUT, Money.of("1", "SGD"), T0, category_id=category.id),
        )
    with pytest.raises(NotFound):
        await rename_category(uow(), bob, category.id, "Stolen")
    with pytest.raises(NotFound):
        await set_category_active(uow(), bob, category.id, False)
    assert "Private" not in [c.name for c in await list_categories(uow(), bob)]
    # Names are unique per user, not globally.
    await create_category(uow(), bob, "Private")


async def test_ious_are_private(uow: UowFactory, alice: UserId, bob: UserId) -> None:
    tx = await log_transaction(uow(), alice, SPEND)
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann")])
    assert await list_open_ious(uow(), bob) == []
    with pytest.raises(Exception, match="no open IOU"):
        await settle_iou(uow(), bob, "Ann", Money.of("20", "SGD"), T0)
    assert len(await list_open_ious(uow(), alice)) == 1


async def test_source_ids_are_per_user(uow: UowFactory, alice: UserId, bob: UserId) -> None:
    item = NewTransaction(
        Direction.OUT, Money.of("5", "SGD"), T0, source=Source.EMAIL, external_id="shared-id"
    )
    await log_transaction(uow(), alice, item)
    await log_transaction(uow(), bob, item)


async def test_database_rejects_cross_tenant_links(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    """Even a buggy query can't attach Bob's row to Alice's category."""
    category = await create_category(uow(), alice, "Private")
    async with engine.begin() as conn:
        with pytest.raises(IntegrityError, match="fk_transactions_category_id_user_id"):
            await conn.execute(
                insert(transactions).values(
                    id=uuid4(),
                    user_id=bob,
                    direction="out",
                    amount=1,
                    currency="SGD",
                    occurred_at=T0,
                    category_id=category.id,
                    status="confirmed",
                    source="manual",
                    created_at=T0,
                    updated_at=T0,
                )
            )
