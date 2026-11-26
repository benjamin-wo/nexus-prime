"""The number-provenance check: a health reply states only numbers its turn's tools gave."""

import pytest

from nexus.evals.checks import unsupported_numbers
from nexus.evals.runner import TurnLog, provenance_failures

LAST_TIME = "Last time, Mon 21 Sep, Barbell Squat: 3 sets of 5 at 100 kg. Volume 1,500.50 kg."


@pytest.mark.parametrize(
    ("reply", "sources"),
    [
        ("You did 3 sets of 5 at 100 kg.", [LAST_TIME]),
        ("That was 100kg for 5 reps.", [LAST_TIME]),  # no space before the unit
        ("Volume was 1500.5 kg.", [LAST_TIME]),  # thousands separator and a trailing zero
        ("Volume was 1,500.50 kg.", ["Volume 1500.5 kg"]),
        ("About 1,501 kg of volume.", [LAST_TIME]),  # rounded to the places shown
        ("About 1,500 kg of volume.", [LAST_TIME]),
        ("You had 52 g of protein.", ["Protein 52.4 g, calories 610"]),
        ("That is 220 lb.", ["Heaviest 100 kg"]),  # kilograms in pounds
        ("That is 80 kg.", ["Heaviest 176.4 lb at 80 kg"]),
        ("1. Add 2.5 kg\n2. Hold", ["Add 2.5 kg"]),  # list markers aren't figures
        ("Okay, nothing to change.", []),  # no numbers, nothing to support
        ("Logged 6.50.", ["Logged 6.50 SGD at the hawker"]),
    ],
)
def test_figures_the_tools_gave_pass(reply: str, sources: list[str]) -> None:
    assert unsupported_numbers(reply, sources) == []


@pytest.mark.parametrize(
    ("reply", "sources", "bad"),
    [
        ("You did 3 sets of 5 at 105 kg.", [LAST_TIME], ["105"]),
        ("About 2,000 calories a day.", [LAST_TIME], ["2000"]),  # an estimate of its own
        ("Total 4 sets.", ["3 sets of 5"], ["4"]),  # a sum the model made
        ("Volume was 1,600 kg.", [LAST_TIME], ["1600"]),  # rounding goes no further than shown
        ("That's 100 lb.", ["Heaviest 100 kg"], ["100"]),  # pounds are not kilograms
        ("You have 800 a day.", [], ["800"]),  # no tool ran at all
        ("Try 82.5 kg, then 85 kg.", ["Try 82.5 kg"], ["85"]),
    ],
)
def test_figures_no_tool_gave_fail(reply: str, sources: list[str], bad: list[str]) -> None:
    assert unsupported_numbers(reply, sources) == bad


def turn(reply: str, *results: str, said: str = "") -> TurnLog:
    return TurnLog(said, replies=[reply], results=list(results))


def test_a_turn_may_quote_what_the_user_said_and_the_card_they_confirmed() -> None:
    card = TurnLog(
        "bench 3x5 at 80",
        replies=["Log Bench: 3 sets of 5 at 80 kg?", "Done: 3 sets of 5 at 80 kg."],
    )
    assert provenance_failures([card]) == []
    assert provenance_failures([turn("You lifted 90 kg.", said="bench 3x5 at 80")]) == [
        "reply states 90, which no tool gave"
    ]


def test_the_fixed_referral_texts_count_as_given() -> None:
    assert provenance_failures([turn("Call 995 now, or Samaritans on 1767.")]) == []
    assert provenance_failures([turn("Call 996 now.")]) == ["reply states 996, which no tool gave"]
