"""Where a month ends up: what has come in and gone out so far, what is still expected, and
what that leaves, with any amounts the user mentions added by code.

This is the arithmetic behind "how much leeway do I have to be positive overall?". The
model must not do it in its head, so it is done here, exactly, in the home currency and
the user's timezone, from the same figures Home shows (``month_figures``, ``expected_between``):

- received and spent are the month's totals (money between the user's own wallets is
  neither); ``net so far`` is received less spent.
- ``moved`` is what went from the main account to the user's other wallets (savings,
  investments; not cards): not spending, but money that has left the main account, so
  it comes off the projection exactly as it does in Home's "left to spend".
- still expected, from today to month end: scheduled payments (bills and scheduled moves),
  tracked subscriptions, trip set-asides and payday. Items with no amount or no exchange
  rate are listed, not counted.
- ``projected_net`` = received + expected in - spent - moved - expected out. With no
  adjustments it equals Home's "left to spend".
- ``overall`` adds the user's own amounts (a carry-over, a planned purchase as a negative).
- ``headroom`` is how much more everyday spending keeps ``overall`` at zero or above.

Everyday spending for the rest of the month is not forecast, and none of this is an
account balance. A month already over has actuals only.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from nexus.application.cashflow import Expected, ExpectedKind, expected_between
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.application.wallet_figures import month_range, wallet_figures
from nexus.domain.calc import calculate
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, User
from nexus.domain.money import Money, minor_units
from nexus.domain.planning import month_start, next_month_start

type UowFactory = Callable[[], UnitOfWork]

MAX_ADJUSTMENTS = 20
MAX_MONTHS_AHEAD = 24


@dataclass(frozen=True, slots=True)
class OutlookItem:
    day: date
    kind: ExpectedKind
    name: str
    direction: Direction
    amount: Money | None  # in the home currency; None: no amount set, or no rate
    original: Money | None  # in its own currency, when that isn't the home currency


@dataclass(frozen=True, slots=True)
class Adjustment:
    label: str
    amount: Money  # signed: a carry-over is positive, a planned purchase negative


@dataclass(frozen=True, slots=True)
class Expectations:
    """What a list of expected items adds up to."""

    money_in: Money
    money_out: Money
    no_amount: list[str]  # names of items left out for want of an amount or a rate


@dataclass(frozen=True, slots=True)
class MonthOutlook:
    month: date  # the first day of the month
    today: date
    currency: str
    status: str  # "current", "past" or "future"
    received: Money
    spent: Money
    moved: Money  # main account to the user's other wallets, not cards
    net_so_far: Money  # received less spent
    items: list[OutlookItem]  # from today (or the first of a future month) to month end
    expected_in: Money
    expected_out: Money
    no_amount: list[str]
    projected_net: Money  # received + expected in - spent - moved - expected out
    projected_net_before_moves: Money  # the same, leaving out what moved to other wallets
    adjustments: list[Adjustment]
    adjustments_total: Money
    overall: Money  # projected_net + adjustments
    headroom: Money  # more everyday spending that keeps overall at zero or above (>= 0)
    shortfall: Money  # how far below zero overall is (>= 0)
    unconverted: list[Money]  # logged foreign amounts with no rate, left out

    @property
    def last_day(self) -> date:
        return next_month_start(self.month) - timedelta(days=1)


def plain(amount: Money, *, signed: bool = False) -> str:
    """ "4,798.00", no currency code (the home currency is said once); "+4,798.00" if signed."""
    shown = amount.amount.quantize(Decimal(1).scaleb(-minor_units(amount.currency)))
    text = f"{abs(shown):,}"
    if shown < 0:
        return f"-{text}"
    return f"+{text}" if signed else text


def sum_expected(items: Iterable[OutlookItem], currency: str) -> Expectations:
    """Expected money in and out, and the names of items with no amount."""
    money_in, money_out = Money.zero(currency), Money.zero(currency)
    missing: list[str] = []
    for item in items:
        if item.amount is None:
            if item.name not in missing:
                missing.append(item.name)
        elif item.direction is Direction.IN:
            money_in = money_in + item.amount
        elif item.direction is Direction.OUT:
            money_out = money_out + item.amount
    return Expectations(money_in, money_out, missing)


def items_of(found: Sequence[tuple[date, Expected]]) -> list[OutlookItem]:
    """Expected items by day, then name, with their own-currency amount when it differs."""
    return sorted(
        (
            OutlookItem(
                day,
                e.kind,
                e.name,
                e.direction,
                e.home,
                e.amount
                if e.amount is not None and e.home is not None and e.amount != e.home
                else None,
            )
            for day, e in found
        ),
        key=lambda i: (i.day, i.name),
    )


def parse_adjustment(text: str, label: str, currency: str) -> Adjustment:
    """An amount the user mentioned, signed ("+2,308.42", "-500", "4000 + 798"), as exact money.
    Written arithmetic in it is worked out here, not by the model."""
    result = calculate(text)
    amount = Money(result.rounded, currency)
    return Adjustment(label.strip()[:60] or "adjustment", amount)


def build_outlook(
    *,
    month: date,
    today: date,
    currency: str,
    received: Money,
    spent: Money,
    moved: Money,
    items: list[OutlookItem],
    adjustments: Sequence[Adjustment] = (),
    unconverted: Sequence[Money] = (),
) -> MonthOutlook:
    """The month's figures from its parts. Pure: all the arithmetic is here."""
    expected = sum_expected(items, currency)
    first = month_start(month)
    this_month = month_start(today)
    status = "current" if first == this_month else ("past" if first < this_month else "future")
    zero = Money.zero(currency)
    adjusted = zero
    for a in adjustments:
        adjusted = adjusted + a.amount
    projected_before_moves = received + expected.money_in - spent - expected.money_out
    projected = projected_before_moves - moved
    overall = projected + adjusted
    return MonthOutlook(
        month=first,
        today=today,
        currency=currency,
        status=status,
        received=received,
        spent=spent,
        moved=moved,
        net_so_far=received - spent,
        items=items,
        expected_in=expected.money_in,
        expected_out=expected.money_out,
        no_amount=expected.no_amount,
        projected_net=projected,
        projected_net_before_moves=projected_before_moves,
        adjustments=list(adjustments),
        adjustments_total=adjusted,
        overall=overall,
        headroom=overall if overall.is_positive else zero,
        shortfall=-overall if overall < zero else zero,
        unconverted=list(unconverted),
    )


