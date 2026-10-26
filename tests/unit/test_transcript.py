"""Tidying what speech-to-text wrote. The transcripts are the ones the speech-model
bake-off produced (made-up phrases read by synthetic voices)."""

import pytest

from nexus.domain.transcript import HEARD_MAX, heard_line, tidy_transcript


def tidy(text: str, currency: str = "SGD") -> str:
    return tidy_transcript(text, currency)


@pytest.mark.parametrize(
    ("heard", "typed"),
    [
        # clock-style and run-together amounts in a spending sentence
        ("Lunch at Maxwell 8:40.", "Lunch at Maxwell 8.40."),
        ("Lunch at Maxwell 8:40", "Lunch at Maxwell 8.40"),
        ("Lunch at Maxwell, 8:40.", "Lunch at Maxwell, 8.40."),
        ("Lunch at Maxwell 840.", "Lunch at Maxwell 8.40."),
        ("Taxi home 23:50 last Friday.", "Taxi home 23.50 last Friday."),
        ("Taxi home 2350 last Friday.", "Taxi home 23.50 last Friday."),
        ("Taxi Home, 2350 last Friday.", "Taxi Home, 23.50 last Friday."),
        ("1799 for Netflix.", "17.99 for Netflix."),
        ("Grab 1250.", "Grab 12.50."),
        ("Grab 12:50.", "Grab 12.50."),
        # a split pair
        ("Grab 12.  50.", "Grab 12.50."),
        ("Grab 12. 50.", "Grab 12.50."),
        # the dollar sign is the home currency
        ("Grab $12.50.", "Grab 12.50."),
        (
            "Dinner $60 at Din Tai Fung, split with Anne.",
            "Dinner 60 at Din Tai Fung, split with Anne.",
        ),
        ("Taxi home, $23.50, last Friday.", "Taxi home, 23.50, last Friday."),
        ("$1.8K for a new laptop.", "1.8K for a new laptop."),
        ("Move $300 to savings on the 25th.", "Move 300 to savings on the 25th."),
        ("Anne paid me back $40.", "Anne paid me back 40."),
        # made-up closing sentences
        ("and paid me back $40.  We'll be right back.", "and paid me back 40."),
        ("Lunch 4.50. Thanks for watching.", "Lunch 4.50."),
        ("Lunch 4.50. Thank you for watching!", "Lunch 4.50."),
        ("Thanks for watching.", ""),
        # whitespace
        ("  coffee \n 3.50\t ", "coffee 3.50"),
        ("", ""),
    ],
)
def test_it_reads_what_the_user_meant(heard: str, typed: str) -> None:
    assert tidy(heard) == typed


@pytest.mark.parametrize(
    "text",
    [
        # real times
        "add dinner at 7:30 pm",
        "Add dinner at 7:30 PM tomorrow.",
        "meet at 8:40",
        "Lunch with Ann at 8:40",
        "dinner at 14:00",
        "at 14:00",
        "Taxi from 8:40 to the airport",
        "pay the bill by 9:15",
        "Dinner 7:30 pm.",
        "Dinner 7:30 tonight.",
        "Add a temple visit to day 3 of my Japan trip at 2 p.m.",
        # not a spending sentence
        "How much did I spend on Grab this month?",
        "Remind me about 840.",
        # round or large amounts stay as said
        "send 500 to Alex",
        "log 500 for rent",
        "1850 for rent",
        "Paid 1800 for the laptop",
        "Dinner 120",
        "Coffee 4.50",
        # years, a minute that could be a dropped digit, a second amount
        "Spent 2026 on groceries",
        "Dinner 6:00 at Din Tai Fung split with Ann.",
        "Lunch 840 and taxi 1250",
        "Lunch at Maxwell 8:40 for 2 people",
        # already right
        "Grab 12.50.",
        "Lunch at Maxwell 8.40.",
        "17.99 for Netflix.",
    ],
)
def test_it_leaves_alone_what_may_be_right(text: str) -> None:
    assert tidy(text) == text


def test_each_sentence_is_read_on_its_own() -> None:
    assert tidy("Lunch 8:40. Taxi home 2350.") == "Lunch 8.40. Taxi home 23.50."
    assert tidy("Lunch 8:40. Meet Ann at 9:15.") == "Lunch 8.40. Meet Ann at 9:15."


def test_a_dollar_sign_with_another_currency_named_is_left_as_said() -> None:
    assert tidy("$15 USD for ChatGPT.") == "$15 USD for ChatGPT."
    assert tidy("$15 SGD for ChatGPT.", "SGD") == "15 SGD for ChatGPT."
    assert tidy("$15 USD for ChatGPT.", "USD") == "15 USD for ChatGPT."
    assert tidy("Lunch $15 in US dollars.") == "Lunch $15 in US dollars."
    assert tidy("S$12 for lunch") == "S$12 for lunch"


def test_a_made_up_sentence_is_dropped_only_when_it_is_the_last() -> None:
    assert tidy("Thanks for watching. Lunch 4.50.") == "Thanks for watching. Lunch 4.50."
    assert tidy("Lunch 4.50. Please subscribe. We'll be right back.") == "Lunch 4.50."
    assert tidy("Lunch 4.50. We\u2019ll be right back.") == "Lunch 4.50."


def test_the_heard_line_is_cut_to_a_sensible_length() -> None:
    assert heard_line("Lunch 8.40.") == '🎙 heard: "Lunch 8.40"'
    long = heard_line("x" * 500)
    assert long.endswith('…"')
    assert len(long) < HEARD_MAX + 20
