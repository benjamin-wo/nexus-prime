"""Splitting habits as pure code: reading a share, which habits hold for an expense, and what
each person owes. Made-up names and amounts only."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import ShareRequest, UserId
from nexus.domain.money import Money
from nexus.domain.split_habits import (
    SplitHabit,
    clean_habit,
    clean_share,
    habit_shares,
    matching,
    parse_share,
    percent,
    select_for_removal,
)

ME = UserId(uuid4())
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def habit(
    person: str, applies_to: str | None = None, share: str = "0.5", day: int = 0
) -> SplitHabit:
    return SplitHabit(uuid4(), ME, person, applies_to, Decimal(share), T0 + timedelta(days=day))


def names(habits: list[SplitHabit]) -> list[str]:
    return [h.person for h in habits]


# --- shares -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "share"),
    [
        (None, "0.5"),
        ("", "0.5"),
        ("0.4", "0.4"),
        ("40%", "0.4"),
        (" 33.33 % ", "0.3333"),
        ("1/3", "0.3333"),
        ("2 / 5", "0.4"),
    ],
)
def test_a_share_is_read_the_way_people_write_it(text: str | None, share: str) -> None:
    assert parse_share(text) == Decimal(share)


@pytest.mark.parametrize("text", ["0", "1", "100%", "0%", "150%", "-0.2", "3/2", "1/0", "half"])
def test_a_share_must_be_between_nothing_and_everything(text: str) -> None:
    with pytest.raises(InvalidInput):
        parse_share(text)


def test_a_share_is_kept_to_four_places_and_never_rounds_out_of_range() -> None:
    assert clean_share(Decimal("0.123456")) == Decimal("0.1235")
    with pytest.raises(InvalidInput):
        clean_share(Decimal("0.00001"))  # rounds to nothing
    with pytest.raises(InvalidInput):
        clean_share(Decimal("0.99999"))  # rounds to everything
    with pytest.raises(InvalidInput):
        clean_share(Decimal("NaN"))


def test_a_habit_is_tidied_and_checked() -> None:
    assert clean_habit("  Ann   Lee ", " Dining  Out ", Decimal("0.5")) == (
        "Ann Lee",
        "Dining Out",
        Decimal("0.5"),
    )
    assert clean_habit("Ann", "  ", Decimal("0.5"))[1] is None
    assert clean_habit("Ann", None, Decimal("0.5"))[1] is None
    with pytest.raises(InvalidInput):
        clean_habit("   ", None, Decimal("0.5"))
    with pytest.raises(InvalidInput):
        clean_habit("Ann", None, Decimal(1))


def test_shares_are_shown_as_percentages() -> None:
    assert [percent(Decimal(s)) for s in ("0.5", "0.3333", "0.6", "0.125")] == [
        "50%",
        "33.33%",
        "60%",
        "12.5%",
    ]
    assert habit("Ann", "Dining Out").describe() == "Dining Out expenses with Ann: their share 50%"
    assert habit("Ben").describe() == "any expense with Ben: their share 50%"


# --- which habits hold ----------------------------------------------------------------------


def test_nothing_matches_without_habits_or_for_another_category() -> None:
    assert matching([], "Dining Out") == []
    assert matching([habit("Ann", "Groceries")], "Dining Out") == []
    assert matching([habit("Ann", "Dining Out")], None) == []


def test_a_habit_for_the_category_matches_in_any_case() -> None:
    ann = habit("Ann", "Dining Out")
    assert matching([ann], "dining out") == [ann]


def test_a_habit_for_anything_matches_every_category_even_none() -> None:
    ben = habit("Ben")
    assert matching([ben], "Transport") == [ben]
    assert matching([ben], None) == [ben]


def test_the_category_beats_anything() -> None:
    ann, ben = habit("Ann", "Dining Out"), habit("Ben")
    assert matching([ben, ann], "Dining Out") == [ann]
    assert matching([ben, ann], "Groceries") == [ben]


def test_several_people_can_share_a_category_oldest_first() -> None:
    ben = habit("Ben", "Dining Out", "0.3333", day=2)
    ann = habit("Ann", "Dining Out", "0.3333", day=1)
    assert names(matching([ben, ann, habit("Cat", "Groceries")], "Dining Out")) == ["Ann", "Ben"]


def test_a_person_appears_once_even_if_the_same_name_was_saved_twice() -> None:
    first, second = habit("Ann", "Dining Out", day=1), habit("ann", "Dining Out", day=2)
    assert matching([second, first], "Dining Out") == [first]


# --- what each person owes ------------------------------------------------------------------


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def test_half_of_a_bill() -> None:
    assert habit_shares(sgd("60"), [habit("Ann")]) == [ShareRequest("Ann", sgd("30.00"))]


def test_a_friend_is_never_charged_a_rounded_up_cent() -> None:
    assert habit_shares(sgd("60.01"), [habit("Ann")]) == [ShareRequest("Ann", sgd("30.00"))]
    thirds = [habit("Ann", share="0.3333"), habit("Ben", share="0.3333")]
    assert habit_shares(sgd("100"), thirds) == [
        ShareRequest("Ann", sgd("33.33")),
        ShareRequest("Ben", sgd("33.33")),
    ]


def test_a_currency_without_cents_is_rounded_to_whole_units() -> None:
    assert habit_shares(Money.of("1001", "JPY"), [habit("Ann")]) == [
        ShareRequest("Ann", Money.of("500", "JPY"))
    ]


def test_a_share_that_rounds_to_nothing_is_left_out() -> None:
    assert habit_shares(sgd("0.01"), [habit("Ann", share="0.4")]) == []


def test_habits_that_claim_more_than_the_bill_are_refused() -> None:
    pair = [habit("Ann", share="0.6"), habit("Ben", share="0.6")]
    with pytest.raises(InvalidInput, match="more than the whole bill"):
        habit_shares(sgd("10"), pair)


# --- forgetting -----------------------------------------------------------------------------


def test_forgetting_a_person_without_a_category_takes_all_their_habits() -> None:
    ann_dinners, ann_all, ben = habit("Ann", "Dining Out"), habit("Ann"), habit("Ben")
    assert select_for_removal([ann_dinners, ann_all, ben], "ann") == [ann_dinners, ann_all]


def test_forgetting_with_a_category_takes_only_that_one() -> None:
    ann_dinners, ann_all = habit("Ann", "Dining Out"), habit("Ann")
    assert select_for_removal([ann_dinners, ann_all], "Ann", "dining out") == [ann_dinners]
    assert select_for_removal([ann_dinners, ann_all], "Ann", "Groceries") == []


def test_a_shortened_name_finds_the_one_person_it_means_but_not_two() -> None:
    lee = habit("Ann Lee", "Dining Out")
    assert select_for_removal([lee], "Ann") == [lee]
    assert select_for_removal([lee, habit("Ann Tan")], "Ann") == []
    assert select_for_removal([lee], "Ben") == []
