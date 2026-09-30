"""Answering questions about the ledger from structured arguments, never SQL.

A question is a fixed set of filters, an optional grouping and a measure, all
from an allow-list. Only the acting user's confirmed, live transactions count.
Figures are in the home currency: foreign amounts convert at their own day's
rate, and any without a rate are reported, not guessed. At most ``MAX_ROWS``
transactions are read per period; a question over more says so.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application.fx import RateSource
from nexus.application.ports import LedgerQuery, SortField, UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
    Source,
    Transaction,
    TransactionStatus,
    User,
    clean_text,
    require_aware,
)
from nexus.domain.money import Money, minor_units

type UowFactory = Callable[[], UnitOfWork]

MAX_ROWS = 5000
MAX_TOP = 31
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class GroupBy(StrEnum):
    CATEGORY = "category"
    MERCHANT = "merchant"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    WEEKDAY = "weekday"


class Measure(StrEnum):
    TOTAL = "total"
    COUNT = "count"
    AVERAGE = "average"
    LARGEST = "largest"


_NONE = UUID(int=0)
_OVER_TIME = {GroupBy.DAY, GroupBy.WEEK, GroupBy.MONTH, GroupBy.WEEKDAY}


@dataclass(frozen=True, slots=True)
class LedgerQuestion:
    start: datetime  # inclusive
    end: datetime  # exclusive
    direction: Direction = Direction.OUT
    search: str | None = None  # text in the merchant or notes
    category_id: UUID | None = None
    uncategorised: bool = False
    source: Source | None = None
    min_amount: Decimal | None = None  # home currency, inclusive
    max_amount: Decimal | None = None
    weekdays: frozenset[int] | None = None  # 0 is Monday, in the user's timezone
    group_by: GroupBy | None = None
    measure: Measure = Measure.TOTAL
    top: int = 10
    compare_previous: bool = False


@dataclass(frozen=True, slots=True)
class Item:
    """A matching transaction with its home-currency amount."""

    transaction: Transaction
    home: Money
    day: date  # local


@dataclass(frozen=True, slots=True)
class Group:
    key: str
    total: Money
    count: int
    average: Money
    largest: Money


@dataclass(frozen=True, slots=True)
class Figures:
    start: datetime
    end: datetime
    total: Money
    count: int
    average: Money
    largest: list[Item]  # the biggest matching transactions, largest first, at most ``top``
    groups: list[Group]  # ranked by the measure, or in time order; at most ``top``
    more_groups: int  # groups left out by ``top``
    converted: list[Money]  # foreign originals included, per currency
    unconverted: list[Money]  # foreign amounts left out for want of a rate
    truncated: bool  # more than MAX_ROWS matched; figures cover the newest MAX_ROWS


@dataclass(frozen=True, slots=True)
class Answer:
    currency: str
    current: Figures
    previous: Figures | None  # the period before, when asked for


def previous_period(start: datetime, end: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The period just before: the same number of whole months when the question
    covers whole months, otherwise the same length of time."""
    first, last = start.astimezone(tz), end.astimezone(tz)
    midnight = time()
    if first.day == 1 and last.day == 1 and first.time() == midnight == last.time():
        months = (last.year - first.year) * 12 + last.month - first.month
        index = first.year * 12 + first.month - 1 - months
        begin = datetime(index // 12, index % 12 + 1, 1, tzinfo=tz)
        return begin, start
    return start - (end - start), start


def _check(q: LedgerQuestion) -> None:
    require_aware(q.start, field_name="start")
    require_aware(q.end, field_name="end")
    if q.start >= q.end:
        raise InvalidInput("the start must be before the end")
    if not 1 <= q.top <= MAX_TOP:
        raise InvalidInput(f"top must be between 1 and {MAX_TOP}")
    if q.uncategorised and q.category_id is not None:
        raise InvalidInput("choose a category or uncategorised, not both")
    for bound in (q.min_amount, q.max_amount):
        if bound is not None and (not bound.is_finite() or bound < 0):
            raise InvalidInput("amount bounds must be zero or more")
    if q.min_amount is not None and q.max_amount is not None and q.min_amount > q.max_amount:
        raise InvalidInput("the smallest amount is larger than the largest")
    if q.weekdays is not None and (not q.weekdays or not q.weekdays <= set(range(7))):
        raise InvalidInput("weekdays are 0 (Monday) to 6 (Sunday)")


def _money(value: Decimal, currency: str) -> Money:
    unit = Decimal(1).scaleb(-minor_units(currency))
    return Money(value.quantize(unit, rounding=ROUND_HALF_UP), currency)


def _by_currency(amounts: Iterable[Money]) -> list[Money]:
    merged: dict[str, Money] = {}
    for m in amounts:
        merged[m.currency] = merged[m.currency] + m if m.currency in merged else m
    return [merged[c] for c in sorted(merged)]


def _key(item: Item, by: GroupBy, names: dict[UUID, str]) -> tuple[str, str]:
    """(sort key, label) for the item's group."""
    tx, day = item.transaction, item.day
    match by:
        case GroupBy.CATEGORY:
            label = names.get(tx.category_id or _NONE, "Uncategorised")
            return label.casefold(), label
        case GroupBy.MERCHANT:
            label = " ".join((tx.counterparty or "(no merchant)").split())
            return label.casefold(), label
        case GroupBy.DAY:
            return day.isoformat(), day.isoformat()
        case GroupBy.WEEK:
            monday = day - timedelta(days=day.weekday())
            return monday.isoformat(), f"week of {monday.isoformat()}"
        case GroupBy.MONTH:
            return day.strftime("%Y-%m"), day.strftime("%Y-%m")
        case GroupBy.WEEKDAY:
            return str(day.weekday()), WEEKDAYS[day.weekday()]


def _measure(group: Group, measure: Measure) -> Decimal:
    match measure:
        case Measure.TOTAL:
            return group.total.amount
        case Measure.COUNT:
            return Decimal(group.count)
        case Measure.AVERAGE:
            return group.average.amount
        case Measure.LARGEST:
            return group.largest.amount


def _groups(
    items: list[Item], q: LedgerQuestion, home: str, names: dict[UUID, str]
) -> tuple[list[Group], int]:
    if q.group_by is None:
        return [], 0
    buckets: dict[str, tuple[str, list[Item]]] = {}
    for item in items:
        key, label = _key(item, q.group_by, names)
        # A merchant written differently keeps the first spelling seen (newest first).
        buckets.setdefault(key, (label, []))[1].append(item)
    groups: list[tuple[str, Group]] = []
    for key, (label, members) in buckets.items():
        total = sum((m.home.amount for m in members), Decimal(0))
        groups.append(
            (
                key,
                Group(
                    label,
                    _money(total, home),
                    len(members),
                    _money(total / len(members), home),
                    max((m.home for m in members), key=lambda m: m.amount),
                ),
            )
        )
    if q.group_by in _OVER_TIME:
        groups.sort(key=lambda g: g[0])
    else:
        groups.sort(key=lambda g: (-_measure(g[1], q.measure), g[0]))
    ranked = [g for _, g in groups]
    return ranked[: q.top], max(0, len(ranked) - q.top)


async def _figures(
    uow: UnitOfWork,
    rates: RateSource,
    user: User,
    q: LedgerQuestion,
    start: datetime,
    end: datetime,
    names: dict[UUID, str],
) -> Figures:
    tz, home = ZoneInfo(user.timezone), user.home_currency
    async with uow:
        page = await uow.ledger.list_transactions(
            user.id,
            LedgerQuery(
                direction=q.direction,
                start=start,
                end=end,
                category_id=q.category_id,
                uncategorized=q.uncategorised,
                source=q.source,
                status=TransactionStatus.CONFIRMED,
                search=q.search,
                sort=SortField.OCCURRED_AT,
                limit=MAX_ROWS,
            ),
        )
    local = [(tx, tx.occurred_at.astimezone(tz).date()) for tx in page.items]
    if q.weekdays is not None:
        local = [(tx, day) for tx, day in local if day.weekday() in q.weekdays]
    found = await fx.rates_for(rates, home, ((tx.amount.currency, day) for tx, day in local))
    items: list[Item] = []
    converted: list[Money] = []
    unconverted: list[Money] = []
    for tx, day in local:
        amount = fx.convert(tx.amount, day, home, found).home
        if amount is None:
            unconverted.append(tx.amount)
            continue
        if q.min_amount is not None and amount.amount < q.min_amount:
            continue
        if q.max_amount is not None and amount.amount > q.max_amount:
            continue
        if tx.amount.currency != home:
            converted.append(tx.amount)
        items.append(Item(tx, amount, day))
    total = sum((i.home.amount for i in items), Decimal(0))
    groups, more = _groups(items, q, home, names)
    return Figures(
        start=start,
        end=end,
        total=_money(total, home),
        count=len(items),
        average=_money(total / len(items) if items else Decimal(0), home),
        largest=sorted(items, key=lambda i: -i.home.amount)[: q.top],
        groups=groups,
        more_groups=more,
        converted=_by_currency(converted),
        unconverted=_by_currency(unconverted),
        truncated=page.total > len(page.items),
    )


async def ask_ledger(
    uow_factory: UowFactory, rates: RateSource, user: User, question: LedgerQuestion
) -> Answer:
    _check(question)
    q = replace(question, search=clean_text(question.search, field_name="search", limit=100))
    async with uow_factory() as db:
        cats = await db.ledger.list_categories(user.id, include_inactive=True)
    names = {c.id: c.name for c in cats}
    current = await _figures(uow_factory(), rates, user, q, q.start, q.end, names)
    previous = None
    if q.compare_previous:
        start, end = previous_period(q.start, q.end, ZoneInfo(user.timezone))
        # Every group of the earlier period, so each current group finds its match.
        wide = replace(q, top=MAX_TOP)
        previous = await _figures(uow_factory(), rates, user, wide, start, end, names)
    return Answer(user.home_currency, current, previous)
