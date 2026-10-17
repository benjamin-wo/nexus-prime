"""What the user put away and what left their Spending wallet, from their wallet moves.

A move between two of the user's wallets is never spending and never income, so the
usual totals leave it out. These numbers add it back where it answers a question:

- put away: money moved into savings or investment wallets from anywhere else, less money
  moved back out of them to anywhere else. Between two savings or investment wallets
  it nets to nothing.
- total out: spending, plus money moved from Spending to any wallet other than a card
  (paying a card is not extra: the card's purchases are already spending).
- saving rate: put away as a share of the month's income.
- left to spend: the month's income (received, plus salary still due) less what has gone
  out so far and what is still due out before month end.

Everything is in the home currency, converted the way ``summarize_in_home`` converts.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application import transactions as tx_cases
from nexus.application.budgets import budget_statuses
from nexus.application.cashflow import ExpectedKind, expected_between
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, User, WalletKind, require_aware
from nexus.domain.money import Money
from nexus.domain.planning import Cadence, month_start, next_month_start

type UowFactory = Callable[[], UnitOfWork]

# Wallets whose money counts as put away.
PUT_AWAY_KINDS = frozenset({WalletKind.SAVINGS, WalletKind.INVESTMENT})


@dataclass(frozen=True, slots=True)
class WalletFigures:
    start: datetime
    end: datetime
    currency: str
    put_away: Money  # net into savings and investments, from outside them
    total_out: Money  # spent, plus moved from Spending to anything but a card
    spent: Money  # as ``summarize_in_home`` reports it
    income: Money  # as ``summarize_in_home`` reports it
    saving_rate: Decimal | None  # put_away / income (0.24 is 24%); None without income
    # Foreign amounts with no exchange rate, left out of the figures above.
    unconverted: list[Money]


def month_range(user: User, now: datetime) -> tuple[datetime, datetime]:
    """The calendar month ``now`` falls in, in the user's timezone: [start, end)."""
    tz = ZoneInfo(user.timezone)
    first: date = month_start(now.astimezone(tz).date())
    return (
        datetime.combine(first, time(), tzinfo=tz),
        datetime.combine(next_month_start(first), time(), tzinfo=tz),
    )


async def wallet_figures(
    uow: UowFactory, rates: RateSource, user: User, start: datetime, end: datetime
) -> WalletFigures:
    """The figures for [start, end): confirmed, undeleted entries only."""
    require_aware(start, field_name="start")
    require_aware(end, field_name="end")
    if start >= end:
        raise InvalidInput("start must be before end")
    home = user.home_currency
    summary = await tx_cases.summarize_in_home(uow(), rates, user, start, end)
    async with uow() as tx:
        kinds: dict[UUID, WalletKind] = {
            w.id: w.kind for w in await tx.ledger.list_wallets(user.id)
        }
        moves = await tx.ledger.moves_by_day(user.id, start, end, user.timezone)
    found = await fx.rates_for(rates, home, ((m.total.currency, m.day) for m in moves))

    put_away = Money.zero(home)
    moved_out = Money.zero(home)  # from Spending to anything but a card
    unconverted = list(summary.out.unconverted) + list(summary.income.unconverted)
    for m in moves:
        origin, target = kinds.get(m.from_wallet_id), kinds.get(m.to_wallet_id)
        into = target in PUT_AWAY_KINDS and origin not in PUT_AWAY_KINDS
        back = origin in PUT_AWAY_KINDS and target not in PUT_AWAY_KINDS
        leaves = origin is WalletKind.SPENDING and target is not WalletKind.CARD
        if not (into or back or leaves):
            continue
        amount = fx.convert(m.total, m.day, home, found).home
        if amount is None:
            unconverted.append(m.total)
            continue
        if into:
            put_away = put_away + amount
        elif back:
            put_away = put_away - amount
        if leaves:
            moved_out = moved_out + amount

    spent, income = summary.out.total, summary.income.total
    rate = put_away.amount / income.amount if income.amount > 0 else None
    return WalletFigures(
        start=start,
        end=end,
        currency=home,
        put_away=put_away,
        total_out=spent + moved_out,
        spent=spent,
        income=income,
        saving_rate=rate,
        unconverted=_by_currency(unconverted),
    )


async def month_figures(
    uow: UowFactory, rates: RateSource, user: User, *, now: datetime
) -> WalletFigures:
    """The figures for the month ``now`` falls in, in the user's timezone."""
    start, end = month_range(user, now)
    return await wallet_figures(uow, rates, user, start, end)


async def put_away(
    uow: UowFactory, rates: RateSource, user: User, start: datetime, end: datetime
) -> Money:
    return (await wallet_figures(uow, rates, user, start, end)).put_away


async def total_out(
    uow: UowFactory, rates: RateSource, user: User, start: datetime, end: datetime
) -> Money:
    return (await wallet_figures(uow, rates, user, start, end)).total_out


def _by_currency(amounts: list[Money]) -> list[Money]:
    merged: dict[str, Money] = {}
    for m in amounts:
        merged[m.currency] = merged[m.currency] + m if m.currency in merged else m
    return [merged[c] for c in sorted(merged)]


# --- left to spend ------------------------------------------------------------------

# How many complete months back "usual income" looks when there's no usual salary.
USUAL_INCOME_MONTHS = 3

