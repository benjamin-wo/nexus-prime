"""Trips: a trip is a money object first. Its dates, budget, money set aside for it
and what was spent on it. Pure rules, no I/O.

Travel never books or buys anything. A trip is made by hand ("Tokyo 10-20 Jan,
budget S$3,000") or, later, from research.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId, clean_name, require_positive
from nexus.domain.money import Money

MAX_TRIPS = 50
MAX_TRIP_DAYS = 120
MAX_COMPANIONS = 12
MAX_PLANNED = 12
# How many of the biggest categories the spending section shows.
TOP_CATEGORIES = 5


class TripStatus(StrEnum):
    UPCOMING = "upcoming"
    ONGOING = "ongoing"
    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class Trip:
    id: UUID
    user_id: UserId
    destination: str
    start: date
    end: date
    currency: str  # what's spent there: expenses in it between the dates are the trip's
    # In the home currency, like the set-aside and the planned amounts.
    budget: Money | None
    companions: tuple[str, ...]
    set_aside: Money | None  # each payday until the trip
    planned: dict[str, Money]  # by category name
    created_at: datetime
    updated_at: datetime

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def status(self, today: date) -> TripStatus:
        if today < self.start:
            return TripStatus.UPCOMING
        if today <= self.end:
            return TripStatus.ONGOING
        return TripStatus.FINISHED

    def day_number(self, today: date) -> int | None:
        """Day 3 of 10, while it's on."""
        if self.status(today) is not TripStatus.ONGOING:
            return None
        return (today - self.start).days + 1


def clean_destination(raw: str) -> str:
    return clean_name(raw, field_name="destination")


def clean_currency(raw: str) -> str:
    code = raw.strip().upper()
    if len(code) != 3 or not code.isalpha() or not code.isascii():
        raise InvalidInput(f"{raw!r} isn't a currency code like JPY")
    return code


def check_dates(start: date, end: date) -> None:
    if end < start:
        raise InvalidInput("the trip ends before it starts")
    if (end - start).days + 1 > MAX_TRIP_DAYS:
        raise InvalidInput(f"a trip can be at most {MAX_TRIP_DAYS} days")


def clean_companions(names: Iterable[str]) -> tuple[str, ...]:
    found: list[str] = []
    for raw in names:
        name = clean_name(raw, field_name="companion")
        if name.casefold() not in {n.casefold() for n in found}:
            found.append(name)
    if len(found) > MAX_COMPANIONS:
        raise InvalidInput(f"at most {MAX_COMPANIONS} people on a trip")
    return tuple(found)


def home_amount(amount: Money | None, home: str, *, what: str) -> Money | None:
    if amount is None:
        return None
    if amount.currency != home:
        raise InvalidInput(f"the {what} is kept in your home currency, {home}")
    return require_positive(amount)


def clean_planned(planned: dict[str, Money], home: str) -> dict[str, Money]:
    found: dict[str, Money] = {}
    for raw, amount in planned.items():
        name = clean_name(raw, field_name="category")
        key = next((k for k in found if k.casefold() == name.casefold()), name)
        if amount.currency != home:
            raise InvalidInput(f"planned amounts are kept in your home currency, {home}")
        checked = require_positive(amount)
        found[key] = found[key] + checked if key in found else checked
    if len(found) > MAX_PLANNED:
        raise InvalidInput(f"plan at most {MAX_PLANNED} categories")
    return found


# --- spending --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TripItem:
    """One expense on the trip: the user's own share (the bill less what others'
    shares of it are), and that in the home currency at the day's rate."""

    transaction_id: UUID
    day: date  # local
    counterparty: str | None
    category: str | None
    amount: Money
    home: Money | None  # None when there's no rate for that day
    linked: bool  # added to the trip by hand rather than by its dates and currency


@dataclass(frozen=True, slots=True)
class CategorySpend:
    name: str
    planned: Money | None
    spent: Money


@dataclass(frozen=True, slots=True)
class TripSpending:
    spent: Money
    left: Money | None  # the budget less what's spent; below zero when over
    percent: int | None  # of the budget
    before: Money  # spent before the trip began: flights, hotel deposits
    today: Money | None  # while it's on
    per_day: Money | None  # the average over the days so far
    per_day_left: Money | None  # what's left over the days still to go, today included
    categories: list[CategorySpend]  # biggest first, planned ones included
    unconverted: int  # expenses with no rate for their day, left out of the totals


def _divide(amount: Money, parts: int) -> Money:
    return Money((amount.amount / parts).quantize(Decimal("0.01")), amount.currency)


