from datetime import UTC, datetime, timedelta

import pytest

from nexus.application.categories import create_category, list_categories, set_category_active
from nexus.application.ports import LedgerQuery, SortField
from nexus.application.splits import split_bill
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
from nexus.application.users import DEFAULT_CATEGORIES, RegisterUser, register_user
from nexus.domain.errors import Conflict, DuplicateSource, InvalidInput, NothingToUndo
from nexus.domain.ledger import (
    Direction,
    RevisionKind,
    ShareRequest,
    Source,
    TransactionStatus,
    UserId,
)
from nexus.domain.money import Money
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 1, 9, tzinfo=UTC)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def spend(amount: str, *, at: datetime = T0, **kwargs: object) -> NewTransaction:
    return NewTransaction(Direction.OUT, sgd(amount), at, **kwargs)  # type: ignore[arg-type]


async def test_register_is_idempotent_and_seeds_categories(uow: UowFactory) -> None:
    first = await register_user(uow(), RegisterUser(telegram_user_id=7, home_currency="sgd"))
    again = await register_user(uow(), RegisterUser(telegram_user_id=7, home_currency="USD"))
    assert first.created and not again.created
    assert again.user == first.user
    assert first.user.home_currency == "SGD"
    names = [c.name for c in await list_categories(uow(), first.user.id)]
    assert sorted(names) == sorted(DEFAULT_CATEGORIES)


async def test_register_rejects_unknown_timezone(uow: UowFactory) -> None:
    with pytest.raises(InvalidInput, match="timezone"):
        await register_user(
            uow(), RegisterUser(telegram_user_id=8, home_currency="SGD", timezone="Mars/Base")
        )


