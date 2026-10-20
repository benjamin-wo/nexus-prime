"""Prices and what holdings are worth at them. Pure rules, no I/O.

A holding is valued at the last close, or, while the US market is open, at the latest
quote (a live price); after the close and before the day's end-of-day prices arrive, at
the quote's last price (a provisional close). ``pick_price`` decides which.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import NamedTuple
from zoneinfo import ZoneInfo

from nexus.domain.investments import Position
from nexus.domain.money import Money, minor_units

US_MARKET = ZoneInfo("America/New_York")
# When end-of-day prices for a US trading day are worth fetching: some time after
# the 4pm close, and once more later in case the first try came too early.
PUBLISH_TIMES = (time(18, 0), time(22, 0))
# The regular session, New York time. Used when the exchange's own status can't be fetched.
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
# A quote stamped later than this ahead of now is a bad clock or bad data, not a price.
CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class Bar:
    """One trading day of a stock, as the exchange printed it."""

    symbol: str
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    # Adjusted for later splits and dividends: for comparing prices over time.
    adj_close: Decimal
    volume: int
    # A dividend per share going ex on this day (0 on most days), in the price's currency.
    div_cash: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class Quote:
    """The latest trade of a stock, as a provider reported it. Prices in USD."""

    symbol: str
    price: Decimal
    prev_close: Decimal  # the previous trading day's close; 0 when the provider has none
    high: Decimal | None  # the day's range and open; None when not given
    low: Decimal | None
    open: Decimal | None
    quoted_at: datetime  # when that trade happened (UTC)


@dataclass(frozen=True, slots=True)
class MarketStatus:
    """Whether the US market is open, as the exchange calendar says."""

    is_open: bool
    session: str | None  # "pre-market", "regular", "post-market" or None
    holiday: str | None  # the holiday's name on a day the market is shut
    checked_at: datetime

    @property
    def regular(self) -> bool:
        """The regular session is on now (not pre-market or after hours)."""
        return self.is_open and self.session in (None, "regular")


class PriceKind(StrEnum):
    LIVE = "live"  # the latest trade while the market is open
    PROVISIONAL_CLOSE = "provisional_close"  # the day's last trade, before the official close
    CLOSE = "close"  # an official end-of-day close


def trading_day(quoted_at: datetime) -> date:
    """The New York date a quote was made on."""
    return quoted_at.astimezone(US_MARKET).date()


def market_open(now: datetime) -> bool:
    """A weekday between 9:30 and 16:00 in New York. A fallback for when the exchange's
    status can't be fetched: it doesn't know holidays or early closes."""
    local = now.astimezone(US_MARKET)
    return local.weekday() < 5 and REGULAR_OPEN <= local.time() < REGULAR_CLOSE


def regular_open(status: MarketStatus | None, now: datetime) -> bool:
    """Whether the regular session is on: the exchange's word, else the usual hours."""
    return status.regular if status is not None else market_open(now)


def just_closed(
    status: MarketStatus | None, now: datetime, within: timedelta = timedelta(minutes=20)
) -> datetime | None:
    """The regular close at 16:00 today if it was less than ``within`` ago, else None.
    Never on a weekend or a holiday."""
    local = now.astimezone(US_MARKET)
    close = datetime.combine(local.date(), REGULAR_CLOSE, US_MARKET)
    if local.weekday() >= 5 or not close <= local < close + within:
        return None
    if status is not None and status.holiday:
        return None
    return close


class Picked(NamedTuple):
    """The price to show for a stock, and what it is."""

    price: Decimal
    previous: Decimal | None  # the close before, for the day's change
    day: date  # the trading day the price belongs to
    at: datetime | None  # when it was traded; None for an official close
    kind: PriceKind


