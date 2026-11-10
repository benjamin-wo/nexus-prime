"""Card details and picking the card someone means: pure rules, no database. Every name and
digit is made up."""

import time
from typing import Any
from uuid import uuid4

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId, Wallet, WalletKind
from nexus.domain.wallets import card_last4_in, clean_last4, paying_candidates


def test_last_four_digits_are_cut_and_anything_but_digits_is_refused() -> None:
    assert clean_last4(None).digits is None and clean_last4("  ").digits is None
    assert (clean_last4("1234").digits, clean_last4("1234").longer) == ("1234", False)
    long = clean_last4("4111-1111-1111-1234")
    assert (long.digits, long.longer) == ("1234", True)
    with pytest.raises(InvalidInput, match="numbers only"):
        clean_last4("12a4")
    with pytest.raises(InvalidInput, match="last 4"):
        clean_last4("12")


@pytest.mark.parametrize(
    ("text", "last4"),
    [
        ("Your card ending 1234 was charged SGD 5.00", "1234"),
        ("Card ending in 4321 used at GRAB", "4321"),
        ("Visa credit card ending with 8765.", "8765"),
        ("Paid with card: xxxx-1234", "1234"),
        ("Card: **** **** **** 4321", "4321"),
        ("Charged to *8765 today", "8765"),
        ("Card number 1357 2468 1357 1234 was used", "1234"),
        ("card ending 1234 ... card ending 1234", "1234"),
        ("card ending 1234 and also card ending 4321", None),  # two cards: unclear
        ("Order 1234567 total 12.00", None),
        ("Your bank account ending 1234", None),  # an account, not a card
        ("Call us on 6123 4567", None),
        ("", None),
    ],
)
def test_the_last_four_digits_are_found_in_what_an_email_says(text: str, last4: str | None) -> None:
    assert card_last4_in(text) == last4


def wallet(name: str, kind: WalletKind = WalletKind.CARD, **extra: Any) -> Wallet:
    return Wallet(uuid4(), UserId(uuid4()), name, kind, **extra)


def test_a_card_is_found_by_name_issuer_product_or_last_four_and_only_if_unique() -> None:
    citi = wallet("Citi PremierMiles", issuer="Citi", product="PremierMiles", last4="4321")
    dbs = wallet("DBS Altitude", issuer="DBS", product="Altitude", last4="8765")
    rewards = wallet("Citi Rewards", issuer="Citi", product="Rewards", last4="1111")
    spending = wallet("Main account", WalletKind.SPENDING)
    cash = wallet("Cash", WalletKind.CASH)
    saver = wallet("Citi Savings", WalletKind.SAVINGS)
    every = [citi, dbs, rewards, spending, cash, saver]

    def pick(text: str) -> list[str]:
        return [w.name for w in paying_candidates(every, text)]

    assert pick("dbs") == ["DBS Altitude"]
    assert pick("MY DBS CARD") == ["DBS Altitude"]
    assert pick("altitude") == ["DBS Altitude"]
    assert pick("premiermiles") == ["Citi PremierMiles"]
    assert pick("premier miles") == ["Citi PremierMiles"]
    assert pick("citi premiermiles") == ["Citi PremierMiles"]
    assert pick("ending 4321") == ["Citi PremierMiles"]
    assert pick("4321") == ["Citi PremierMiles"]
    assert pick("the card ending in 8765") == ["DBS Altitude"]
    assert pick("citi 1111") == ["Citi Rewards"]
    assert pick("cash") == ["Cash"] and pick("my main account") == ["Main account"]
    assert sorted(pick("citi")) == ["Citi PremierMiles", "Citi Rewards"]  # ambiguous
    assert pick("amex") == [] and pick("my card") == [] and pick("") == []
    assert pick("savings") == []  # a savings wallet can't pay
    assert pick("citi 9999") == []


@pytest.mark.parametrize(
    "text", ["*" * 20_000 + "a", "x" * 20_000 + "!", "•" * 20_000, "** " * 5_000]
)
def test_a_long_divider_line_is_read_at_once(text: str) -> None:
    # A row of stars in an email once backtracked for hours and froze the app.
    started = time.perf_counter()
    assert card_last4_in(text) is None
    assert time.perf_counter() - started < 2
