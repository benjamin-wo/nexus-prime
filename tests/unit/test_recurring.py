from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.planning import Cadence
from nexus.domain.recurring import (
    Charge,
    Subscription,
    SubscriptionStatus,
    cadence_of,
    display_name,
    find_recurring,
    merchant_key,
    monthly_cost,
    next_charge,
    price_changed,
)

TODAY = date(2026, 9, 29)


def charge(day: date, amount: str, merchant: str = "Netflix", currency: str = "SGD") -> Charge:
    return Charge(uuid4(), day, Money.of(amount, currency), merchant)


def monthly(
    merchant: str = "Netflix", *amounts: str, last: date = date(2026, 9, 12)
) -> list[Charge]:
    amounts = amounts or ("15.98", "15.98", "15.98")
    days = [date(last.year, last.month - i, last.day) for i in range(len(amounts))][::-1]
    return [charge(d, a, merchant) for d, a in zip(days, amounts, strict=True)]


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("NETFLIX.COM 8829", "netflix.com"),
        ("Netflix.com", "netflix.com"),
        ("  Spotify   P1234 ", "spotify p"),
        ("7-Eleven", "7-eleven"),
        ("123", None),
        (None, None),
    ],
)
def test_merchants_match_without_reference_numbers(text: str | None, key: str | None) -> None:
    assert merchant_key(text) == key


def test_display_names_drop_reference_numbers() -> None:
    assert display_name("Netflix.com 8829") == "Netflix.com"
    assert display_name("GRAB *RIDE 1234") == "GRAB RIDE"
    assert display_name("7-Eleven") == "7-Eleven"
    assert display_name("123") == "123"


def test_schedules_are_recognised_from_the_gaps() -> None:
    assert cadence_of([date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15)]) is Cadence.WEEKLY
    assert cadence_of([date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)]) is Cadence.MONTHLY
    assert cadence_of([date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]) is Cadence.MONTHLY
    assert cadence_of([date(2024, 3, 1), date(2025, 3, 1), date(2026, 3, 1)]) is Cadence.YEARLY
    assert cadence_of([date(2026, 9, 1), date(2026, 9, 8), date(2026, 10, 8)]) is None


def test_three_regular_similar_charges_are_proposed() -> None:
    [found] = find_recurring(monthly(), TODAY)
    assert (found.key, found.cadence, found.amount) == (
        "netflix",
        Cadence.MONTHLY,
        Money.of("15.98", "SGD"),
    )
    assert found.last_day == date(2026, 9, 12) and len(found.transaction_ids) == 3


def test_what_isnt_a_subscription() -> None:
    assert find_recurring(monthly()[:2], TODAY) == []  # only two so far
    assert find_recurring(monthly("Netflix", "15.98", "40.00", "15.98"), TODAY) == []  # too varied
    stopped = monthly(last=date(2026, 7, 12))
    assert find_recurring(stopped, TODAY) == []  # no charge since July
    kopi = [charge(TODAY - timedelta(days=d), "4.50", "Kopi") for d in (0, 1, 3, 4)]
    assert find_recurring(kopi, TODAY) == []  # often, but not on a schedule


def test_a_price_rise_within_bounds_still_counts_and_currencies_stay_apart() -> None:
    [found] = find_recurring(monthly("Netflix", "15.98", "15.98", "17.98"), TODAY)
    assert found.amount == Money.of("17.98", "SGD")
    usd = [charge(c.day, "10", "OpenRouter", "USD") for c in monthly()]
    sgd = [charge(c.day, "13", "OpenRouter") for c in monthly()]
    assert {f.amount.currency for f in find_recurring(usd + sgd, TODAY)} == {"USD", "SGD"}


def test_two_charges_on_one_day_count_once() -> None:
    charges = monthly()
    charges.append(charge(charges[-1].day, "15.98"))
    assert len(find_recurring(charges, TODAY)) == 1


def subscription(amount: str = "15.98", cadence: Cadence = Cadence.MONTHLY) -> Subscription:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    return Subscription(
        uuid4(),
        UserId(uuid4()),
        "netflix",
        "Netflix",
        cadence,
        Money.of(amount, "SGD"),
        date(2026, 9, 12),
        SubscriptionStatus.ACTIVE,
        now,
        now,
    )


def test_price_changes_and_monthly_cost() -> None:
    sub = subscription()
    assert price_changed(sub, Money.of("17.98", "SGD"))
    assert not price_changed(sub, Money.of("16.00", "SGD"))  # within 1%: rounding, not a change
    assert not price_changed(sub, Money.of("20", "USD"))
    assert monthly_cost(subscription("12", Cadence.WEEKLY)) == Money.of("52.00", "SGD")
    assert monthly_cost(subscription("120", Cadence.YEARLY)) == Money.of("10.00", "SGD")
    assert next_charge(Cadence.MONTHLY, date(2026, 1, 31)) == date(2026, 2, 28)
