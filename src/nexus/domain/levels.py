"""Levels worked out from daily prices, in code: never by a model.

Moving averages, momentum (RSI), the typical daily move (ATR), recent swing highs
and lows as resistance and support, and the 52-week range. Prices are adjusted
for splits and dividends first, so a split doesn't look like a crash. Every
figure can be traced back to these formulas and the stored bars.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from nexus.domain.market import Bar

RSI_DAYS = 14
ATR_DAYS = 14
MA_DAYS = (20, 50, 200)
# A swing high (low) is the highest (lowest) point of the days either side of it.
SWING_SIDE = 5
# Swings are looked for in this many recent days.
SWING_DAYS = 120
# Levels closer together than this share of the ATR count as one.
MERGE_ATR = Decimal("0.5")
MAX_LEVELS = 3
YEAR_DAYS = 252
_CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Adjusted:
    """A day's prices on the same footing as today's: scaled by adjusted ÷ raw close."""

    day: date
    high: Decimal
    low: Decimal
    close: Decimal


def adjust(bars: Sequence[Bar]) -> list[Adjusted]:
    out = []
    for b in bars:
        factor = b.adj_close / b.close if b.close else Decimal(1)
        out.append(Adjusted(b.day, b.high * factor, b.low * factor, b.adj_close))
    return out


def sma(closes: Sequence[Decimal], days: int) -> Decimal | None:
    if len(closes) < days:
        return None
    return sum(closes[-days:], Decimal(0)) / days


def rsi(closes: Sequence[Decimal], days: int = RSI_DAYS) -> Decimal | None:
    """Wilder's relative strength index: 0 to 100; above 70 is stretched, below 30
    beaten down."""
    if len(closes) <= days:
        return None
    moves = [b - a for a, b in pairwise(closes)]
    gain = sum((m for m in moves[:days] if m > 0), Decimal(0)) / days
    loss = sum((-m for m in moves[:days] if m < 0), Decimal(0)) / days
    for m in moves[days:]:
        gain = (gain * (days - 1) + max(m, Decimal(0))) / days
        loss = (loss * (days - 1) + max(-m, Decimal(0))) / days
    if loss == 0:
        return Decimal(100)
    return 100 - 100 / (1 + gain / loss)


def atr(days_: Sequence[Adjusted], days: int = ATR_DAYS) -> Decimal | None:
    """Wilder's average true range: how far the price typically moves in a day."""
    if len(days_) <= days:
        return None
    ranges = [
        max(d.high - d.low, abs(d.high - p.close), abs(d.low - p.close)) for p, d in pairwise(days_)
    ]
    value = sum(ranges[:days], Decimal(0)) / days
    for r in ranges[days:]:
        value = (value * (days - 1) + r) / days
    return value


def swings(
    days_: Sequence[Adjusted], side: int = SWING_SIDE
) -> tuple[list[Decimal], list[Decimal]]:
    """Swing highs and lows: a day whose high (low) is the highest (lowest) of the
    ``side`` days before and after it."""
    highs, lows = [], []
    for i in range(side, len(days_) - side):
        window = days_[i - side : i + side + 1]
        if days_[i].high == max(d.high for d in window):
            highs.append(days_[i].high)
        if days_[i].low == min(d.low for d in window):
            lows.append(days_[i].low)
    return highs, lows


def _nearest(points: list[Decimal], price: Decimal, gap: Decimal, *, above: bool) -> list[Decimal]:
    """Up to MAX_LEVELS points on one side of the price, nearest first, with points
    closer together than ``gap`` counted once."""
    side = sorted((p for p in points if (p > price if above else p < price)), reverse=not above)
    levels: list[Decimal] = []
    for p in side:
        if levels and abs(p - levels[-1]) < gap:
            continue
        levels.append(p)
        if len(levels) == MAX_LEVELS:
            break
    return [_q(p) for p in levels]


@dataclass(frozen=True, slots=True)
class Levels:
    symbol: str
    as_of: date
    close: Decimal
    averages: dict[int, Decimal]  # days → moving average; only those with enough history
    rsi: Decimal | None
    atr: Decimal | None
    atr_percent: Decimal | None  # the ATR as a share of the close
    support: list[Decimal]  # below the close, nearest first
    resistance: list[Decimal]  # above the close, nearest first
    year_high: Decimal
    year_low: Decimal
    days: int  # trading days of history used

    @property
    def trend(self) -> str | None:
        """Where the close sits against the 50- and 200-day averages."""
        fifty, two_hundred = self.averages.get(50), self.averages.get(200)
        if fifty is None or two_hundred is None:
            return None
        if self.close > fifty > two_hundred:
            return "uptrend"
        if self.close < fifty < two_hundred:
            return "downtrend"
        return "mixed"


def compute(bars: Sequence[Bar]) -> Levels | None:
    """Levels from a stock's daily bars, oldest first. None with under a month of them."""
    if len(bars) < MA_DAYS[0]:
        return None
    days_ = adjust(bars)
    closes = [d.close for d in days_]
    close = closes[-1]
    averages = {n: _q(v) for n in MA_DAYS if (v := sma(closes, n)) is not None}
    range_ = atr(days_)
    recent = days_[-SWING_DAYS:]
    highs, lows = swings(recent)
    gap = range_ * MERGE_ATR if range_ is not None else Decimal(0)
    year = days_[-YEAR_DAYS:]
    momentum = rsi(closes)
    return Levels(
        symbol=bars[-1].symbol,
        as_of=bars[-1].day,
        close=_q(close),
        averages=averages,
        rsi=_q(momentum) if momentum is not None else None,
        atr=_q(range_) if range_ is not None else None,
        atr_percent=_q(range_ / close * 100) if range_ is not None and close else None,
        support=_nearest(lows, close, gap, above=False),
        resistance=_nearest(highs, close, gap, above=True),
        year_high=_q(max(d.high for d in year)),
        year_low=_q(min(d.low for d in year)),
        days=len(bars),
    )


def describe(levels: Levels) -> list[str]:
    """The levels as short lines, each saying what it is."""

    def money(values: list[Decimal]) -> str:
        return ", ".join(f"{v:,.2f}" for v in values) or "none in the last 6 months"

    lines = [f"Close {levels.close:,.2f} on {levels.as_of:%d %b %Y}"]
    if levels.averages:
        lines.append(
            "Moving averages: "
            + ", ".join(f"{n}-day {v:,.2f}" for n, v in sorted(levels.averages.items()))
        )
    if levels.trend:
        lines.append(f"Trend against the 50/200-day averages: {levels.trend}")
    if levels.rsi is not None:
        lines.append(f"RSI(14): {levels.rsi}")
    if levels.atr is not None:
        lines.append(f"Typical daily move (ATR 14): {levels.atr:,.2f} ({levels.atr_percent}%)")
    lines.append(f"Support (recent swing lows): {money(levels.support)}")
    lines.append(f"Resistance (recent swing highs): {money(levels.resistance)}")
    lines.append(f"52-week range: {levels.year_low:,.2f} to {levels.year_high:,.2f}")
    return lines
