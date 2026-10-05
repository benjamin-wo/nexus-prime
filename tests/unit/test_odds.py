"""Odds from a stock's own past moves: ranges, plan replays and the calibration check.
Every ticker and price here is made up."""

import math
import random
from datetime import date, timedelta
from decimal import Decimal

from nexus.domain.market import Bar
from nexus.domain.odds import (
    MIN_RETURNS,
    calibration,
    daily_volatility,
    describe_odds,
    describe_ranges,
    plan_odds,
    ranges,
    returns,
    trading_days,
)

D = Decimal


def wobble(days: int = 253, size: float = 0.02, seed: int = 7) -> list[float]:
    """Made-up daily moves of about ``size``, up or down at random."""
    dice = random.Random(seed)  # noqa: S311 - test data
    return [size if dice.random() < 0.5 else -size for _ in range(days)]


def test_returns_come_from_adjusted_closes_and_keep_a_year() -> None:
    start = date(2025, 1, 1)
    bars = [
        Bar("ACME", start + timedelta(days=i), D(100), D(100), D(100), D(100), D(100 + i), 1)
        for i in range(300)
    ]
    moves = returns(bars)
    assert len(moves) == 252
    assert math.isclose(moves[-1], math.log(399 / 398))


def test_ranges_widen_with_time_and_are_centred_on_the_close() -> None:
    assert ranges(D(100), wobble(MIN_RETURNS - 1)) == []
    found = ranges(D(100), wobble())
    assert [r.label for r in found] == ["1 week", "1 month", "3 months"]
    sigma = daily_volatility(wobble())
    assert 0.019 < sigma < 0.021
    week, month, quarter = found
    # Two times in three: the close times e to the plus or minus one spread.
    assert week.high_68 == D(str(round(100 * math.exp(sigma * math.sqrt(5)), 2)))
    assert math.isclose(float(week.low_68 * week.high_68), 10000, rel_tol=1e-3)
    for r in found:
        assert r.low_90 < r.low_68 < D(100) < r.high_68 < r.high_90
    assert week.high_90 < month.high_90 < quarter.high_90
    assert describe_ranges(found)[1].startswith("In 1 month: ")


def test_a_drifting_stock_gets_no_lean() -> None:
    # Moves that only went up still give a range around today's close, not above it.
    rising = [m + 0.01 for m in wobble()]
    flat = ranges(D(100), wobble())
    assert ranges(D(100), rising) == flat


def test_plan_odds_are_reproducible_and_add_up() -> None:
    moves = wobble()
    args = (D(100), D(95), [D(105), D(110)], moves, 10)
    first = plan_odds(*args, seed="ACME:2026-09-25", paths=500)
    again = plan_odds(*args, seed="ACME:2026-09-25", paths=500)
    assert first is not None and first == again
    t1, t2 = first.targets
    assert t1.price == D("105.00") and t2.price == D("110.00")
    assert t2.chance <= t1.chance
    assert abs(t1.chance + first.stop_first + first.neither - 100) <= 1
    assert t1.typical_days is not None and 1 <= t1.typical_days <= 10
    lines = describe_odds(first)
    assert lines[0].startswith("Target 1 (105.00) closed before the stop in ")
    assert lines[-1].startswith("The stop (95.00) came first in ")


def test_a_symmetric_plan_is_about_even() -> None:
    # Target and stop the same distance away, plenty of time: close to a coin flip.
    odds = plan_odds(D(100), D(95), [D(105)], wobble(), 250, seed="ACME", paths=2000)
    assert odds is not None
    assert odds.neither < 5
    assert 40 <= odds.targets[0].chance <= 60
    assert 40 <= odds.stop_first <= 60


def test_a_closer_target_is_likelier_than_a_closer_stop() -> None:
    odds = plan_odds(D(100), D(90), [D(103)], wobble(), 40, seed="ACME")
    assert odds is not None and odds.targets[0].chance > odds.stop_first


def test_no_odds_without_enough_history_or_a_sensible_plan() -> None:
    assert plan_odds(D(100), D(95), [D(105)], wobble(MIN_RETURNS - 1), 10, seed="x") is None
    assert plan_odds(D(100), D(95), [], wobble(), 10, seed="x") is None
    assert plan_odds(D(100), D(100), [D(105)], wobble(), 10, seed="x") is None
    assert plan_odds(D(100), D(95), [D(105)], wobble(), 0, seed="x") is None


def test_trading_days_skip_weekends() -> None:
    friday = date(2026, 9, 25)
    assert trading_days(friday, friday) == 0
    assert trading_days(friday, date(2026, 9, 28)) == 1  # Monday
    assert trading_days(friday, date(2026, 10, 9)) == 10


def test_calibration_compares_what_the_odds_said_with_what_happened() -> None:
    assert calibration([]) is None
    c = calibration([(40, True), (50, False), (60, True), (30, False)])
    assert c is not None and (c.plans, c.said, c.happened) == (4, 45, 50)
