"""When two records look like one payment. Every name here is made up."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from nexus.domain.duplicates import Candidate, better_name, likely_same, pair_key, same_merchant
from nexus.domain.ledger import Direction, Source
from nexus.domain.money import Money

SG = ZoneInfo("Asia/Singapore")
AT = datetime(2026, 10, 3, 1, 0, tzinfo=UTC)


def pay(
    merchant: str | None,
    amount: str = "23.40",
    *,
    at: datetime = AT,
    source: Source = Source.EMAIL,
    kind: str | None = "Card alert",
    direction: Direction = Direction.OUT,
) -> Candidate:
    return Candidate(direction, Money(Decimal(amount), "SGD"), at, merchant, source, kind)


def test_merchants_match_however_the_bank_writes_them() -> None:
    assert same_merchant("Grab* A-7KXPLMQZRTWB", "Grab Singapore")
    assert same_merchant("GRB*Kopi Corner Bedok", "Kopi Corner")
    assert same_merchant("Lucky Vending Pte Ltd", None)  # one side has no name
    assert not same_merchant("Grab Singapore", "Gojek Singapore")
    assert not same_merchant("Kopi Pte Ltd", "Toast Pte Ltd")


def test_a_card_alert_and_a_receipt_are_one_payment() -> None:
    alert = pay("Grab* A-7KXPLMQZRTWB")
    receipt = pay("Grab Singapore", kind="Your Grab e-receipt", at=AT + timedelta(hours=2))
    assert likely_same(alert, receipt, SG)
    typed = pay("grab", source=Source.TEXT, kind=None)
    assert likely_same(typed, receipt, SG)


def test_what_isnt_one_payment() -> None:
    alert = pay("Grab* A-7KXP")
    assert not likely_same(alert, pay("Grab Singapore", "23.50", kind="Receipt"), SG)
    assert not likely_same(alert, pay("Grab", kind="Receipt", at=AT + timedelta(days=2)), SG)
    refund = pay("Grab", kind="Receipt", direction=Direction.IN)
    assert not likely_same(alert, refund, SG)
    # Two alerts of the same kind are two rides; so are two statement lines.
    assert not likely_same(alert, pay("Grab* B-77XQ", at=AT + timedelta(hours=1)), SG)
    line = pay("BUS/MRT", "1.95", source=Source.IMPORT, kind=None)
    assert not likely_same(line, line, SG)
    kopi = pay("Kopi", "1.80", source=Source.TEXT, kind=None)
    assert not likely_same(kopi, kopi, SG)  # a second kopi the user logged


def test_the_readable_name_wins() -> None:
    assert better_name("Grab* A-7KXPLMQZRTWB", "Grab Singapore") == "Grab Singapore"
    assert better_name("Grab Singapore", "Grab* A-7KXPLMQZRTWB") == "Grab Singapore"
    assert better_name(None, "Kopi Corner") == "Kopi Corner"
    assert better_name("Kopi", "Kopi") == "Kopi"


def test_a_pair_has_one_key_either_way_round() -> None:
    assert pair_key("b", "a") == pair_key("a", "b") == ("a", "b")