# Occurrences per month of a repeating payment (a one-off has none).
_PER_MONTH = {
    Cadence.WEEKLY: Decimal(52) / 12,
    Cadence.MONTHLY: Decimal(1),
    Cadence.YEARLY: Decimal(1) / 12,
}
_UNIT = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class MonthPlan:
    """Where the month stands, in the home currency.

    ``left_to_spend = income - total_out - still_due_out``; every part is shown so the
    sum can be checked. ``income`` is received so far plus salary still due this month.
    """

    currency: str
    total_out: Money  # so far this month: spent, plus moved from Spending to non-cards
    still_due_out: Money  # bills (spending or not), subscriptions and trip set-asides ahead
    income: Money  # received this month so far, plus salary still due before month end
    left_to_spend: Money  # can be negative
    budget_left: Money | None  # the overall budget less spending so far; None without one
    tighter: Literal["budget", "left_to_spend"] | None  # the lower of the two; None w/o budget
    plan_warning: str | None  # the budget plus scheduled moves outgrow usual income
    # Names of scheduled items left out for want of an amount or a rate.
    skipped: list[str]


async def month_plan(uow: UowFactory, rates: RateSource, user: User, *, now: datetime) -> MonthPlan:
    """Left to spend for the month ``now`` falls in, and the plan check."""
    home = user.home_currency
    figures = await month_figures(uow, rates, user, now=now)
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    last_day = next_month_start(today) - timedelta(days=1)

    skipped: list[str] = []
    due_out = Money.zero(home)
    salary_due = Money.zero(home)
    # Today's unpaid items count as still due; payday only from tomorrow (today's may be
    # logged already, and is then in the income received).
    for _, item in await expected_between(uow, rates, user, today, last_day, now=now):
        if item.home is None:
            if item.name not in skipped:
                skipped.append(item.name)
        elif item.kind is ExpectedKind.SALARY:
            salary_due = salary_due + item.home
        elif item.direction is Direction.OUT:
            due_out = due_out + item.home

    income = figures.income + salary_due
    left = income - figures.total_out - due_out

    overall = next(
        (s for s in await budget_statuses(uow, rates, user, now=now) if s.budget.is_overall),
        None,
    )
    budget_left = overall.remaining if overall else None
    tighter: Literal["budget", "left_to_spend"] | None = None
    if budget_left is not None:
        tighter = "budget" if budget_left < left else "left_to_spend"

    warning = None
    if overall is not None:
        warning = await _plan_warning(
            uow, rates, user, overall.budget.limit, today=today, now=now, skipped=skipped
        )
    return MonthPlan(
        currency=home,
        total_out=figures.total_out,
        still_due_out=due_out,
        income=income,
        left_to_spend=left,
        budget_left=budget_left,
        tighter=tighter,
        plan_warning=warning,
        skipped=skipped,
    )


async def _plan_warning(
    uow: UowFactory,
    rates: RateSource,
    user: User,
    budget: Money,
    *,
    today: date,
    now: datetime,
    skipped: list[str],
) -> str | None:
    """Text when the budget plus the month's worth of scheduled moves (repeating bills that
    aren't spending: investing, saving) is more than the usual income."""
    home = user.home_currency
    async with uow() as tx:
        bills = [b for b in await tx.planning.list_bills(user.id) if not b.spending]
        schedule = await tx.planning.get_salary_schedule(user.id)
    monthly = Decimal(0)
    wanted = {(b.amount.currency, today) for b in bills if b.amount is not None}
    if schedule is not None and schedule.baseline is not None:
        wanted.add((schedule.baseline.currency, today))
    found = await fx.rates_for(rates, home, wanted)
    for bill in bills:
        per_month = _PER_MONTH.get(bill.cadence)
        if per_month is None:
            continue  # a one-off isn't a monthly commitment
        converted = (
            fx.convert(bill.amount, today, home, found).home if bill.amount is not None else None
        )
        if converted is None:
            if bill.name not in skipped:
                skipped.append(bill.name)
            continue
        monthly += converted.amount * per_month
    if monthly <= 0:
        return None
    moves = Money(monthly.quantize(_UNIT), home)

    usual = None
    if schedule is not None and schedule.baseline is not None:
        usual = fx.convert(schedule.baseline, today, home, found).home
    if usual is None:
        usual = await _average_income(uow, rates, user, now)
    if usual is None or budget + moves <= usual:
        return None
    return (
        f"A {budget} budget plus {moves} of scheduled moves is more than your usual {usual} income."
    )


async def _average_income(
    uow: UowFactory, rates: RateSource, user: User, now: datetime
) -> Money | None:
    """Average income of the last few complete months that had any; None with no history."""
    first = month_start(now.astimezone(ZoneInfo(user.timezone)).date())
    tz = ZoneInfo(user.timezone)
    totals: list[Money] = []
    for _ in range(USUAL_INCOME_MONTHS):
        begins = first
        first = month_start(first - timedelta(days=1))
        summary = await tx_cases.summarize_in_home(
            uow(),
            rates,
            user,
            datetime.combine(first, time(), tzinfo=tz),
            datetime.combine(begins, time(), tzinfo=tz),
        )
        if summary.income.total.is_positive:
            totals.append(summary.income.total)
    if not totals:
        return None
    total = Decimal(0)
    for t in totals:
        total += t.amount
    return Money((total / len(totals)).quantize(_UNIT), user.home_currency)
