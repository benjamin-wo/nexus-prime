"""Reading gym entries and ranges, and writing figures down. No database."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from nexus.agent import gym_text
from nexus.domain.errors import InvalidInput
from nexus.domain.gym_entry import (
    ALIASES,
    MAX_SETS_AT_ONCE,
    ParsedSet,
    alias_id,
    parse_range,
    parse_sets,
    parse_week,
)
from nexus.domain.gym_training import SetKind, WeightUnit
from nexus.infra.exercises import load_catalogue

D = Decimal
MONDAY = date(2026, 9, 28)


def test_every_alias_names_a_catalogue_exercise() -> None:
    ids = {e.id for e in load_catalogue()}
    assert {v for v in ALIASES.values()} <= ids
    assert alias_id("Bench!") == "Barbell_Bench_Press_-_Medium_Grip"
    assert alias_id("tricep pushdown") is None


@pytest.mark.parametrize(
    ("text", "count", "first"),
    [
        ("3x5 at 80", 3, ParsedSet(reps=5, weight=D(80))),
        ("3 by 8 at 60kg RPE 8", 3, ParsedSet(reps=8, weight=D(60), unit=WeightUnit.KG, rpe=D(8))),
        (f"3 {chr(0xD7)} 5 @ 82,5 kg", 3, ParsedSet(reps=5, weight=D("82.5"), unit=WeightUnit.KG)),
        ("5 reps at 135 lb", 1, ParsedSet(reps=5, weight=D(135), unit=WeightUnit.LB)),
        ("4 sets of 6 bodyweight", 4, ParsedSet(reps=6)),
        ("3x60s", 3, ParsedSet(seconds=60)),
        ("8 reps", 1, ParsedSet(reps=8)),
        ("2x5 at 40 warm-up", 2, ParsedSet(reps=5, weight=D(40), kind=SetKind.WARMUP)),
        ("3x5 at 100 @ rpe 8.5", 3, ParsedSet(reps=5, weight=D(100), rpe=D("8.5"))),
    ],
)
def test_sets_are_read_from_what_the_user_typed(text: str, count: int, first: ParsedSet) -> None:
    sets = parse_sets(text)
    assert len(sets) == count and sets[0] == first


def test_several_groups_keep_their_order_and_their_own_numbers() -> None:
    sets = parse_sets("warm-up 2x5 at 40, 3x5 at 80 kg then 1x3 at 85")
    assert [(s.kind, s.weight) for s in sets] == [
        (SetKind.WARMUP, D(40)),
        (SetKind.WARMUP, D(40)),
        *[(SetKind.WORKING, D(80))] * 3,
        (SetKind.WORKING, D(85)),
    ]


@pytest.mark.parametrize("text", ["", "at 80", "bench", "0x5", f"{MAX_SETS_AT_ONCE + 1}x5"])
def test_what_cannot_be_read_is_refused_not_guessed(text: str) -> None:
    with pytest.raises(InvalidInput):
        parse_sets(text)


def test_ranges() -> None:
    day = timedelta(days=1)
    assert parse_range("today", MONDAY) == (MONDAY, MONDAY + day)
    assert parse_range("Yesterday", MONDAY) == (MONDAY - day, MONDAY)
    assert parse_range("this week", date(2026, 9, 30)) == (MONDAY, date(2026, 10, 5))
    assert parse_range("last week", MONDAY) == (date(2026, 9, 21), MONDAY)
    assert parse_range("this month", MONDAY) == (date(2026, 9, 1), date(2026, 10, 1))
    assert parse_range("last month", date(2026, 1, 5)) == (date(2025, 12, 1), date(2026, 1, 1))
    assert parse_range("last 7 days", MONDAY) == (date(2026, 9, 22), MONDAY + day)
    assert parse_range("2026-09-14", MONDAY) == (date(2026, 9, 14), date(2026, 9, 15))
    assert parse_range("2026-09-01 to 2026-09-14", MONDAY) == (date(2026, 9, 1), date(2026, 9, 15))
    for bad in ("someday", "last 0 days", "2026-09-14 to 2026-09-01", "2026-13-40"):
        with pytest.raises(InvalidInput):
            parse_range(bad, MONDAY)


def test_weeks_start_on_monday() -> None:
    assert parse_week(None, date(2026, 9, 30)) == MONDAY
    assert parse_week("last week", date(2026, 9, 30)) == date(2026, 9, 21)
    assert parse_week("2026-09-17", MONDAY) == date(2026, 9, 14)
    with pytest.raises(InvalidInput):
        parse_week("whenever", MONDAY)


def test_sets_are_described_in_runs() -> None:
    sets = [
        ParsedSet(reps=5, weight=D(40), kind=SetKind.WARMUP),
        *[ParsedSet(reps=5, weight=D(80), unit=WeightUnit.KG)] * 3,
        ParsedSet(reps=3, weight=D("82.5"), rpe=D(9)),
        ParsedSet(seconds=60),
    ]
    assert gym_text.describe_sets(sets) == (
        "1 warm-up set of 5 at 40 kg, 3 sets of 5 at 80 kg, 1 set of 3 at 82.5 kg (RPE 9), "
        "1 set of 60 s"
    )


def test_figures_are_written_plainly() -> None:
    assert gym_text.num(D("80.00")) == "80"
    assert gym_text.num(D("1234.56"), 1) == "1,234.6"
    assert gym_text.kg_text(D(4200)) == "4,200 kg"
    assert gym_text.duration_text(timedelta(seconds=30)) == "under a minute"
    assert gym_text.duration_text(timedelta(minutes=52)) == "52 min"
    assert gym_text.duration_text(timedelta(minutes=65)) == "1 h 05 min"
    assert gym_text.day_text(date(2026, 9, 21), MONDAY) == "Mon 21 Sep"
    assert gym_text.day_text(date(2025, 9, 22), MONDAY) == "Mon 22 Sep 2025"