def pick_price(
    latest: Bar | None,
    previous: Bar | None,
    quote: Quote | None,
    status: MarketStatus | None,
    now: datetime,
) -> Picked | None:
    """Which price to show: the live quote while the market is open and the quote is
    from today; the quote's last price after the close until that day's official bar
    arrives (provisional); otherwise the last close. A quote from a trading day no newer
    than the latest bar, from a past day while the market is open, from before the open
    on its own day, or stamped in the future is ignored. None when there is no bar and
    no usable quote."""
    local = now.astimezone(US_MARKET)
    if quote is not None and quote.price > 0:
        day = trading_day(quote.quoted_at)
        if (latest is None or day > latest.day) and quote.quoted_at <= now + CLOCK_SKEW:
            before = quote.prev_close if quote.prev_close > 0 else None
            if regular_open(status, now):
                if day == local.date():
                    return Picked(quote.price, before, day, quote.quoted_at, PriceKind.LIVE)
            elif day < local.date() or _after_close(status, local):
                return Picked(
                    quote.price, before, day, quote.quoted_at, PriceKind.PROVISIONAL_CLOSE
                )
    if latest is None:
        return None
    return Picked(
        latest.close, previous.close if previous is not None else None, latest.day, None,
        PriceKind.CLOSE,
    )  # fmt: skip


def _after_close(status: MarketStatus | None, local: datetime) -> bool:
    """Today's regular session is over (it isn't the morning of a day not yet open)."""
    if status is not None and status.session == "post-market":
        return True
    return local.time() >= REGULAR_CLOSE


def describe_price_time(kind: PriceKind, at: datetime | None, day: date, tz: ZoneInfo) -> str:
    """When a price is from, for the chat: "at 10:42pm (live)", "at the close
    (provisional)", "at the close on Fri 17 Oct". ``at`` is shown in ``tz``."""
    if kind is PriceKind.LIVE and at is not None:
        return f"at {at.astimezone(tz):%-I:%M%p}".lower() + " (live)"
    if kind is PriceKind.PROVISIONAL_CLOSE:
        return "at the close (provisional)"
    return f"at the close on {day:%a %-d %b}"


def last_publish(now: datetime) -> datetime:
    """The latest moment at or before ``now`` when a weekday's prices were due."""
    local = now.astimezone(US_MARKET)
    for back in range(8):
        day = local.date() - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        for at in sorted(PUBLISH_TIMES, reverse=True):
            moment = datetime.combine(day, at, US_MARKET)
            if moment <= local:
                return moment
    raise AssertionError("unreachable")  # pragma: no cover - a weekday is within 8 days


def due(fetched_at: datetime | None, now: datetime) -> bool:
    """Whether a stock's prices should be fetched again."""
    return fetched_at is None or fetched_at < last_publish(now)


def _round(amount: Decimal, currency: str) -> Money:
    unit = Decimal(1).scaleb(-minor_units(currency))
    return Money(amount.quantize(unit, rounding=ROUND_HALF_UP), currency)


def percent(part: Decimal, whole: Decimal) -> Decimal | None:
    if whole == 0:
        return None
    return (part / whole * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Valued:
    """A position at its latest price: a close, or while the market is open a live quote.
    Everything is in the position's currency."""

    position: Position
    price: Money
    price_day: date
    value: Money
    gain: Money  # against what the user paid
    gain_percent: Decimal | None
    # Since the close before: None with only one day of prices.
    day_change: Money | None
    day_percent: Decimal | None
    # When the price was traded, and what kind it is (see ``pick_price``).
    price_at: datetime | None = None
    price_kind: PriceKind = PriceKind.CLOSE


def value(position: Position, latest: Bar, previous: Bar | None) -> Valued:
    """A position at the close of ``latest``, its day change against ``previous``."""
    close = previous.close if previous is not None else None
    return live_value(position, Picked(latest.close, close, latest.day, None, PriceKind.CLOSE))


def live_value(position: Position, picked: Picked) -> Valued:
    """A position at the price ``pick_price`` chose: a close, a live quote or a
    provisional close."""
    currency = position.average_cost.currency
    worth = _round(position.quantity * picked.price, currency)
    cost = _round(position.cost.amount, currency)
    gain = worth - cost
    change = percent_change = None
    if picked.previous is not None:
        change = _round(position.quantity * (picked.price - picked.previous), currency)
        percent_change = percent(picked.price - picked.previous, picked.previous)
    return Valued(
        position=position,
        price=Money(picked.price.quantize(Decimal("0.0001")), currency),
        price_day=picked.day,
        value=worth,
        gain=gain,
        gain_percent=percent(gain.amount, cost.amount),
        day_change=change,
        day_percent=percent_change,
        price_at=picked.at,
        price_kind=picked.kind,
    )
