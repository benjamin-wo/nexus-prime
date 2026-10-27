"""``near_name``: a name that is probably a misspelling or mishearing of a known one."""

import pytest

from nexus.domain.ledger import near_name


@pytest.mark.parametrize(
    ("known", "given"),
    [
        ("Ann", "Anne"),
        ("Anne", "Ann"),
        ("Sarah", "Sara"),
        ("Sara", "Sarah"),
        ("John", "Jon"),
        ("Steven", "Stephen"),
        ("Stephen", "Steven"),
        ("Ann", "ANNE"),  # any case
        ("Ben", "Bne"),  # swapped neighbours cost one
        ("Ann Lee", "Anne Lee"),  # each word is judged on its own
        ("Wei Ming", "Wei Mng"),
    ],
)
def test_a_small_slip_finds_the_known_name(known: str, given: str) -> None:
    assert near_name([known], given) == known


@pytest.mark.parametrize(
    ("known", "given"),
    [
        ("Sam", "Pam"),  # one letter off, but a different first letter
        ("Ian", "Ann"),
        ("Ann", "Anna Lee"),  # a different number of words
        ("Ann Lee", "Ann Lim"),  # a short word gets one letter only
        ("Ben", "Bob"),
        ("Carol", "Carlos Ruiz"),
        ("Alex", "Alexander"),
        ("Ann", ""),
        ("Ann", "  "),
    ],
)
def test_different_people_are_not_near(known: str, given: str) -> None:
    assert near_name([known], given) is None


def test_it_gives_the_known_name_as_it_was_written() -> None:
    assert near_name(["Sam", "TAN Ann"], "tan anne") == "TAN Ann"


def test_a_name_already_known_is_not_near_anyone() -> None:
    assert near_name(["Ann", "Anne"], "Ann") is None  # exactly known
    assert near_name(["Ann", "Anne"], "anne") is None  # any case
    assert near_name(["Ann", "Anne"], "ANN") is None
    # The way same_person matches: a shorter way of writing a known name.
    assert near_name(["TAN WEI MING", "Wei Mng"], "Wei Ming") is None


def test_two_near_names_are_too_ambiguous_to_pick_one() -> None:
    assert near_name(["Ann", "Anna"], "Anne") is None
    assert near_name(["Ann"], "Anne") == "Ann"


def test_the_same_person_written_twice_counts_once() -> None:
    assert near_name(["Ann", "ann", "ANN"], "Anne") == "Ann"


def test_nothing_known_means_nothing_near() -> None:
    assert near_name([], "Anne") is None
    assert near_name(iter(["Ann"]), "Anne") == "Ann"  # any iterable
