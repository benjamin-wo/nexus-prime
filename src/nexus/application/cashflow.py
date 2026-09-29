"""The cash-flow calendar: net money movement per day, in the home currency.

Days so far show what was logged. Days ahead show what's expected: bills (unless
already marked paid), tracked subscriptions and payday. It shows movement only,
never a balance: Nexus doesn't know what's in the user's accounts.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, User
from nexus.domain.money import Money
from nexus.domain.planning import due_dates, paydays
from nexus.domain.recurring import SubscriptionStatus, next_charge

type UowFactory = Callable[[], UnitOfWork]

MAX_DAYS = 62  # about two months per request


class ExpectedKind(StrEnum):
    BILL = "bill"
    SUBSCRIPTION = "subscription"
    SALARY = "salary"


@dataclass(frozen=True, slots=True)
class Expected:
    kind: ExpectedKind
    name: str
    direction: Direction
    amount: Money | None  # None when the amount isn't known (a bill without one)
    home: Money | None  # in the home currency; None if unknown or no rate


@dataclass(frozen=True, slots=True)
class CashDay:
    day: date
    money_in: Money  # logged, in the home currency
    money_out: Money
    expected: list[Expected] = field(default_factory=list)

    @property
    def net(self) -> Money:
        return self.money_in - self.money_out

    @property
    def expected_net(self) -> Money:
        total = Money.zero(self.money_in.currency)
        for e in self.expected:
            if e.home is not None:
                total = total + e.home if e.direction is Direction.IN else total - e.home
        return total


@dataclass(frozen=True, slots=True)
class CashFlow:
    start: date
    end: date  # inclusive
    today: date
    currency: str
    days: list[CashDay]
    unconverted: list[Money]  # logged foreign amounts with no rate, left out of the days

    @property
    def logged_in(self) -> Money:
        return _sum((d.money_in for d in self.days), self.currency)

    @property
    def logged_out(self) -> Money:
        return _sum((d.money_out for d in self.days), self.currency)

    @property
    def expected_in(self) -> Money:
        return _sum(self._expected(Direction.IN), self.currency)

    @property
    def expected_out(self) -> Money:
        return _sum(self._expected(Direction.OUT), self.currency)

    def _expected(self, direction: Direction) -> list[Money]:
        return [
            e.home
            for d in self.days
            for e in d.expected
            if e.direction is direction and e.home is not None
        ]

    @property
    def unknown_amounts(self) -> int:
        """Expected items without a known amount (they're listed, not counted)."""
        return sum(1 for d in self.days for e in d.expected if e.home is None)


def _sum(amounts: Iterable[Money], currency: str) -> Money:
    total = Money.zero(currency)
    for m in amounts:
        total = total + m
    return total


async def cash_flow(
    uow: UowFactory, rates: RateSource, user: User, start: date, end: date, *, now: datetime
) -> CashFlow:
    if end < start:
        raise InvalidInput("the end date is before the start date")
    if (end - start).days + 1 > MAX_DAYS:
        raise InvalidInput(f"show at most {MAX_DAYS} days at a time")
    tz = ZoneInfo(user.timezone)
    home = user.home_currency
    today = now.astimezone(tz).date()
    zero = Money.zero(home)
    days = {start + timedelta(days=n): [zero, zero] for n in range((end - start).days + 1)}

    # What happened, up to today.
    unconverted: list[Money] = []
    last_logged = min(end, today)
    if start <= last_logged:
        async with uow() as tx:
            totals = await tx.ledger.totals_by_day(
                user.id,
                datetime.combine(start, time(), tzinfo=tz),
                datetime.combine(last_logged + timedelta(days=1), time(), tzinfo=tz),
                user.timezone,
            )
        found = await fx.rates_for(rates, home, ((t.total.currency, t.day) for t in totals))
        for t in totals:
            amount = fx.convert(t.total, t.day, home, found).home
            if amount is None:
                unconverted.append(t.total)
                continue
            slot = days[t.day]
            index = 0 if t.direction is Direction.IN else 1
            slot[index] = slot[index] + amount

    # What's expected, from today on.
    expected: dict[date, list[Expected]] = {d: [] for d in days}
    first_ahead = max(start, today)
    if first_ahead <= end:
        for day, item in await _expected(uow, user, first_ahead, end, today):
            expected[day].append(item)
    wanted = {
        (e.amount.currency, today)
        for items in expected.values()
        for e in items
        if e.amount is not None
    }
    found = await fx.rates_for(rates, home, wanted)
    for items in expected.values():
        for n, e in enumerate(items):
            if e.amount is not None:
                items[n] = Expected(
                    e.kind,
                    e.name,
                    e.direction,
                    e.amount,
                    fx.convert(e.amount, today, home, found).home,
                )

    return CashFlow(
        start=start,
        end=end,
        today=today,
        currency=home,
        days=[
            CashDay(d, money_in, money_out, sorted(expected[d], key=lambda e: e.name))
            for d, (money_in, money_out) in days.items()
        ],
        unconverted=unconverted,
    )


async def _expected(
    uow: UowFactory, user: User, start: date, end: date, today: date
) -> list[tuple[date, Expected]]:
    found: list[tuple[date, Expected]] = []
    async with uow() as tx:
        bills = await tx.planning.list_bills(user.id)
        paid: set[tuple[UUID, date]] = set()
        for bill in bills:
            for o in await tx.planning.occurrences(user.id, bill.id, start):
                if o.paid_at is not None:
                    paid.add((bill.id, o.due))
        subscriptions = await tx.planning.list_subscriptions(user.id)
        schedule = await tx.planning.get_salary_schedule(user.id)

    for bill in bills:
        for due in due_dates(bill.anchor, bill.cadence, start, end):
            if (bill.id, due) not in paid:
                found.append(
                    (due, Expected(ExpectedKind.BILL, bill.name, Direction.OUT, bill.amount, None))
                )
    for sub in subscriptions:
        if sub.status is not SubscriptionStatus.ACTIVE:
            continue
        charge = next_charge(sub.cadence, sub.last_charged_on)
        while charge <= end:
            if charge >= start and charge > sub.last_charged_on:
                found.append(
                    (
                        charge,
                        Expected(
                            ExpectedKind.SUBSCRIPTION, sub.name, Direction.OUT, sub.amount, None
                        ),
                    )
                )
            charge = next_charge(sub.cadence, charge)
    if schedule is not None:
        for payday in paydays(schedule, start, end):
            # Today's payday may already be logged: it's shown as expected from
            # tomorrow on, and as what happened today.
            if payday > today:
                found.append(
                    (
                        payday,
                        Expected(
                            ExpectedKind.SALARY, "Salary", Direction.IN, schedule.baseline, None
                        ),
                    )
                )
    return found
