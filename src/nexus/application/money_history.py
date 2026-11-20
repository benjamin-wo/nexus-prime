"""What the user has saved, month by month, and what that says about what they could save.

This is the arithmetic behind "how much do I save per month?", "what are my savings for
previous months?" and "how much should I be saving?". The model must not stitch it together
from ledger queries and add it up in its head, so it is done here, exactly, in the home
currency and the user's timezone, from the same month figures Home and ``month_outlook`` use
(``month_figures``), so the totals match the app to the cent:

- a month's ``received`` and ``spent`` are its totals (money between the user's own wallets is
  neither); ``net`` is received less spent, and that net is what "saved" means.
- ``moved`` is what went from the main account to the user's other wallets (savings,
  investments; not cards), as in ``month_outlook``. It is already part of the net, not on top.
- ``savings_rate`` is net over received (0.24 is 24%); None when nothing was received.
- the months are the last ``months`` full ones (6 by default, at most 12), oldest first, then
  the current month to date, marked partial. Months before the user's first confirmed entry
  are left out: there is nothing to say about them.
- the summary covers full months only, and only those with something logged: a month with no
  entries at all is a gap in the ledger, not a month in which the user saved nothing, so it is
  listed but left out of the averages. A part-month says little about a month, so it is too.
  It gives the average net, received and spent, the average saving rate (total net over total
  received, so a month with little income weighs little), the best and worst month by net, and
  how many months that is. With fewer than 2 full months it is one figure, not a pattern.
- the guide for "how much could I save" has, from the same months: the average spent, the
  user's usual salary (as they set it; None when they haven't), 20% of it (a common rule of
  thumb, a benchmark to set beside their own figures, not advice), and their average net as a
  share of the usual salary.

None of this is an account balance, and it is not advice: the words are the model's.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application.fx import RateSource
from nexus.application.ports import LedgerQuery, SortField, UnitOfWork
from nexus.application.wallet_figures import month_figures
from nexus.domain.ledger import TransactionStatus, User
from nexus.domain.money import Money, minor_units
from nexus.domain.planning import month_start

type UowFactory = Callable[[], UnitOfWork]

DEFAULT_MONTHS = 6
MAX_MONTHS = 12
# The common rule of thumb the guide sets beside the user's own figures.
BENCHMARK_RATE = Decimal("0.20")


@dataclass(frozen=True, slots=True)
class MonthFigures:
    """One month's totals as ``month_figures`` reports them, before any arithmetic here."""

    month: date  # the first day of the month
    received: Money
    spent: Money
    moved: Money  # main account to the user's other wallets, not cards
    unconverted: list[Money]  # logged foreign amounts with no rate, left out of the above


@dataclass(frozen=True, slots=True)
class MonthSaving:
    month: date  # the first day of the month
    partial: bool  # the current month, still going
    received: Money
    spent: Money
    moved: Money  # already part of net, not on top of it
    net: Money  # received less spent
    savings_rate: Decimal | None  # net / received (0.24 is 24%); None when nothing came in
    unconverted: list[Money]

    @property
    def logged(self) -> bool:
        """Whether the ledger has anything for the month: a month with nothing is a gap."""
        has_money = bool(self.received.amount or self.spent.amount or self.moved.amount)
        return has_money or bool(self.unconverted)


@dataclass(frozen=True, slots=True)
class SavingsSummary:
    """Full months with something logged, over which the averages are taken."""

    months: int
    average_received: Money
    average_spent: Money
    average_net: Money
    average_savings_rate: Decimal | None  # total net / total received; None without income
    best: MonthSaving  # highest net
    worst: MonthSaving  # lowest net


@dataclass(frozen=True, slots=True)
class SavingsGuide:
    """The figures to set a suggestion beside: theirs, and the 20% rule of thumb."""

    average_spent: Money
    usual_salary: Money | None  # as the user set it, in the home currency; None when not set
    benchmark: Money | None  # BENCHMARK_RATE of the usual salary
    average_net_share_of_salary: Decimal | None  # average net / usual salary


@dataclass(frozen=True, slots=True)
class MoneyHistory:
    today: date
    currency: str
    first_day: date | None  # the day of the user's first confirmed entry; None without any
    months: list[MonthSaving]  # oldest first; the current month last, partial
    summary: SavingsSummary | None  # None when no full month has anything logged
    guide: SavingsGuide | None  # None without a summary


def clamp_months(months: int) -> int:
    return max(1, min(months, MAX_MONTHS))


