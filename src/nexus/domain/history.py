"""A stock's recent history in numbers: what it returned, how far it has fallen from
its high, whether it's moving and trading more than usual, how it did against the
market, and how it moved on past earnings. Pure maths, no I/O.

Everything is worked out from adjusted closes (splits and dividends don't show as
moves), so the research writers can talk about the past without inventing it.
Percentages are rounded to one decimal place.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from statistics import mean, stdev

from nexus.domain.market import Bar
from nexus.domain.news import EarningsDate

MARKET = "SPY"  # the S&P 500, as a fund: what "the market" means here
YEAR = 252  # trading days
RECENT = 20  # a month of trading days, for "lately"
PERIODS = ((5, "1 week"), (21, "1 month"), (63, "3 months"), (126, "6 months"), (252, "1 year"))
VERSUS = ((21, "1 month"), (63, "3 months"), (252, "1 year"))
MAX_EARNINGS = 4
# Lately busier or calmer than usual beyond these ratios.
BUSIER = 1.25
CALMER = 0.8
USUAL_VOLUME = 10  # % either way that's still "about the year's average"
_TENTH = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class Change:
    label: str  # "1 month"
    percent: Decimal


@dataclass(frozen=True, slots=True)
class Versus:
    label: str
    stock: Decimal  # % over the period
    market: Decimal


@dataclass(frozen=True, slots=True)
class Reaction:
    day: date  # the earnings date
    percent: Decimal  # the close before the news to the close after it


@dataclass(frozen=True, slots=True)
class History:
    changes: list[Change]  # over each period it has prices for, then this year's
    from_high: Decimal | None  # % below the highest close of the last year (<= 0)
    high_day: date | None
    worst_drop: Decimal | None  # the deepest fall from a peak within the last year
    worst_from: date | None
    worst_to: date | None
    move_now: Decimal | None  # typical daily move over the last month, %
    move_normal: Decimal | None  # and over the year
    volume_change: Decimal | None  # last month's average volume against the year's, %
    versus: list[Versus]
    earnings: list[Reaction]  # newest first


def _pct(value: float) -> Decimal:
    return Decimal(str(value * 100)).quantize(_TENTH, ROUND_HALF_UP)


def _closes(bars: Sequence[Bar]) -> list[Bar]:
    return [b for b in bars if b.adj_close > 0]


def _change(closes: Sequence[Bar], back: int) -> float | None:
    if len(closes) <= back:
        return None
    return float(closes[-1].adj_close / closes[-1 - back].adj_close) - 1


def _ytd(closes: Sequence[Bar]) -> float | None:
    """From the last close of the previous year."""
    last = closes[-1]
    before = [b for b in closes if b.day.year < last.day.year]
    if not before:
        return None
    return float(last.adj_close / before[-1].adj_close) - 1


def _worst(closes: Sequence[Bar]) -> tuple[float, date, date] | None:
    """The deepest fall from a peak to a later trough, with both days."""
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst: tuple[float, date, date] | None = None
    for b in closes[1:]:
        if b.adj_close > peak.adj_close:
            peak = b
            continue
        drop = float(b.adj_close / peak.adj_close) - 1
        if worst is None or drop < worst[0]:
            worst = (drop, peak.day, b.day)
    return worst


def _on_or_before(bars: Sequence[Bar], day: date) -> Bar | None:
    i = bisect_right([b.day for b in bars], day)
    return bars[i - 1] if i else None


def _versus(closes: Sequence[Bar], market: Sequence[Bar]) -> list[Versus]:
    market = _closes(market)
    found = []
    for back, label in VERSUS:
        if len(closes) <= back:
            continue
        start, end = closes[-1 - back], closes[-1]
        m_start, m_end = _on_or_before(market, start.day), _on_or_before(market, end.day)
        if m_start is None or m_end is None or m_start.day == m_end.day:
            continue
        # The market's prices must cover the same stretch, give or take a few days.
        if (start.day - m_start.day).days > 5 or (end.day - m_end.day).days > 5:
            continue
        stock = float(end.adj_close / start.adj_close) - 1
        whole = float(m_end.adj_close / m_start.adj_close) - 1
        found.append(Versus(label, _pct(stock), _pct(whole)))
    return found


def _reaction(closes: Sequence[Bar], e: EarningsDate) -> Reaction | None:
    """Before the open: the day before to the day. After the close: the day to the
    next. Not said: the day before to the next, covering either."""
    days = [b.day for b in closes]
    i = bisect_right(days, e.day)  # the first bar after the day
    on = closes[i - 1] if i and days[i - 1] == e.day else None
    before = i - 2 if on is not None else i - 1
    if e.timing == "before open":
        start, end = (closes[before] if before >= 0 else None), on
    elif e.timing == "after close":
        start, end = on, (closes[i] if i < len(closes) else None)
    else:
        start, end = (
            (closes[before] if before >= 0 else None),
            (closes[i] if i < len(closes) else None),
        )
    if start is None or end is None:
        return None
    return Reaction(e.day, _pct(float(end.adj_close / start.adj_close) - 1))


def history(
    bars: Sequence[Bar], market: Sequence[Bar] = (), earnings: Sequence[EarningsDate] = ()
) -> History | None:
    """The stock's history from its daily bars (oldest first), the market's bars over
    the same days, and its past earnings dates. None with under a month of prices."""
    closes = _closes(bars)
    if len(closes) <= RECENT:
        return None
    year = closes[-(YEAR + 1) :]
    changes = []
    for back, label in PERIODS:
        if (c := _change(closes, back)) is not None:
            changes.append(Change(label, _pct(c)))
    if (ytd := _ytd(year)) is not None:
        changes.append(Change("this year", _pct(ytd)))
    high = max(year, key=lambda b: b.adj_close)
    worst = _worst(year)
    moves = [math.log(b.adj_close / a.adj_close) for a, b in pairwise(year)]
    move_now = stdev(moves[-RECENT:]) if len(moves) >= RECENT else None
    move_normal = stdev(moves) if len(moves) >= 2 * RECENT else None
    volumes = [float(b.volume) for b in year if b.volume]
    volume_change = None
    if len(volumes) >= 2 * RECENT and (normal := mean(volumes)) > 0:
        volume_change = _pct(mean(volumes[-RECENT:]) / normal - 1)
    first = year[0].day
    past = sorted((e for e in earnings if first < e.day <= closes[-1].day), key=lambda e: e.day)
    reactions = [r for e in reversed(past) if (r := _reaction(closes, e)) is not None]
    return History(
        changes=changes,
        from_high=_pct(float(closes[-1].adj_close / high.adj_close) - 1),
        high_day=high.day,
        worst_drop=_pct(worst[0]) if worst else None,
        worst_from=worst[1] if worst else None,
        worst_to=worst[2] if worst else None,
        move_now=_pct(move_now) if move_now is not None else None,
        move_normal=_pct(move_normal) if move_normal is not None else None,
        volume_change=volume_change,
        versus=_versus(closes, market),
        earnings=reactions[:MAX_EARNINGS],
    )


def _signed(p: Decimal) -> str:
    return f"{p:+}%"


def describe(h: History) -> list[str]:
    """The history as lines, each saying what it is. Only percentages and days, so
    none of it reads as a price."""
    lines = []
    if h.changes:
        lines.append(
            "Change in price: " + ", ".join(f"{c.label} {_signed(c.percent)}" for c in h.changes)
        )
    if h.from_high is not None and h.high_day is not None:
        lines.append(
            "At its highest close of the last year"
            if h.from_high == 0
            else f"{abs(h.from_high)}% below its highest close of the last year "
            f"({h.high_day:%d %b})"
        )
    if h.worst_drop is not None and h.worst_drop < 0 and h.worst_from and h.worst_to:
        lines.append(
            f"Its deepest fall in the last year: {h.worst_drop}% "
            f"({h.worst_from:%d %b} to {h.worst_to:%d %b})"
        )
    if h.move_now is not None and h.move_normal is not None and h.move_normal > 0:
        ratio = float(h.move_now / h.move_normal)
        mood = (
            "busier than usual"
            if ratio > BUSIER
            else "calmer than usual"
            if ratio < CALMER
            else "about usual"
        )
        lines.append(
            f"Typical daily move: {h.move_now}% over the last month against {h.move_normal}% "
            f"over the year ({mood})"
        )
    if h.volume_change is not None:
        if abs(h.volume_change) < USUAL_VOLUME:
            lines.append("Shares traded over the last month: about the year's average")
        else:
            more = "above" if h.volume_change > 0 else "below"
            lines.append(
                f"Shares traded over the last month: {abs(h.volume_change)}% {more} the "
                "year's average"
            )
    if h.versus:
        lines.append(
            "Against the US market (SPY, an S&P 500 fund): "
            + ", ".join(
                f"{v.label} {_signed(v.stock)} against {_signed(v.market)}" for v in h.versus
            )
        )
    if h.earnings:
        size = mean(abs(float(r.percent)) for r in h.earnings)
        lines.append(
            "Moves on its last earnings: "
            + ", ".join(f"{r.day:%d %b} {_signed(r.percent)}" for r in h.earnings)
            + f" (about {_pct(size / 100)}% either way on average)"
        )
    return lines
