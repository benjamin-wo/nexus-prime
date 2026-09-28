from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
    OpenIou,
    ShareRequest,
    Source,
    Split,
    Transaction,
    TransactionStatus,
    UserId,
    allocate_repayment,
    apply_snapshot,
    plan_split,
    snapshot,
)
from nexus.domain.money import Money

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def test_equal_split_user_absorbs_remainder() -> None:
    plan = plan_split(sgd("100"), [ShareRequest("Ann"), ShareRequest("Ben")])
    assert plan.own_share == sgd("33.34")
    assert [(s.participant_name, s.share) for s in plan.shares] == [
        ("Ann", sgd("33.33")),
        ("Ben", sgd("33.33")),
    ]


def test_equal_split_without_self() -> None:
    plan = plan_split(sgd("10"), [ShareRequest("Ann"), ShareRequest("Ben")], include_self=False)
    assert plan.own_share == sgd("0")
    assert [s.share for s in plan.shares] == [sgd("5"), sgd("5")]


def test_explicit_shares() -> None:
    plan = plan_split(sgd("50"), [ShareRequest("Ann", sgd("20")), ShareRequest("Ben", sgd("5"))])
    assert plan.own_share == sgd("25")


@pytest.mark.parametrize(
    ("requests", "message"),
    [
        ([], "at least one"),
        ([ShareRequest("Ann"), ShareRequest(" ann ")], "only once"),
        ([ShareRequest("Ann", sgd("5")), ShareRequest("Ben")], "every participant"),
        ([ShareRequest("Ann", sgd("60"))], "more than the bill"),
        ([ShareRequest("Ann", sgd("0"))], "greater than zero"),
        ([ShareRequest("  ")], "empty"),
    ],
)
def test_split_rejects(requests: list[ShareRequest], message: str) -> None:
    with pytest.raises(InvalidInput, match=message):
        plan_split(sgd("50"), requests)


def iou(outstanding: str, days_ago: int, currency: str = "SGD") -> OpenIou:
    split = Split(uuid4(), UserId(uuid4()), uuid4(), "Ann", Money.of(outstanding, currency))
    return OpenIou(split, Money.of(outstanding, currency), NOW - timedelta(days=days_ago))


def test_repayment_pays_oldest_first_and_reports_excess() -> None:
    newer, older = iou("30", 1), iou("20", 5)
    plan = allocate_repayment(sgd("45"), [newer, older])
    assert [(a.split_id, a.amount) for a in plan.allocations] == [
        (older.split.id, sgd("20")),
        (newer.split.id, sgd("25")),
    ]
    assert plan.unallocated == sgd("0")
    assert allocate_repayment(sgd("60"), [newer, older]).unallocated == sgd("10")


def test_repayment_skips_other_currencies() -> None:
    plan = allocate_repayment(sgd("10"), [iou("10", 3, "USD"), iou("10", 1)])
    assert len(plan.allocations) == 1
    assert plan.allocations[0].amount == sgd("10")


def test_snapshot_round_trip() -> None:
    tx = Transaction(
        id=uuid4(),
        user_id=UserId(uuid4()),
        direction=Direction.OUT,
        amount=sgd("12.3456"),
        occurred_at=NOW,
        counterparty="Cafe",
        category_id=uuid4(),
        notes=None,
        status=TransactionStatus.PENDING,
        source=Source.TEXT,
        created_at=NOW,
        updated_at=NOW,
    )
    later = NOW + timedelta(hours=1)
    changed = replace(tx, amount=sgd("1"), counterparty=None, deleted_at=later)
    assert apply_snapshot(changed, snapshot(tx), now=later) == replace(tx, updated_at=later)