def months_covered(today: date, first_day: date | None, months: int) -> list[date]:
    """The first days of the last ``months`` full months, oldest first, that are not before
    the month of ``first_day``, then the current month. Empty without a first entry, and when
    the first entry is still ahead."""
    if first_day is None:
        return []
    current = month_start(today)
    earliest = month_start(first_day)
    if earliest > current:
        return []
    found: list[date] = []
    first = current
    for _ in range(clamp_months(months)):
        first = month_start(first - timedelta(days=1))
        if first < earliest:
            break
        found.append(first)
    found.reverse()
    return [*found, current]


def _round(value: Decimal, currency: str) -> Money:
    unit = Decimal(1).scaleb(-minor_units(currency))
    return Money(value.quantize(unit, rounding=ROUND_HALF_UP), currency)


def _average(amounts: Sequence[Money], currency: str) -> Money:
    total = sum((m.amount for m in amounts), Decimal(0))
    return _round(total / len(amounts), currency)


def build_money_history(
    *,
    today: date,
    currency: str,
    first_day: date | None,
    figures: Sequence[MonthFigures],
    usual_salary: Money | None = None,
) -> MoneyHistory:
    """The history from each month's figures. Pure: all the arithmetic is here. A month
    counts as partial when it is the one ``today`` falls in."""
    this_month = month_start(today)
    months = []
    for f in sorted(figures, key=lambda f: f.month):
        net = f.received - f.spent
        months.append(
            MonthSaving(
                month=f.month,
                partial=f.month == this_month,
                received=f.received,
                spent=f.spent,
                moved=f.moved,
                net=net,
                savings_rate=net.amount / f.received.amount if f.received.is_positive else None,
                unconverted=list(f.unconverted),
            )
        )
    used = [m for m in months if not m.partial and m.logged]
    if not used:
        return MoneyHistory(today, currency, first_day, months, None, None)

    received = sum((m.received.amount for m in used), Decimal(0))
    net_total = sum((m.net.amount for m in used), Decimal(0))
    summary = SavingsSummary(
        months=len(used),
        average_received=_average([m.received for m in used], currency),
        average_spent=_average([m.spent for m in used], currency),
        average_net=_average([m.net for m in used], currency),
        average_savings_rate=net_total / received if received > 0 else None,
        best=max(used, key=lambda m: m.net.amount),
        worst=min(used, key=lambda m: m.net.amount),
    )
    salary = usual_salary if usual_salary is not None and usual_salary.is_positive else None
    guide = SavingsGuide(
        average_spent=summary.average_spent,
        usual_salary=salary,
        benchmark=_round(salary.amount * BENCHMARK_RATE, currency) if salary else None,
        average_net_share_of_salary=summary.average_net.amount / salary.amount if salary else None,
    )
    return MoneyHistory(today, currency, first_day, months, summary, guide)


async def money_history(
    uow: UowFactory,
    rates: RateSource,
    user: User,
    *,
    now: datetime,
    months: int = DEFAULT_MONTHS,
) -> MoneyHistory:
    """The last ``months`` full months (6 by default, at most 12) that the ledger covers, and
    the current month so far, with the summary and the guide."""
    tz = ZoneInfo(user.timezone)
    home = user.home_currency
    today = now.astimezone(tz).date()
    async with uow() as tx:
        # The first confirmed, undeleted entry: months before it are not in the history.
        first = await tx.ledger.list_transactions(
            user.id,
            LedgerQuery(
                status=TransactionStatus.CONFIRMED,
                sort=SortField.OCCURRED_AT,
                descending=False,
                limit=1,
            ),
        )
        schedule = await tx.planning.get_salary_schedule(user.id)
    first_day = first.items[0].occurred_at.astimezone(tz).date() if first.items else None

    figures: list[MonthFigures] = []
    for begins in months_covered(today, first_day, months):
        month = await month_figures(
            uow, rates, user, now=datetime.combine(begins, time(12), tzinfo=tz)
        )
        figures.append(
            MonthFigures(
                month=begins,
                received=month.income,
                spent=month.spent,
                moved=month.total_out - month.spent,
                unconverted=month.unconverted,
            )
        )

    usual: Money | None = None
    if schedule is not None and schedule.baseline is not None:
        found = await fx.rates_for(rates, home, [(schedule.baseline.currency, today)])
        usual = fx.convert(schedule.baseline, today, home, found).home
    return build_money_history(
        today=today, currency=home, first_day=first_day, figures=figures, usual_salary=usual
    )
