"""Daily prices and what holdings are worth at them. Pure rules, no I/O.

End-of-day data only: a holding is valued at the last close, never a live quote.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from nexus.domain.investments import Position
from nexus.domain.money import Money, minor_units

US_MARKET = ZoneInfo("America/New_York")
# When end-of-day prices for a US trading day are worth fetching: some time after
# the 4pm close, and once more later in case the first try came too early.
PUBLISH_TIMES = (time(18, 0), time(22, 0))


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
    """A position at its latest close. Everything is in the position's currency."""

    position: Position
    price: Money
    price_day: date
    value: Money
    gain: Money  # against what the user paid
    gain_percent: Decimal | None
    # Since the close before: None with only one day of prices.
    day_change: Money | None
    day_percent: Decimal | None


def value(position: Position, latest: Bar, previous: Bar | None) -> Valued:
    currency = position.average_cost.currency
    worth = _round(position.quantity * latest.close, currency)
    cost = _round(position.cost.amount, currency)
    gain = worth - cost
    change = percent_change = None
    if previous is not None:
        change = _round(position.quantity * (latest.close - previous.close), currency)
        percent_change = percent(latest.close - previous.close, previous.close)
    return Valued(
        position=position,
        price=Money(latest.close.quantize(Decimal("0.0001")), currency),
        price_day=latest.day,
        value=worth,
        gain=gain,
        gain_percent=percent(gain.amount, cost.amount),
        day_change=change,
        day_percent=percent_change,
    )
