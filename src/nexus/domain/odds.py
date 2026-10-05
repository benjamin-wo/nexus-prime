"""Odds from a stock's own past moves: likely price ranges, and how often a plan's
targets were reached before its stop when the last year's daily moves are replayed.
Pure maths, no I/O.

None of this forecasts a price. It says what the stock's own recent moves make
likely, with no view on direction: returns are centred on zero, so a stock that
rallied all year isn't assumed to keep rallying. Results are rounded to whole
percentages and depend only on the prices given (the replay's dice are seeded by
the stock and day), so the same data always gives the same odds.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from nexus.domain.market import Bar

# A year of daily moves; fewer than this many and there are no odds.
LOOKBACK = 252
MIN_RETURNS = 60
# Replays of the plan's window, in blocks of a week's moves so calm and rough
# spells keep together.
PATHS = 2000
BLOCK = 5
# z-scores for the middle 68% and 90% of a normal spread.
Z68 = 1.0
Z90 = 1.645
HORIZONS = ((5, "1 week"), (21, "1 month"), (63, "3 months"))
_CENT = Decimal("0.01")


def returns(bars: Sequence[Bar]) -> list[float]:
    """Daily log returns from adjusted closes (splits and dividends don't show as
    moves), the last year's, oldest first."""
    closes = [float(b.adj_close) for b in bars if b.adj_close > 0][-(LOOKBACK + 1) :]
    return [math.log(b / a) for a, b in pairwise(closes)]


def _centred(moves: Sequence[float]) -> list[float]:
    mean = sum(moves) / len(moves)
    return [m - mean for m in moves]


def daily_volatility(moves: Sequence[float]) -> float:
    centred = _centred(moves)
    return math.sqrt(sum(m * m for m in centred) / (len(centred) - 1))


@dataclass(frozen=True, slots=True)
class Range:
    """Where the price ends up after ``days`` trading days, two times in three
    (68%) and nine times in ten (90%), from the stock's own volatility."""

    days: int
    label: str  # "1 month"
    low_68: Decimal
    high_68: Decimal
    low_90: Decimal
    high_90: Decimal


def _price(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def ranges(close: Decimal, moves: Sequence[float]) -> list[Range]:
    if len(moves) < MIN_RETURNS:
        return []
    sigma = daily_volatility(moves)
    base = float(close)
    found = []
    for days, label in HORIZONS:
        spread = sigma * math.sqrt(days)
        found.append(
            Range(
                days, label,
                _price(base * math.exp(-Z68 * spread)), _price(base * math.exp(Z68 * spread)),
                _price(base * math.exp(-Z90 * spread)), _price(base * math.exp(Z90 * spread)),
            )
        )  # fmt: skip
    return found


@dataclass(frozen=True, slots=True)
class TargetOdds:
    price: Decimal
    chance: int  # % of replays reaching it (on a close) before the stop
    typical_days: int | None  # the median trading days it took, when reached


@dataclass(frozen=True, slots=True)
class PlanOdds:
    """How a plan played out over many replays of the stock's past daily moves."""

    reference: Decimal  # the price the replays start from (the buy price, or the close)
    stop: Decimal
    days: int  # trading days in the plan's window
    targets: list[TargetOdds]
    stop_first: int  # % of replays closing below the stop before the first target
    neither: int  # % reaching neither within the window
    paths: int


def trading_days(start: date, end: date) -> int:
    """Weekdays after ``start`` up to ``end`` (holidays aside)."""
    days, day = 0, start
    while day < end:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days += 1
    return days


def _pct(count: int, total: int) -> int:
    return int(Decimal(count * 100) / Decimal(total) + Decimal("0.5"))


def plan_odds(
    reference: Decimal,
    stop: Decimal,
    targets: Sequence[Decimal],
    moves: Sequence[float],
    days: int,
    *,
    seed: str,
    paths: int = PATHS,
) -> PlanOdds | None:
    """Replays ``days`` of the past year's daily moves (in week-long blocks, centred
    on no drift) from ``reference``: how often each target closed before the stop."""
    if len(moves) < MIN_RETURNS or days <= 0 or not targets or stop >= reference:
        return None
    centred = _centred(moves)
    dice = random.Random(seed)  # noqa: S311 - reproducible replays, not secrets
    start, floor = float(reference), float(stop)
    levels = [float(t) for t in targets]
    reached: list[list[int]] = [[] for _ in levels]
    stopped = untouched = 0
    starts = len(centred) - BLOCK
    for _ in range(paths):
        price, day, hit, stop_hit = start, 0, [False] * len(levels), False
        while day < days and not stop_hit and not all(hit):
            at = dice.randrange(starts + 1)
            for move in centred[at : at + BLOCK]:
                day += 1
                price *= math.exp(move)
                if price <= floor:
                    stop_hit = True
                    break
                for i, level in enumerate(levels):
                    if not hit[i] and price >= level:
                        hit[i] = True
                        reached[i].append(day)
                if all(hit) or day >= days:
                    break
        if not hit[0]:
            if stop_hit:
                stopped += 1
            else:
                untouched += 1
    return PlanOdds(
        reference=reference.quantize(_CENT),
        stop=stop.quantize(_CENT),
        days=days,
        targets=[
            TargetOdds(
                Decimal(str(level)).quantize(_CENT),
                _pct(len(when), paths),
                sorted(when)[len(when) // 2] if when else None,
            )
            for level, when in zip(levels, reached, strict=True)
        ],
        stop_first=_pct(stopped, paths),
        neither=_pct(untouched, paths),
        paths=paths,
    )


def describe_ranges(found: Sequence[Range]) -> list[str]:
    return [
        f"In {r.label}: {r.low_68} to {r.high_68} two times in three, "
        f"{r.low_90} to {r.high_90} nine times in ten"
        for r in found
    ]


def describe_odds(o: PlanOdds) -> list[str]:
    lines = []
    for n, t in enumerate(o.targets, 1):
        took = f", typically in {t.typical_days} trading days" if t.typical_days else ""
        lines.append(
            f"Target {n} ({t.price}) closed before the stop in {t.chance}% of replays{took}"
        )
    lines.append(
        f"The stop ({o.stop}) came first in {o.stop_first}%; neither within the "
        f"{o.days} trading days in {o.neither}%"
    )
    return lines


# --- calibration -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Calibration:
    """Whether past odds held up: the average chance plans gave their first target,
    against how many of those plans reached it."""

    plans: int
    said: int  # average % the odds gave
    happened: int  # % that reached their first target


def calibration(outcomes: Sequence[tuple[int, bool]]) -> Calibration | None:
    """From (the odds given to the first target, whether it was reached)."""
    if not outcomes:
        return None
    said = sum(chance for chance, _ in outcomes) / len(outcomes)
    return Calibration(
        len(outcomes),
        int(Decimal(str(said)) + Decimal("0.5")),
        _pct(sum(1 for _, hit in outcomes if hit), len(outcomes)),
    )
