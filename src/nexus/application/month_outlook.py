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
- with an overall budget: ``budget_left`` is the limit less what was spent against it (as
  Home shows it, so it can be negative); ``spending_due`` is the still-expected payments that
  will count as spending when paid (bills that are spending, subscriptions; not moves to the
  user's own wallets, trip set-asides or payday); ``budget_left_after_due`` is the first less
  the second. ``tighter`` says which is lower, that or ``overall``, and by how much.
- ``budget_room`` is the answer to "how much can I spend / can I afford it" when there is an
  overall budget: ``budget_left_after_due`` less the user's purchases, never the projection. Only
  the negative adjustments (a purchase they ask about, spending they plan) come off it, as
  ``budget_adjustments``; a positive one (a carry-over, money they expect) is cash, not budget,
  so it never adds to the room.
- ``pay_not_yet_in`` is the part of the projection that is payday still to come (items of kind
  salary with an amount) and ``next_pay_day`` its first date: pay not received is not money to
  spend, so the reply has to say when the projection counts it.

- per day, for this month and future ones: ``days_left`` counts today through month end (a
  future month: all its days). ``budget_room_per_day`` is the budget room over them, or, with no
  budget, ``headroom_per_day`` is the headroom (which counts pay not yet in); each also over
  the days left from tomorrow (this month only). With no room it is zero: say "no room", never
  a spend per day. ``everyday_per_day`` is the pace so far: spending from the 1st to today
  (a month already over: all of it), leaving out the scheduled payments and subscriptions set up
  in Nexus that can be found in it (a logged expense of the same amount, under a name that shares
  a word with the bill's, once per due date; split ones are not left out). Rent is not
  everyday spending, and the room per day already has what is due taken off. Without a match
  nothing is left out, and ``spent_per_day`` is everything. ``room_vs_pace`` says, in code, how
  the room per day compares with the pace (percent and a band), so no one compares in their head.

Everyday spending for the rest of the month is not forecast, and none of this is an
account balance. A month already over has actuals only.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application.budgets import budget_statuses
from nexus.application.cashflow import Expected, ExpectedKind, expected_between
from nexus.application.fx import RateSource
from nexus.application.ports import LedgerQuery, UnitOfWork
from nexus.application.wallet_figures import month_range, wallet_figures
from nexus.domain.calc import calculate
from nexus.domain.duplicates import shares_a_name
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, TransactionStatus, User
from nexus.domain.money import Money, minor_units
from nexus.domain.planning import due_dates, month_start, next_month_start
from nexus.domain.recurring import SubscriptionStatus, next_charge

type UowFactory = Callable[[], UnitOfWork]

MAX_ADJUSTMENTS = 20
MAX_MONTHS_AHEAD = 24
# The room per day against the pace so far, in percent: under the first is "far below", under
# the second "below", up to the third "about", under the fourth "above", from it "far above".
FAR_BELOW_PERCENT = 50
BELOW_PERCENT = 90
ABOUT_PERCENT = 110
FAR_ABOVE_PERCENT = 200
# How many of a month's expenses are looked through for scheduled payments.
_SCHEDULED_POOL = 2_000

type Band = Literal["far_below", "below", "about", "above", "far_above"]


@dataclass(frozen=True, slots=True)
class OutlookItem:
    day: date
    kind: ExpectedKind
    name: str
    direction: Direction
    amount: Money | None  # in the home currency; None: no amount set, or no rate
    original: Money | None  # in its own currency, when that isn't the home currency
    spending: bool  # will count as spending (against budgets) once it happens


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
    # The overall budget, None when the user has none. Limit, spent and left are for the month
    # asked for (spent against today's limit; a future month has nothing spent yet).
    budget_limit: Money | None
    budget_spent: Money | None
    budget_left: Money | None  # limit - spent, as Home shows it: negative when over
    # The rest are None without a budget, and for a month already over (nothing is due).
    spending_due: Money | None  # still-expected payments that count as spending
    budget_left_after_due: Money | None  # budget_left - spending_due: negative when it'll be over
    tighter: Literal["budget", "outlook"] | None  # lower of budget_left_after_due and overall
    tighter_by: Money | None  # how far apart they are (>= 0)
    # With an overall budget, for this month or a future one: what the budget leaves to spend,
    # budget_left_after_due + budget_adjustments (negative: over). The answer to "how much can I
    # spend", unlike the projection, which counts pay not yet received.
    budget_room: Money | None
    budget_adjustments: Money | None  # the negative adjustments only (<= 0), already in the room
    # Payday still to come (kind salary, with an amount), counted in expected_in and so in the
    # projection. Zero, with no date, when none is left (and for a month already over).
    pay_not_yet_in: Money
    next_pay_day: date | None
    # Per day. Days: today through month end (a future month: all of it), None for a month
    # already over; and the days elapsed, 1st through today (a past month: all of it), None for a
    # future month.
    days_left: int | None
    days_elapsed: int | None
    # Of ``spent``, the scheduled payments and subscriptions found in it (zero when none), by name.
    scheduled_spent: Money
    scheduled_names: list[str]
    everyday_spent: Money  # spent less scheduled_spent
    spent_per_day: Money | None  # spent over the days elapsed, everything
    everyday_per_day: Money | None  # the pace: everyday_spent over the days elapsed
    # The room over the days left (zero when there is no room), and over the days left from
    # tomorrow (this month only, when more than one day is left). The budget's room with a
    # budget, the headroom (which counts pay not yet in) without one; None when not applicable.
    budget_room_per_day: Money | None
    budget_room_per_day_from_tomorrow: Money | None
    headroom_per_day: Money | None
    headroom_per_day_from_tomorrow: Money | None
    # The room per day as a share of the pace, whole percent, and its band; None with no pace
    # (nothing spent yet, or no month so far) or no per-day room.
    room_vs_pace_percent: int | None
    room_vs_pace: Band | None

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


def per_day(total: Money, days: int) -> Money:
    """``total`` over ``days``, to the currency's minor unit, halves rounded up."""
    unit = Decimal(1).scaleb(-minor_units(total.currency))
    return Money((total.amount / days).quantize(unit, rounding=ROUND_HALF_UP), total.currency)


def room_per_day(room: Money, days: int) -> Money:
    """What ``room`` leaves per day: zero when there is no room, never a negative spend."""
    return per_day(room, days) if room.is_positive else Money.zero(room.currency)


def compare_pace(room_day: Money, pace: Money) -> tuple[int, Band] | None:
    """The room per day as a whole percent of the pace, and its band. None with no pace."""
    if not pace.is_positive:
        return None
    percent = int((room_day.amount / pace.amount * 100).quantize(Decimal(1), ROUND_HALF_UP))
    if percent < FAR_BELOW_PERCENT:
        return percent, "far_below"
    if percent < BELOW_PERCENT:
        return percent, "below"
    if percent <= ABOUT_PERCENT:
        return percent, "about"
    return percent, "above" if percent < FAR_ABOVE_PERCENT else "far_above"


@dataclass(frozen=True, slots=True)
class Scheduled:
    """A scheduled payment or subscription set up in Nexus, to look for in the month's spending:
    ``times`` due dates in the month."""

    name: str
    amount: Money
    times: int


@dataclass(frozen=True, slots=True)
class Spend:
    """One logged expense of the month, as logged and in the home currency."""

    counterparty: str | None
    amount: Money
    home: Money


def scheduled_in(
    planned: Iterable[Scheduled], spends: Sequence[Spend], currency: str
) -> tuple[Money, list[str]]:
    """The scheduled payments found in the month's spending, and their names. A payment is found
    in an expense of the same amount, under a name that shares a word with its own; each expense
    is used once, and a payment at most as often as it falls due."""
    total = Money.zero(currency)
    names: list[str] = []
    used: set[int] = set()
    for p in planned:
        left = p.times
        for i, spend in enumerate(spends):
            if left == 0:
                break
            if (
                i not in used
                and spend.amount == p.amount
                and shares_a_name(spend.counterparty, p.name)
            ):
                used.add(i)
                left -= 1
                total = total + spend.home
                if p.name not in names:
                    names.append(p.name)
    return total, names


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


def spending_due(items: Iterable[OutlookItem], currency: str) -> Money:
    """Expected payments with an amount that will count as spending when they happen."""
    total = Money.zero(currency)
    for item in items:
        if item.direction is Direction.OUT and item.spending and item.amount is not None:
            total = total + item.amount
    return total


def pay_still_to_come(items: Iterable[OutlookItem], currency: str) -> tuple[Money, date | None]:
    """The pay (salary items with an amount) still expected, and the day of the first."""
    total = Money.zero(currency)
    first: date | None = None
    for item in items:
        if (
            item.kind is ExpectedKind.SALARY
            and item.direction is Direction.IN
            and item.amount is not None
        ):
            total = total + item.amount
            first = item.day if first is None else min(first, item.day)
    return total, first


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
                e.spending,
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
    budget_limit: Money | None = None,
    budget_spent: Money | None = None,
    scheduled_spent: Money | None = None,
    scheduled_names: Sequence[str] = (),
) -> MonthOutlook:
    """The month's figures from its parts. Pure: all the arithmetic is here. The budget
    figures are worked out only when both ``budget_limit`` and ``budget_spent`` are given.
    ``scheduled_spent`` is the part of ``spent`` that is scheduled payments (``scheduled_in``)."""
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
    budget_left = None
    due = after_due = tighter_by = None
    tighter: Literal["budget", "outlook"] | None = None
    room = purchases = None
    if budget_limit is not None and budget_spent is not None:
        budget_left = budget_limit - budget_spent
        if status != "past":
            due = spending_due(items, currency)
            after_due = budget_left - due
            # Compared with ``overall`` (not the clamped headroom), so a shortfall counts in full.
            tighter = "budget" if after_due < overall else "outlook"
            tighter_by = after_due - overall if after_due > overall else overall - after_due
            purchases = zero
            for a in adjustments:
                if a.amount < zero:
                    purchases = purchases + a.amount
            room = after_due + purchases
    else:
        budget_limit = budget_spent = None
    pay, next_pay_day = pay_still_to_come(items, currency)

    last_day = next_month_start(first) - timedelta(days=1)
    month_days = (last_day - first).days + 1
    days_left = (
        None
        if status == "past"
        else (month_days if status == "future" else (last_day - today).days + 1)
    )
    days_elapsed = (
        None
        if status == "future"
        else (month_days if status == "past" else (today - first).days + 1)
    )
    scheduled = zero if scheduled_spent is None else scheduled_spent.min(spent)
    everyday = spent - scheduled
    spent_day = everyday_day = None
    if days_elapsed is not None:
        spent_day, everyday_day = per_day(spent, days_elapsed), per_day(everyday, days_elapsed)
    # The room over the days left, and over the days left from tomorrow (this month only).
    tomorrow = (
        days_left - 1 if status == "current" and days_left is not None and days_left > 1 else None
    )
    budget_day = budget_day_tomorrow = headroom_day = headroom_day_tomorrow = None
    compared: tuple[int, Band] | None = None
    if days_left is not None:
        if room is not None:
            budget_day = room_per_day(room, days_left)
            budget_day_tomorrow = room_per_day(room, tomorrow) if tomorrow else None
            if everyday_day is not None:
                compared = compare_pace(budget_day, everyday_day)
        elif budget_limit is None:
            headroom = overall if overall.is_positive else zero
            headroom_day = room_per_day(headroom, days_left)
            headroom_day_tomorrow = room_per_day(headroom, tomorrow) if tomorrow else None
            if everyday_day is not None:
                compared = compare_pace(headroom_day, everyday_day)
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
        budget_limit=budget_limit,
        budget_spent=budget_spent,
        budget_left=budget_left,
        spending_due=due,
        budget_left_after_due=after_due,
        tighter=tighter,
        tighter_by=tighter_by,
        budget_room=room,
        budget_adjustments=purchases,
        pay_not_yet_in=pay,
        next_pay_day=next_pay_day,
        days_left=days_left,
        days_elapsed=days_elapsed,
        scheduled_spent=scheduled,
        scheduled_names=list(scheduled_names) if scheduled.is_positive else [],
        everyday_spent=everyday,
        spent_per_day=spent_day,
        everyday_per_day=everyday_day,
        budget_room_per_day=budget_day,
        budget_room_per_day_from_tomorrow=budget_day_tomorrow,
        headroom_per_day=headroom_day,
        headroom_per_day_from_tomorrow=headroom_day_tomorrow,
        room_vs_pace_percent=compared[0] if compared else None,
        room_vs_pace=compared[1] if compared else None,
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


async def scheduled_spending(
    uow: UowFactory,
    rates: RateSource,
    user: User,
    first: date,
    until: date,
    tz: ZoneInfo,
) -> tuple[Money, list[str]]:
    """The scheduled payments and subscriptions set up in Nexus found in the user's expenses from
    ``first`` to ``until`` (a day of the same month): how much, in the home currency, and which.
    Expenses that were split or repaid are left out (what the user spent on them is not their
    amount), and so are bills with no amount: those are not found, so they stay in the pace."""
    home = user.home_currency
    last_day = next_month_start(first) - timedelta(days=1)
    async with uow() as tx:
        bills = await tx.planning.list_bills(user.id)
        subscriptions = await tx.planning.list_subscriptions(user.id)
        page = await tx.ledger.list_transactions(
            user.id,
            LedgerQuery(
                direction=Direction.OUT,
                status=TransactionStatus.CONFIRMED,
                start=datetime.combine(first, time(), tzinfo=tz),
                end=datetime.combine(until + timedelta(days=1), time(), tzinfo=tz),
                limit=_SCHEDULED_POOL,
            ),
        )
        shared = await tx.ledger.lineage(user.id, [t.id for t in page.items])
    planned = [
        Scheduled(b.name, b.amount, len(due_dates(b.anchor, b.cadence, first, last_day)))
        for b in bills
        if b.amount is not None and b.spending and b.wallet_id is None
    ]
    for sub in subscriptions:
        if sub.status is not SubscriptionStatus.ACTIVE:
            continue
        # Charges in the month: the last one if it was this month, and those after it.
        times = 1 if first <= sub.last_charged_on <= last_day else 0
        charge = next_charge(sub.cadence, sub.last_charged_on)
        while charge <= last_day:
            times += charge >= first
            charge = next_charge(sub.cadence, charge)
        planned.append(Scheduled(sub.name, sub.amount, times))
    mine = [t for t in page.items if t.id not in shared]
    found = await fx.rates_for(
        rates, home, ((t.amount.currency, t.occurred_at.astimezone(tz).date()) for t in mine)
    )
    spends = [
        Spend(t.counterparty, t.amount, home_amount)
        for t in mine
        if (
            home_amount := fx.convert(
                t.amount, t.occurred_at.astimezone(tz).date(), home, found
            ).home
        )
        is not None
    ]
    return scheduled_in([p for p in planned if p.times], spends, home)


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
    # The overall budget (None without one), spent against for the month asked for.
    overall_budget = next(
        (
            s
            for s in await budget_statuses(uow, rates, user, now=now, month=first)
            if s.budget.is_overall
        ),
        None,
    )
    # The scheduled payments among what was spent, for the pace (nothing for a month not begun).
    scheduled: tuple[Money, list[str]] | None = None
    if first <= today:
        scheduled = await scheduled_spending(uow, rates, user, first, min(today, last_day), tz)
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
        budget_limit=overall_budget.budget.limit if overall_budget else None,
        budget_spent=overall_budget.spent if overall_budget else None,
        scheduled_spent=scheduled[0] if scheduled else None,
        scheduled_names=scheduled[1] if scheduled else (),
    )
