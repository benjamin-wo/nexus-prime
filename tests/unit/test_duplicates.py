"""When two records look like one payment. Every name here is made up."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from nexus.domain.duplicates import (
    Candidate,
    Valuer,
    better_name,
    likely_same,
    pair_key,
    same_merchant,
)
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


# --- one payment in two currencies --------------------------------------------------------


def rates(**per_unit: str) -> Valuer:
    """Home (SGD) value of a currency, by its rate: ``rates(EUR="1.48")``."""

    def value(amount: Money, day: date) -> Money | None:
        if amount.currency == "SGD":
            return amount
        if amount.currency not in per_unit:
            return None
        converted = amount.amount * Decimal(per_unit[amount.currency])
        return Money(converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "SGD")

    return value


def abroad(
    merchant: str | None,
    amount: str = "14.00",
    currency: str = "EUR",
    *,
    source: Source = Source.EMAIL,
    kind: str | None = "Payment confirmation",
    at: datetime = AT,
) -> Candidate:
    return Candidate(Direction.OUT, Money(Decimal(amount), currency), at, merchant, source, kind)


def test_euros_and_the_cards_conversion_are_one_payment() -> None:
    shop = abroad("Acme Hire")
    card = pay("Acme Hire Pte Ltd", "20.67", at=AT + timedelta(hours=3))  # 14 x 1.48 = 20.72
    assert likely_same(shop, card, SG, value=rates(EUR="1.48"))
    assert likely_same(card, shop, SG, value=rates(EUR="1.48"))  # whichever way round
    ledger_row = pay("ACME HIRE", "20.67", source=Source.MANUAL, kind=None)
    assert likely_same(shop, ledger_row, SG, value=rates(EUR="1.48"))


def test_two_foreign_currencies_are_compared_in_the_home_currency() -> None:
    euros = abroad("Acme Hire", "14.00", "EUR")
    pounds = abroad("Acme Hire", "12.00", "GBP", kind="Receipt")
    assert likely_same(euros, pounds, SG, value=rates(EUR="1.48", GBP="1.72"))  # 20.72 v 20.64
    assert not likely_same(euros, pounds, SG, value=rates(EUR="1.48", GBP="1.40"))


def test_the_three_percent_edge() -> None:
    """100 EUR at 1.5 is 150 SGD; the gap may be 3% of the bigger amount."""
    shop, value = abroad("Acme Hire", "100.00"), rates(EUR="1.5")

    def card(amount: str) -> Candidate:
        return pay("Acme Hire", amount, kind="x")

    assert likely_same(shop, card("145.50"), SG, value=value)
    assert not likely_same(shop, card("145.40"), SG, value=value)
    assert likely_same(shop, card("154.60"), SG, value=value)
    assert not likely_same(shop, card("154.70"), SG, value=value)
    assert not likely_same(shop, card("150.00"), SG, value=rates(EUR="1.6"))  # a 6% rate gap


def test_what_is_not_one_payment_across_currencies() -> None:
    shop, card = abroad("Acme Hire"), pay("Acme Hire", "20.67")
    value = rates(EUR="1.48")
    assert likely_same(shop, card, SG, value=value)
    # 10% apart
    assert not likely_same(shop, pay("Acme Hire", "22.80"), SG, value=value)
    # an unnamed side (allowed within one currency, not across two)
    assert not likely_same(shop, pay(None, "20.67"), SG, value=value)
    assert not likely_same(abroad(None), card, SG, value=value)
    assert not likely_same(abroad("Toll"), pay("Parking", "20.67"), SG, value=value)
    # different merchants
    assert not likely_same(shop, pay("Zeta Taxis", "20.67"), SG, value=value)
    # no rate, or nothing to convert with
    assert not likely_same(shop, card, SG, value=rates())
    assert not likely_same(shop, card, SG)
    # another day, the other direction, or two records of the same kind
    assert not likely_same(
        shop, pay("Acme Hire", "20.67", at=AT + timedelta(days=2)), SG, value=value
    )
    refund = pay("Acme Hire", "20.67", direction=Direction.IN)
    assert not likely_same(shop, refund, SG, value=value)
    assert not likely_same(
        shop, abroad("Acme Hire", "14.10", kind="payment confirmation"), SG, value=value
    )
    other_alert = pay("Acme Hire", "20.67", kind="Payment confirmation")
    assert not likely_same(shop, other_alert, SG, value=value)  # both emails, same subject


def test_the_same_currency_is_judged_as_before() -> None:
    value = rates(EUR="1.48")
    assert likely_same(pay("Grab* A-7KXP"), pay("Grab Singapore", kind="Receipt"), SG, value=value)
    assert likely_same(pay(None), pay("Grab", kind="Receipt"), SG, value=value)  # unnamed is fine
    assert not likely_same(pay("Grab"), pay("Grab", "23.41", kind="Receipt"), SG, value=value)
    # near amounts in one currency are still two payments, whatever the tolerance
    assert not likely_same(abroad("Acme"), abroad("Acme", "14.10", kind="Receipt"), SG, value=value)