def spending(trip: Trip, items: Sequence[TripItem], today: date, home: str) -> TripSpending:
    zero = Money.zero(home)
    counted = [i for i in items if i.home is not None]
    spent = sum((i.home for i in counted if i.home), zero)
    before = sum((i.home for i in counted if i.home and i.day < trip.start), zero)
    status = trip.status(today)

    left = percent = None
    if trip.budget is not None:
        left = trip.budget - spent
        percent = int(spent.amount * 100 / trip.budget.amount)

    today_spent = per_day = per_day_left = None
    if status is not TripStatus.UPCOMING:
        last = min(today, trip.end)
        elapsed = (last - trip.start).days + 1
        during = sum((i.home for i in counted if i.home and trip.start <= i.day <= last), zero)
        per_day = _divide(during, elapsed)
    if status is TripStatus.ONGOING:
        today_spent = sum((i.home for i in counted if i.home and i.day == today), zero)
        if left is not None:
            remaining = (trip.end - today).days + 1
            per_day_left = _divide(left, remaining) if left.is_positive else zero

    by_name: dict[str, Money] = {}
    for i in counted:
        if i.home is not None:
            name = i.category or "Uncategorised"
            by_name[name] = by_name.get(name, zero) + i.home
    planned = {k.casefold(): (k, v) for k, v in trip.planned.items()}
    categories = [
        CategorySpend(name, planned.pop(name.casefold(), (name, None))[1], amount)
        for name, amount in sorted(by_name.items(), key=lambda kv: (-kv[1].amount, kv[0]))
    ]
    categories += [CategorySpend(name, amount, zero) for name, amount in planned.values()]
    return TripSpending(
        spent=spent,
        left=left,
        percent=percent,
        before=before,
        today=today_spent,
        per_day=per_day,
        per_day_left=per_day_left,
        categories=categories,
        unconverted=len(items) - len(counted),
    )


# --- setting money aside -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SetAside:
    per_payday: Money | None
    paydays_done: int  # since the trip was made, today included
    paydays_left: int  # from tomorrow until the day before the trip
    saved: Money | None  # what should be put aside by now, at the planned amount
    by_start: Money | None  # and by the day before the trip
    covers_budget: bool | None
    # What each payday left would need to be to reach the budget. None without a
    # budget or with no paydays left.
    suggested: Money | None
    fits: bool | None = None  # whether the forecast to the trip stays above zero
    next_payday: date | None = field(default=None)


def set_aside(trip: Trip, done: Sequence[date], ahead: Sequence[date], home: str) -> SetAside:
    """``done``: paydays from the day the trip was made to today; ``ahead``: paydays
    after today and before the trip starts."""
    per = trip.set_aside
    saved = by_start = None
    if per is not None:
        saved = Money(per.amount * len(done), home)
        by_start = Money(per.amount * (len(done) + len(ahead)), home)
    covers = suggested = None
    if trip.budget is not None:
        if by_start is not None:
            covers = by_start >= trip.budget
        if ahead:
            short = trip.budget - (saved or Money.zero(home))
            if short.is_positive:
                each = (short.amount / len(ahead)).quantize(Decimal(1), rounding=ROUND_CEILING)
                suggested = Money(each, home)
    return SetAside(
        per_payday=per,
        paydays_done=len(done),
        paydays_left=len(ahead),
        saved=saved,
        by_start=by_start,
        covers_budget=covers,
        suggested=suggested,
        next_payday=ahead[0] if ahead else None,
    )


# --- settling up -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Owed:
    """What one companion still owes the user for the trip."""

    name: str
    amounts: list[Money]  # one per currency
    home: Money | None  # in the home currency; None if a rate is missing


def describe_trip(trip: Trip, today: date) -> str:
    status = trip.status(today)
    when = f"{trip.start:%d %b} to {trip.end:%d %b %Y} ({trip.days} days)"
    parts = [f"{trip.destination}, {when}, spending in {trip.currency}"]
    if status is TripStatus.UPCOMING:
        parts.append(f"in {(trip.start - today).days} days")
    elif status is TripStatus.ONGOING:
        parts.append(f"day {trip.day_number(today)} of {trip.days}")
    else:
        parts.append("finished")
    if trip.budget:
        parts.append(f"budget {trip.budget}")
    if trip.companions:
        parts.append("with " + ", ".join(trip.companions))
    if trip.set_aside:
        parts.append(f"setting aside {trip.set_aside} each payday")
    return "; ".join(parts)
