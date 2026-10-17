"""Telling which wallet a line of text is about: whole words and phrases in any case, the
longest phrase wins, a tie is ambiguous, and Spending never matches. Made-up wallets."""

from uuid import uuid4

import pytest

from nexus.domain.ledger import UserId, Wallet, WalletKind
from nexus.domain.wallets import match_wallet, wallet_for

USER = UserId(uuid4())


def wallet(name: str, kind: WalletKind, *words: str) -> Wallet:
    return Wallet(uuid4(), USER, name, kind, words)


SPENDING = wallet("Spending", WalletKind.SPENDING, "everyday")
IBKR = wallet("IBKR", WalletKind.INVESTMENT, "ibkr", "interactive brokers")
CARD = wallet("Card", WalletKind.CARD, "card payment")
SAVINGS = wallet("Savings", WalletKind.SAVINGS, "savings", "fixed deposit")
ALL = [SPENDING, IBKR, CARD, SAVINGS]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("IBKR top-up", IBKR),
        ("ibkr", IBKR),
        ("Funds to IBKR*TOPUP", IBKR),  # punctuation ends a word
        ("INTERACTIVE   BROKERS LLC", IBKR),  # phrases, any case, any spacing
        ("Card Payment 1234", CARD),
        ("fixed deposit placement", SAVINGS),
    ],
)
def test_whole_words_and_phrases_match_in_any_case(text: str, expected: Wallet) -> None:
    assert wallet_for([text], ALL) == expected


@pytest.mark.parametrize(
    "text",
    ["fibkro", "ibkrs", "xibkr", "interactive", "brokers interactive", "cardpayment", "payment"],
)
def test_parts_of_words_and_other_word_orders_do_not(text: str) -> None:
    assert wallet_for([text], ALL) is None


def test_it_reports_the_word_that_matched() -> None:
    found = match_wallet(["wire to Interactive Brokers"], ALL)
    assert found is not None and (found.wallet, found.word) == (IBKR, "interactive brokers")


def test_either_part_can_match_and_missing_parts_are_ignored() -> None:
    assert wallet_for([None, "", "ibkr"], ALL) == IBKR
    assert wallet_for(["Wire", "to my IBKR account"], ALL) == IBKR
    assert wallet_for([None, ""], ALL) is None
    assert wallet_for([], ALL) is None


def test_the_longest_matching_phrase_wins() -> None:
    other = wallet("Brokerage", WalletKind.INVESTMENT, "interactive brokers sg")
    assert wallet_for(["Interactive Brokers SG fee"], [IBKR, other]) == other
    assert wallet_for(["Interactive Brokers fee"], [IBKR, other]) == IBKR
    # The longest word that matched counts, not the longest word a wallet has.
    wordy = wallet("Wordy", WalletKind.OTHER, "ibkr", "a very long phrase nobody writes")
    assert wallet_for(["IBKR and savings"], [wordy, SAVINGS]) == SAVINGS


def test_a_tie_between_two_wallets_matches_nothing() -> None:
    twin = wallet("Brokerage", WalletKind.INVESTMENT, "IBKR")
    assert wallet_for(["IBKR top-up"], [IBKR, twin]) is None
    # One wallet matching by several words is still one wallet.
    assert wallet_for(["ibkr, Interactive Brokers"], ALL) == IBKR


def test_spending_never_matches() -> None:
    assert wallet_for(["everyday spending"], ALL) is None
    assert wallet_for(["everyday spending"], [SPENDING]) is None
    assert wallet_for(["everyday ibkr"], ALL) == IBKR


def test_a_wallet_without_words_never_matches() -> None:
    assert wallet_for(["Emergency fund"], [wallet("Emergency fund", WalletKind.SAVINGS)]) is None
