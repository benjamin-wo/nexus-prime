"""Which bank a sender is, and picking the card that bank's alert means. Pure rules, no
database. Every name and digit is made up."""

from uuid import uuid4

import pytest

from nexus.domain.banks import issuer_from_sender, sender_domain
from nexus.domain.ledger import UserId, Wallet, WalletKind
from nexus.domain.wallets import card_with_last4, cards_with_last4


@pytest.mark.parametrize(
    ("sender", "bank"),
    [
        ("alerts@uobgroup.com", "UOB"),
        ("alerts@uob.com.sg", "UOB"),
        ("ibanking.alert@dbs.com", "DBS"),
        ("alerts@dbs.com.sg", "DBS"),
        ("alerts@posb.com.sg", "POSB"),
        ("citialerts@citibank.com.sg", "Citi"),
        ("alerts@citi.com", "Citi"),
        ("alerts@ocbc.com", "OCBC"),
        ("alerts@hsbc.com.sg", "HSBC"),
        ("alerts@hsbc.com", "HSBC"),
        ("alerts@sc.com", "Standard Chartered"),
        ("alerts@americanexpress.com", "American Express"),
        ("alerts@aexp.com", "American Express"),
        ("alerts@maybank.com.sg", "Maybank"),
        ("alerts@maybank2u.com", "Maybank"),
        ("alerts@trustbank.sg", "Trust"),
    ],
)
def test_every_listed_domain_names_its_bank(sender: str, bank: str) -> None:
    assert issuer_from_sender(sender) == bank


def test_a_subdomain_counts_and_case_and_display_names_do_not_matter() -> None:
    assert issuer_from_sender("noreply@alerts.uob.com.sg") == "UOB"
    assert issuer_from_sender("a@mail.eu.americanexpress.com") == "American Express"
    assert issuer_from_sender("ALERTS@DBS.COM.SG") == "DBS"
    assert issuer_from_sender("UOB Alerts <alerts@uob.com.sg>") == "UOB"
    assert issuer_from_sender("alerts@uob.com.sg.") == "UOB"
    assert sender_domain("UOB Alerts <Alerts@Uob.com.sg>") == "uob.com.sg"


@pytest.mark.parametrize(
    "sender",
    [
        "alerts@notuob.com.sg",  # a longer name is not a subdomain
        "alerts@uob.com.sg.example.com",  # the bank's name inside someone else's domain
        "alerts@example.com/uob.com.sg",
        "alerts@osc.com",  # ends the same as sc.com, but is not a subdomain of it
        "alerts@citi.org",
        "uob.com.sg",  # no address at all
        "no-reply@grab.com",
        "",
    ],
)
def test_lookalikes_and_other_senders_are_not_a_bank(sender: str) -> None:
    assert issuer_from_sender(sender) is None


def card(name: str, last4: str | None, issuer: str | None = None) -> Wallet:
    return Wallet(uuid4(), UserId(uuid4()), name, WalletKind.CARD, last4=last4, issuer=issuer)


def test_one_card_with_the_digits_is_the_card_whatever_its_issuer() -> None:
    only = card("Travel", "1234", "Citi")
    others = [card("Other", "4321", "UOB"), Wallet(uuid4(), only.user_id, "Cash", WalletKind.CASH)]
    assert card_with_last4([only, *others], "1234") is only
    assert card_with_last4([only, *others], "1234", "UOB") is only  # disambiguation only
    assert card_with_last4([only, *others], "9999", "Citi") is None


def test_several_cards_with_the_digits_are_told_apart_by_issuer_in_any_case() -> None:
    uob, citi, bare = card("A", "1234", "UOB"), card("B", "1234", "Citi"), card("C", "1234")
    cards = [uob, citi, bare]
    assert card_with_last4(cards, "1234") is None  # nothing says which
    assert card_with_last4(cards, "1234", "uob") is uob
    assert card_with_last4(cards, "1234", " CITI ") is citi
    assert card_with_last4(cards, "1234", "DBS") is None  # none of them
    twins = [card("D", "1234", "UOB"), card("E", "1234", "uob")]
    assert card_with_last4(twins, "1234", "UOB") is None  # still two: tag nothing
    assert len(cards_with_last4(cards, "1234")) == 3