def parse_month(text: str | None, today: date) -> date:
    """The first day of the month asked for ("2026-08"); this month when none is given."""
    if text is None or not text.strip():
        return month_start(today)
    try:
        year, month = text.strip().split("-")[:2]
        first = date(int(year), int(month), 1)
    except ValueError as exc:
        raise InvalidInput("give the month as YYYY-MM, like 2026-08") from exc
    ahead = (first.year - today.year) * 12 + first.month - today.month
    if ahead > MAX_MONTHS_AHEAD:
        raise InvalidInput(f"at most {MAX_MONTHS_AHEAD} months ahead")
    return first


async def month_outlook(
    uow: UowFactory,
    rates: RateSource,
    user: User,
    *,
    now: datetime,
    month: str | None = None,
    adjustments: Sequence[tuple[str, str]] = (),
) -> MonthOutlook:
    """The outlook for ``month`` (YYYY-MM; this month by default), with ``adjustments`` as
    (amount, label) pairs added to the overall figure."""
    if len(adjustments) > MAX_ADJUSTMENTS:
        raise InvalidInput(f"at most {MAX_ADJUSTMENTS} adjustments")
    tz = ZoneInfo(user.timezone)
    home = user.home_currency
    today = now.astimezone(tz).date()
    first = parse_month(month, today)
    start, end = month_range(user, datetime.combine(first, time(12), tzinfo=tz))
    figures = await wallet_figures(uow, rates, user, start, end)

    items: list[OutlookItem] = []
    last_day = next_month_start(first) - timedelta(days=1)
    if last_day >= today:
        # Today's unpaid items count as still due; payday only from tomorrow (today's may
        # be logged already, and is then in what was received): as Home's left to spend.
        found = await expected_between(uow, rates, user, max(first, today), last_day, now=now)
        items = items_of(found)
    return build_outlook(
        month=first,
        today=today,
        currency=home,
        received=figures.income,
        spent=figures.spent,
        moved=figures.total_out - figures.spent,
        items=items,
        adjustments=[parse_adjustment(a, label, home) for a, label in adjustments],
        unconverted=figures.unconverted,
    )
