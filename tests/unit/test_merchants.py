"""Suggestions for who an expense was paid to, from past entries. Every name and
figure here is made up."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from nexus.domain.ledger import Direction, Source, Transaction, TransactionStatus, UserId
from nexus.domain.merchants import merchant_key, suggest
from nexus.domain.money import Money

USER = UserId(uuid4())
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
FOOD, TRANSPORT = uuid4(), uuid4()


def tx(name: str, amount: str, days_ago: int, category: UUID | None = None) -> Transaction:
    at = NOW - timedelta(days=days_ago)
    return Transaction(
        id=uuid4(), user_id=USER, direction=Direction.OUT, amount=Money.of(amount, "SGD"),
        occurred_at=at, counterparty=name, category_id=category, notes=None,
        status=TransactionStatus.CONFIRMED, source=Source.MANUAL, created_at=at, updated_at=at,
    )  # fmt: skip


ENTRIES = sorted(
    [
        tx("Foodcourt ABC", "6.50", 1, FOOD),
        tx("foodcourt  abc", "6.50", 2, FOOD),
        tx("FOODCOURT-ABC", "7.20", 3, None),
        tx("Grab", "12.00", 1, TRANSPORT),
        tx("Grab", "15.00", 5, TRANSPORT),
        tx("Abc Bakery", "4.00", 9, FOOD),
        tx("Cafe Foodie", "5.00", 0, FOOD),
    ],
    key=lambda t: t.occurred_at,
    reverse=True,
)


def test_one_merchant_however_it_is_typed() -> None:
    assert merchant_key("Foodcourt ABC") == merchant_key(" foodcourt  abc") == "foodcourt abc"
    assert merchant_key("FOODCOURT-ABC") == "foodcourt abc"


def test_with_nothing_typed_the_most_used_come_first() -> None:
    names = [s.name for s in suggest(ENTRIES, "")]
    assert names[:2] == ["Foodcourt ABC", "Grab"]
    top = suggest(ENTRIES, "")[0]
    assert top.times == 3 and top.category_id == FOOD
    assert top.amount == Money.of("6.50", "SGD")  # the usual, not the odd 7.20


def test_names_starting_with_the_text_come_before_ones_containing_it() -> None:
    assert [s.name for s in suggest(ENTRIES, "foo")] == ["Foodcourt ABC", "Cafe Foodie"]
    assert [s.name for s in suggest(ENTRIES, "abc")] == ["Abc Bakery", "Foodcourt ABC"]
    assert [s.name for s in suggest(ENTRIES, "court")] == ["Foodcourt ABC"]
    assert suggest(ENTRIES, "zzz") == []


def test_a_name_typed_in_full_is_not_suggested_again() -> None:
    assert [s.name for s in suggest(ENTRIES, "grab")] == []
    assert [s.name for s in suggest(ENTRIES, "gra")] == ["Grab"]


def test_the_latest_amount_when_none_repeats() -> None:
    grab = suggest(ENTRIES, "gr")[0]
    assert grab.amount == Money.of("12.00", "SGD") and grab.last == NOW - timedelta(days=1)