async def test_log_and_read_back_exact_money(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(
        uow(), alice, spend("5.1234", counterparty="  Starbucks ", notes="  ")
    )
    stored = await get_transaction(uow(), alice, tx.id)
    assert stored == tx
    assert stored.amount == Money.of("5.1234", "SGD")
    assert stored.counterparty == "Starbucks"
    assert stored.notes is None


async def test_rejects_naive_datetimes_and_non_positive_amounts(
    uow: UowFactory, alice: UserId
) -> None:
    with pytest.raises(InvalidInput, match="timezone"):
        await log_transaction(uow(), alice, spend("1", at=datetime(2026, 9, 1)))
    with pytest.raises(InvalidInput, match="greater than zero"):
        await log_transaction(uow(), alice, spend("0"))


async def test_duplicate_source_is_refused_even_after_delete(
    uow: UowFactory, alice: UserId
) -> None:
    first = await log_transaction(
        uow(), alice, spend("12", source=Source.EMAIL, external_id="msg-1")
    )
    with pytest.raises(DuplicateSource) as caught:
        await log_transaction(uow(), alice, spend("12", source=Source.EMAIL, external_id="msg-1"))
    assert caught.value.transaction_id == first.id

    await delete_transaction(uow(), alice, first.id)
    with pytest.raises(DuplicateSource):
        await log_transaction(uow(), alice, spend("12", source=Source.EMAIL, external_id="msg-1"))
    # The refused attempt left nothing behind.
    page = await list_ledger(uow(), alice, LedgerQuery(include_deleted=True))
    assert page.total == 1

    # Same id from a different source is a different item.
    await log_transaction(uow(), alice, spend("12", source=Source.IMPORT, external_id="msg-1"))


async def test_archived_category_cannot_be_assigned(uow: UowFactory, alice: UserId) -> None:
    category = await create_category(uow(), alice, "Coffee")
    with pytest.raises(Conflict, match="already exists"):
        await create_category(uow(), alice, "coffee")
    await set_category_active(uow(), alice, category.id, False)
    with pytest.raises(InvalidInput, match="archived"):
        await log_transaction(uow(), alice, spend("3", category_id=category.id))


async def test_edit_then_undo_walks_back(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, spend("10", counterparty="Cafe"))
    edited = await edit_transaction(
        uow(), alice, tx.id, TransactionChanges(amount=sgd("12"), notes="with cake")
    )
    assert edited.amount == sgd("12") and edited.notes == "with cake"
    deleted = await delete_transaction(uow(), alice, tx.id)
    assert deleted.is_deleted

    undone = await undo_last(uow(), alice)
    assert undone.undone is RevisionKind.DELETE
    assert not undone.transaction.is_deleted
    assert undone.transaction.amount == sgd("12")

    undone = await undo_last(uow(), alice)
    assert undone.undone is RevisionKind.EDIT
    assert undone.transaction.amount == sgd("10")
    assert undone.transaction.notes is None

    undone = await undo_last(uow(), alice)
    assert undone.undone is RevisionKind.CREATE
    assert undone.transaction.is_deleted

    with pytest.raises(NothingToUndo):
        await undo_last(uow(), alice)


async def test_noop_edit_records_nothing(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, spend("10", counterparty="Cafe"))
    same = await edit_transaction(uow(), alice, tx.id, TransactionChanges(counterparty="Cafe"))
    assert same == tx
    assert (await undo_last(uow(), alice)).undone is RevisionKind.CREATE


async def test_deleted_transactions_must_be_restored_before_editing(
    uow: UowFactory, alice: UserId
) -> None:
    tx = await log_transaction(uow(), alice, spend("10"))
    await delete_transaction(uow(), alice, tx.id)
    with pytest.raises(InvalidInput, match="restore"):
        await edit_transaction(uow(), alice, tx.id, TransactionChanges(notes="x"))
    restored = await restore_transaction(uow(), alice, tx.id)
    assert not restored.is_deleted
    assert (await undo_last(uow(), alice)).transaction.is_deleted


async def test_edit_respects_splits(uow: UowFactory, alice: UserId) -> None:
    tx = await log_transaction(uow(), alice, spend("30"))
    await split_bill(uow(), alice, tx.id, [ShareRequest("Ann"), ShareRequest("Ben")])
    with pytest.raises(Conflict, match="below"):
        await edit_transaction(uow(), alice, tx.id, TransactionChanges(amount=sgd("19.99")))
    with pytest.raises(Conflict, match="currency"):
        await edit_transaction(
            uow(), alice, tx.id, TransactionChanges(amount=Money.of("30", "USD"))
        )
    with pytest.raises(Conflict, match="money out"):
        await edit_transaction(uow(), alice, tx.id, TransactionChanges(direction=Direction.IN))
    ok = await edit_transaction(uow(), alice, tx.id, TransactionChanges(amount=sgd("20")))
    assert ok.amount == sgd("20")


async def test_ledger_filters_search_sort_and_pages(uow: UowFactory, alice: UserId) -> None:
    food = await create_category(uow(), alice, "Food")
    await log_transaction(uow(), alice, spend("5", at=T0, counterparty="Kopi 100%"))
    await log_transaction(uow(), alice, spend("50", at=T0 + timedelta(days=1), category_id=food.id))
    await log_transaction(
        uow(),
        alice,
        NewTransaction(Direction.IN, sgd("3000"), T0 + timedelta(days=2), counterparty="Salary"),
    )
    gone = await log_transaction(uow(), alice, spend("7", at=T0 + timedelta(days=3)))
    await delete_transaction(uow(), alice, gone.id)

    page = await list_ledger(uow(), alice, LedgerQuery())
    assert page.total == 3
    assert [t.amount for t in page.items] == [sgd("3000"), sgd("50"), sgd("5")]

    outs = await list_ledger(uow(), alice, LedgerQuery(direction=Direction.OUT))
    assert {t.amount for t in outs.items} == {sgd("5"), sgd("50")}

    # LIKE wildcards in the search term are literal.
    found = await list_ledger(uow(), alice, LedgerQuery(search="100%"))
    assert [t.counterparty for t in found.items] == ["Kopi 100%"]
    assert (await list_ledger(uow(), alice, LedgerQuery(search="%"))).total == 1

    by_cat = await list_ledger(uow(), alice, LedgerQuery(category_id=food.id))
    assert [t.amount for t in by_cat.items] == [sgd("50")]
    # Every new transaction gets a category: "Other" or "Income" when nothing decides.
    assert (await list_ledger(uow(), alice, LedgerQuery(uncategorized=True))).total == 0

    ranged = await list_ledger(
        uow(), alice, LedgerQuery(start=T0 + timedelta(days=1), end=T0 + timedelta(days=2))
    )
    assert [t.amount for t in ranged.items] == [sgd("50")]

    cheapest = await list_ledger(
        uow(), alice, LedgerQuery(sort=SortField.AMOUNT, descending=False, limit=1, offset=1)
    )
    assert cheapest.total == 3 and [t.amount for t in cheapest.items] == [sgd("50")]

    deleted = await list_ledger(uow(), alice, LedgerQuery(only_deleted=True))
    assert [t.id for t in deleted.items] == [gone.id]

    with pytest.raises(InvalidInput):
        await list_ledger(uow(), alice, LedgerQuery(limit=0))
    with pytest.raises(InvalidInput):
        await list_ledger(uow(), alice, LedgerQuery(start=T0, end=T0))


async def test_summary_counts_confirmed_live_money_per_currency(
    uow: UowFactory, alice: UserId
) -> None:
    food = await create_category(uow(), alice, "Food")
    await log_transaction(uow(), alice, spend("10", category_id=food.id))
    await log_transaction(uow(), alice, spend("5.50", category_id=food.id))
    await log_transaction(uow(), alice, spend("2"))
    await log_transaction(uow(), alice, NewTransaction(Direction.OUT, Money.of("20", "USD"), T0))
    await log_transaction(uow(), alice, NewTransaction(Direction.IN, sgd("100"), T0))
    await log_transaction(uow(), alice, spend("99", status=TransactionStatus.PENDING))
    gone = await log_transaction(uow(), alice, spend("1000"))
    await delete_transaction(uow(), alice, gone.id)
    await log_transaction(uow(), alice, spend("500", at=T0 + timedelta(days=40)))

    summary = await summarize(uow(), alice, T0, T0 + timedelta(days=30))
    assert {(t.direction, t.total, t.count) for t in summary.totals} == {
        (Direction.IN, sgd("100"), 1),
        (Direction.OUT, sgd("17.50"), 3),
        (Direction.OUT, Money.of("20", "USD"), 1),
    }
    assert [(c.category_name, c.total) for c in summary.spending_by_category] == [
        ("Food", sgd("15.50")),
        ("Other", sgd("2")),
        ("Other", Money.of("20", "USD")),
    ]
