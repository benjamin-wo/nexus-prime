"""Hiding card numbers in what a user says: only real card numbers (13 to 19 digits that
pass the Luhn check), down to their last four. Every number here is built when the test
runs, so no card number is written anywhere in the repository."""

import pytest

from nexus.agent.service import CARD_NOTE, Button, Reply, _hidden, _noted
from nexus.domain.private import hide_card_numbers, hide_private
from tests.cards import card_number, last4, luhn_digit, spaced

VISA = card_number()
MASTER = card_number("5", 16, seed=2)
MASTER_2 = card_number("2221", 16, seed=3)
AMEX = card_number("37", 15, seed=4)
OLD_VISA = card_number("4", 13, seed=5)
LONG = card_number("62", 19, seed=6)


def masked(number: str) -> str:
    return f"•••• {last4(number)}"


def broken(number: str) -> str:
    """The same digits with a wrong check digit."""
    return number[:-1] + str((int(number[-1]) + 1) % 10)


@pytest.mark.parametrize(
    "number, typed",
    [
        (VISA, VISA),
        (VISA, spaced(VISA)),
        (VISA, spaced(VISA, "-")),
        (MASTER, spaced(MASTER)),
        (MASTER_2, spaced(MASTER_2)),
        (AMEX, spaced(AMEX, groups=(4, 6, 5))),
        (AMEX, AMEX),
        (OLD_VISA, spaced(OLD_VISA)),
        (LONG, spaced(LONG)),
        (LONG, LONG),
    ],
)
def test_a_card_number_is_cut_down_to_its_last_four(number: str, typed: str) -> None:
    assert hide_card_numbers(f"my card is {typed} thanks") == f"my card is {masked(number)} thanks"
    assert hide_card_numbers(typed) == masked(number)
    assert number[:-4] not in hide_card_numbers(typed).replace(" ", "")


def test_the_last_four_are_all_that_is_left() -> None:
    out = hide_card_numbers(f"pay with {spaced(VISA)}, not {spaced(MASTER)}.")
    assert out == f"pay with {masked(VISA)}, not {masked(MASTER)}."


def test_a_card_followed_by_its_expiry_is_still_hidden() -> None:
    assert hide_card_numbers(f"{spaced(VISA)} 12 28 cvv") == f"{masked(VISA)} 12 28 cvv"
    assert hide_card_numbers(f"{spaced(VISA)} 12/28") == f"{masked(VISA)} 12/28"
    assert hide_card_numbers(f"exp 12 28 {spaced(VISA)}") == f"exp 12 28 {masked(VISA)}"


def test_hiding_twice_changes_nothing() -> None:
    once = hide_card_numbers(f"card {spaced(VISA)}")
    assert hide_card_numbers(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "call +65 9123 4567 or +44 7911 123456",
        "whatsapp +1 415 555 0132",
        "paid SGD 1,234,567.89 for it",
        "that was 12345678901234.56 yen",
        "on 2026-11-03 10:15:30 and 20261103 101530",
        "booking reference XK7Q9P, order 1234567890123, e-ticket 123-4567890123",
        "IBAN GB00 TEST 1234 5612 3456 78 and DE00123456789012345678",
        "invoice INV-2026-000123 / PO 4455667788",
        "split 90 three ways, 30 each, 8.40 for lunch",
        "id 1234567",
        "",
        "no numbers at all",
    ],
)
def test_phone_numbers_amounts_dates_and_references_are_left_alone(text: str) -> None:
    assert hide_card_numbers(text) == text


def test_long_numbers_that_fail_the_card_checksum_are_left_alone() -> None:
    for number in (VISA, MASTER, AMEX, OLD_VISA, LONG):
        wrong = broken(number)
        assert hide_card_numbers(f"order {wrong} and {spaced(wrong)}") == (
            f"order {wrong} and {spaced(wrong)}"
        )


def test_a_number_with_the_wrong_length_or_first_digit_is_not_a_card() -> None:
    for number in (card_number("4", 12, seed=7), card_number("4", 20, seed=8)):
        assert hide_card_numbers(number) == number
        assert hide_card_numbers(spaced(number)) == spaced(number)
    # Passing the checksum is not enough: no card network starts a number with 1, 7, 8 or 9.
    for first in "1789":
        number = card_number(first, 16, seed=9)
        assert hide_card_numbers(number) == number


def test_digits_inside_a_longer_word_or_decimal_are_not_a_card() -> None:
    assert hide_card_numbers(f"DE{VISA}") == f"DE{VISA}"
    assert hide_card_numbers(f"{VISA}x") == f"{VISA}x"
    assert hide_card_numbers(f"+{AMEX}") == f"+{AMEX}"
    assert hide_card_numbers(f"{VISA}.50") == f"{VISA}.50"
    assert hide_card_numbers(f"1.{VISA}") == f"1.{VISA}"
    assert hide_card_numbers(f"ref-{VISA}") == f"ref-{VISA}"


def test_chat_leaves_security_codes_and_passports_to_the_user_but_trips_hide_them() -> None:
    text = f"card {spaced(VISA)} cvv 123, passport E1234567"
    assert hide_card_numbers(text) == f"card {masked(VISA)} cvv 123, passport E1234567"
    assert hide_private(text) == f"card {masked(VISA)} cvv •••, passport •••"


def test_the_check_digit_helper_makes_numbers_that_pass() -> None:
    assert luhn_digit("7992739871") == "3"  # the checksum's standard worked example
    for prefix, length in (("4", 16), ("37", 15), ("62", 19), ("4", 13)):
        number = card_number(prefix, length)
        assert len(number) == length and number.startswith(prefix)
        assert hide_card_numbers(number) == masked(number)


# --- what the agent service does with it ----------------------------------------------


def test_hidden_says_whether_it_hid_something() -> None:
    assert _hidden(f"card {VISA}") == (f"card {masked(VISA)}", True)
    assert _hidden("coffee 4.50") == ("coffee 4.50", False)


def test_the_note_ends_the_last_reply_once_and_keeps_the_rest() -> None:
    ask = Reply("Delete it?", [[Button("Confirm", "hitl:1:y"), Button("Cancel", "hitl:1:n")]])
    out = _noted([Reply("first"), ask], True)
    assert out[0] == Reply("first")
    assert out[1].text == f"Delete it?\n\n{CARD_NOTE}" and out[1].buttons == ask.buttons
    assert _noted(out, True) == out  # not added twice
    assert _noted([Reply("first"), ask], False) == [Reply("first"), ask]
    assert _noted([], True) == [Reply(CARD_NOTE)]
    assert CARD_NOTE == "I only keep the last 4 digits of card numbers."
