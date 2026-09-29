from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.rules import CategoryRule, best_rule, clean_pattern, matches, pattern_for

T0 = datetime(2026, 9, 29, tzinfo=UTC)


def rule(pattern: str, age: int = 0, archived: bool = False) -> CategoryRule:
    at = T0 + timedelta(minutes=age)
    return CategoryRule(
        uuid4(), UserId(uuid4()), pattern, uuid4(), "", at, at, at if archived else None
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Grab   Food ", "grab food"),
        ("“Grab”", "grab"),
        ("NTUC.", "ntuc"),
        ("7-Eleven", "7-eleven"),
    ],
)
def test_patterns_are_normalised(text: str, expected: str) -> None:
    assert clean_pattern(text.replace("“", '"').replace("”", '"')) == expected


@pytest.mark.parametrize("text", ["", "  ", "x", "y" * 61])
def test_unusable_patterns(text: str) -> None:
    with pytest.raises(InvalidInput):
        clean_pattern(text)
    assert pattern_for(text) is None


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Grab", True),
        ("GRAB*ride 1234", True),
        ("paid grab", True),
        ("Grabbed", False),
        ("Megrab", False),
        (None, False),
    ],
)
def test_whole_word_matching(text: str | None, hit: bool) -> None:
    assert matches("grab", text) is hit


def test_multi_word_patterns_ignore_spacing() -> None:
    assert matches("grab food", "Grab   FOOD delivery")
    assert not matches("grab food", "GrabFood")


def test_best_rule_ordering() -> None:
    broad, narrow, notes_only = rule("grab"), rule("grab food", age=5), rule("dinner at grab food")
    rules = [broad, narrow, notes_only]
    assert best_rule(rules, "Grab Food", None) is narrow
    assert best_rule(rules, "Grab", None) is broad
    # A merchant match beats a longer notes match.
    assert best_rule(rules, "Grab", "dinner at grab food") is broad
    assert best_rule(rules, "Cash", "dinner at grab food") is notes_only
    assert best_rule(rules, "Cash", None) is None
    # Equal length: the older rule wins; archived rules never do.
    older, newer = rule("taxi", age=0), rule("cabs", age=1)
    assert best_rule([newer, older], "taxi cabs", None) is older
    assert best_rule([rule("taxi", archived=True)], "taxi", None) is None
