from datetime import UTC, datetime, timedelta

import pytest

from nexus.application.splits import list_open_ious, settle_iou, split_bill
from nexus.application.transactions import (
    NewTransaction,
    delete_transaction,
    log_transaction,
    undo_last,
)
from nexus.domain.errors import Conflict, InvalidInput
from nexus.domain.ledger import Direction, RevisionKind, ShareRequest, Source, UserId
from nexus.domain.money import Money
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 1, 19, tzinfo=UTC)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def bill(uow: UowFactory, user: UserId, amount: str, days: int = 0) -> NewTransaction:
    return NewTransaction(Direction.OUT, sgd(amount), T0 + timedelta(days=days))


async def outstanding(uow: UowFactory, user: UserId, name: str | None = None) -> list[Money]:
    return [iou.outstanding for iou in await list_open_ious(uow(), user, participant_name=name)]


async def test_equal_split_creates_ious(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, await bill(uow, alice, "100"))
    result = await split_bill(uow(), alice, tx.id, [ShareRequest("Ann"), ShareRequest("Ben")])
    assert result.own_share == sgd("33.34")
    assert [(s.participant_name, s.share) for s in result.splits] == [
        ("Ann", sgd("33.33")),
        ("Ben", sgd("33.33")),
    ]
    assert await outstanding(uow, alice, "ann") == [sgd("33.33")]


async def test_only_live_money_out_can_be_split(uow: UowFactory, alice: UserId) -> None:
    income = await log_transaction(uow(), alice, NewTransaction(Direction.IN, sgd("10"), T0))
    with pytest.raises(InvalidInput, match="money out"):
        await split_bill(uow(), alice, income.id, [ShareRequest("Ann")])
    tx = await log_transaction(uow(), alice, await bill(uow, alice, "10"))
    await delete_transaction(uow(), alice, tx.id)
    with pytest.raises(InvalidInput, match="restore"):
        await split_bill(uow(), alice, tx.id, [ShareRequest("Ann")])


async def test_resplit_replaces_and_undo_restores_previous(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, await bill(uow, alice, "60"))
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann"), ShareRequest("Ben")])
    await split_bill(uow(), alice, tx.id, [ShareRequest("Cat", sgd("15"))])
    assert [i.split.participant_name for i in await list_open_ious(uow(), alice)] == ["Cat"]

    assert (await undo_last(uow(), alice)).undone is RevisionKind.SPLIT
    ious = await list_open_ious(uow(), alice)
    assert sorted((i.split.participant_name, i.outstanding) for i in ious) == [
        ("Ann", sgd("20")),
        ("Ben", sgd("20")),
    ]
    await undo_last(uow(), alice)
    assert await list_open_ious(uow(), alice) == []


async def test_repayment_settles_oldest_first(uow: UowFactory, alice: UserId) -> None:
    first = await log_transaction(uow(), alice, await bill(uow, alice, "40", days=0))
    second = await log_transaction(uow(), alice, await bill(uow, alice, "30", days=1))
    await split_bill(uow(), alice, first.id, [ShareRequest("Ann")])  # Ann owes 20
    await split_bill(uow(), alice, second.id, [ShareRequest("Ann")])  # Ann owes 15

    result = await settle_iou(uow(), alice, "ANN", sgd("25"), T0 + timedelta(days=2))
    assert result.transaction.direction is Direction.IN
    assert result.transaction.counterparty == "Ann"
    assert [s.amount for s in result.settlements] == [sgd("20"), sgd("5")]
    assert result.unallocated == sgd("0")
    assert await outstanding(uow, alice, "Ann") == [sgd("10")]

    extra = await settle_iou(uow(), alice, "Ann", sgd("12"), T0 + timedelta(days=3))
    assert extra.unallocated == sgd("2")
    assert await outstanding(uow, alice, "Ann") == []

    with pytest.raises(InvalidInput, match="no open IOU"):
        await settle_iou(uow(), alice, "Ann", sgd("1"), T0)


async def test_undoing_a_repayment_reopens_the_iou(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, await bill(uow, alice, "20"))
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann")])
    await settle_iou(uow(), alice, "Ann", sgd("10"), T0, source=Source.TEXT, external_id="tg-55")
    assert await outstanding(uow, alice) == []
    assert (await undo_last(uow(), alice)).undone is RevisionKind.CREATE
    assert await outstanding(uow, alice) == [sgd("10")]
    # A split with recorded repayments can't be changed or undone any more.
    with pytest.raises(Conflict, match="repayments"):
        await split_bill(uow(), alice, tx.id, [ShareRequest("Ben")])
    with pytest.raises(Conflict, match="repayments"):
        await undo_last(uow(), alice)


async def test_deleting_the_bill_cancels_its_ious(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, await bill(uow, alice, "20"))
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann")])
    await delete_transaction(uow(), alice, tx.id)
    assert await outstanding(uow, alice) == []
    await undo_last(uow(), alice)
    assert await outstanding(uow, alice) == [sgd("10")]


async def test_repayment_currency_must_match(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, await bill(uow, alice, "20"))
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann")])
    with pytest.raises(InvalidInput, match="USD"):
        await settle_iou(uow(), alice, "Ann", Money.of("10", "USD"), T0)
