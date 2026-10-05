"""What an evaluation case expects of the data afterwards. Each check reads the
user's data through the use cases and says, in words, what it looked for."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import memory as memory_cases
from nexus.application import notifications as notification_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.categories import list_categories
from nexus.application.category_rules import list_rules
from nexus.application.ports import LedgerQuery, UnitOfWork
from nexus.domain.ledger import Transaction, User

type UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class World:
    """The case's user after the conversation, and what was there before it."""

    uow: UowFactory
    user: User
    seeded: frozenset[UUID]  # transaction ids from the seed

    async def transactions(self) -> list[Transaction]:
        page = await tx_cases.list_ledger(
            self.uow(), self.user.id, LedgerQuery(include_deleted=True, limit=500)
        )
        return page.items

    async def category_names(self, *, include_inactive: bool = False) -> dict[UUID, str]:
        cats = await list_categories(self.uow(), self.user.id, include_inactive=True)
        return {c.id: c.name for c in cats if include_inactive or c.active}

    def local_day(self, tx: Transaction) -> date:
        return tx.occurred_at.astimezone(ZoneInfo(self.user.timezone)).date()


class Check(Protocol):
    def describe(self) -> str: ...

    async def holds(self, world: World) -> bool: ...


def _one_of(value: str | None, wanted: str | tuple[str, ...] | None) -> bool:
    if wanted is None:
        return True
    options = (wanted,) if isinstance(wanted, str) else wanted
    return value is not None and value.casefold() in {o.casefold() for o in options}


def _mentions(tx: Transaction, text: str | None) -> bool:
    if text is None:
        return True
    haystack = f"{tx.counterparty or ''} {tx.notes or ''}".casefold()
    return text.casefold() in haystack


@dataclass(frozen=True, slots=True)
class Logged:
    """A new, live transaction like this exists."""

    amount: str
    merchant: str | None = None  # found in the merchant or notes, any case
    category: str | tuple[str, ...] | None = None
    currency: str = "SGD"
    day: date | None = None
    direction: str = "out"

    def describe(self) -> str:
        parts = [f"{self.direction} {self.amount} {self.currency}"]
        if self.merchant:
            parts.append(f"mentioning {self.merchant!r}")
        if self.category:
            parts.append(f"in {self.category}")
        if self.day:
            parts.append(f"on {self.day}")
        return "logged " + ", ".join(parts)

    async def holds(self, world: World) -> bool:
        names = await world.category_names(include_inactive=True)
        for tx in await world.transactions():
            if tx.id in world.seeded or tx.is_deleted:
                continue
            if (
                tx.direction.value == self.direction
                and tx.amount.amount == Decimal(self.amount)
                and tx.amount.currency == self.currency
                and _mentions(tx, self.merchant)
                and _one_of(names.get(tx.category_id) if tx.category_id else None, self.category)
                and (self.day is None or world.local_day(tx) == self.day)
            ):
                return True
        return False


@dataclass(frozen=True, slots=True)
class NotLogged:
    """No new, live transaction like this exists (undone, corrected or never made)."""

    amount: str
    merchant: str | None = None
    day: date | None = None

    def describe(self) -> str:
        where = f" mentioning {self.merchant!r}" if self.merchant else ""
        when = f" on {self.day}" if self.day else ""
        return f"no live {self.amount}{where}{when}"

    async def holds(self, world: World) -> bool:
        return not any(
            tx.id not in world.seeded
            and not tx.is_deleted
            and tx.amount.amount == Decimal(self.amount)
            and _mentions(tx, self.merchant)
            and (self.day is None or world.local_day(tx) == self.day)
            for tx in await world.transactions()
        )


@dataclass(frozen=True, slots=True)
class Changed:
    """The seeded transaction at this merchant on this day now looks like this."""

    merchant: str
    day: date
    amount: str | None = None
    category: str | tuple[str, ...] | None = None
    new_day: date | None = None

    def describe(self) -> str:
        what = []
        if self.amount:
            what.append(f"amount {self.amount}")
        if self.category:
            what.append(f"category {self.category}")
        if self.new_day:
            what.append(f"day {self.new_day}")
        return f"{self.merchant} on {self.day} changed to " + ", ".join(what)

    async def holds(self, world: World) -> bool:
        names = await world.category_names(include_inactive=True)
        for tx in await world.transactions():
            if tx.id not in world.seeded or tx.is_deleted or not _mentions(tx, self.merchant):
                continue
            if self.new_day is None and world.local_day(tx) != self.day:
                continue
            if self.new_day is not None and world.local_day(tx) != self.new_day:
                continue
            if self.amount is not None and tx.amount.amount != Decimal(self.amount):
                continue
            category = names.get(tx.category_id) if tx.category_id else None
            if self.category is not None and not _one_of(category, self.category):
                continue
            return True
        return False


@dataclass(frozen=True, slots=True)
class Deleted:
    merchant: str
    day: date

    def describe(self) -> str:
        return f"{self.merchant} on {self.day} deleted"

    async def holds(self, world: World) -> bool:
        return any(
            tx.is_deleted and _mentions(tx, self.merchant) and world.local_day(tx) == self.day
            for tx in await world.transactions()
        )


@dataclass(frozen=True, slots=True)
class Owes:
    """What this person still owes the user, across their open IOUs."""

    name: str
    amount: str

    def describe(self) -> str:
        return f"{self.name} owes {self.amount}"

    async def holds(self, world: World) -> bool:
        ious = await split_cases.list_open_ious(world.uow(), world.user.id)
        name = self.name.casefold()
        theirs = [i.outstanding.amount for i in ious if i.split.participant_name.casefold() == name]
        owed = sum(theirs, Decimal(0))
        return owed == Decimal(self.amount)


@dataclass(frozen=True, slots=True)
class BudgetIs:
    category: str | None  # None: the overall budget
    amount: str | None  # None: there's no such budget

    def describe(self) -> str:
        which = self.category or "overall"
        return f"{which} budget is {self.amount}" if self.amount else f"no {which} budget"

    async def holds(self, world: World) -> bool:
        names = await world.category_names(include_inactive=True)
        async with world.uow() as tx:
            budgets = await tx.planning.list_budgets(world.user.id)
        for b in budgets:
            name = names.get(b.category_id) if b.category_id else None
            same = (name or "").casefold() == (self.category or "").casefold()
            if same:
                return self.amount is not None and b.limit.amount == Decimal(self.amount)
        return self.amount is None


@dataclass(frozen=True, slots=True)
class BillIs:
    name: str
    amount: str | None = None
    due: date | None = None
    exists: bool = True
    paid_on: date | None = None  # this due date is marked paid

    def describe(self) -> str:
        if not self.exists:
            return f"no bill called {self.name}"
        extra = f" of {self.amount}" if self.amount else ""
        extra += f" due {self.due}" if self.due else ""
        extra += f", {self.paid_on} marked paid" if self.paid_on else ""
        return f"a bill {self.name}{extra}"

    async def holds(self, world: World) -> bool:
        async with world.uow() as tx:
            bills = [
                b
                for b in await tx.planning.list_bills(world.user.id)
                if b.archived_at is None and self.name.casefold() in b.name.casefold()
            ]
            if not self.exists:
                return not bills
            for bill in bills:
                if self.amount is not None and (
                    bill.amount is None or bill.amount.amount != Decimal(self.amount)
                ):
                    continue
                if self.due is not None and bill.anchor != self.due:
                    continue
                if self.paid_on is not None:
                    occurrences = await tx.planning.occurrences(
                        world.user.id, bill.id, self.paid_on
                    )
                    if not any(o.due == self.paid_on and o.paid_at for o in occurrences):
                        continue
                return True
        return False


@dataclass(frozen=True, slots=True)
class RuleIs:
    pattern: str
    category: str | None  # None: no active rule for the pattern

    def describe(self) -> str:
        if self.category is None:
            return f"no rule for {self.pattern!r}"
        return f"rule {self.pattern!r} → {self.category}"

    async def holds(self, world: World) -> bool:
        for view in await list_rules(world.uow(), world.user.id):
            if view.rule.pattern == self.pattern.casefold():
                return (
                    self.category is not None
                    and view.category.name.casefold() == self.category.casefold()
                )
        return self.category is None


@dataclass(frozen=True, slots=True)
class CategoryIs:
    name: str
    active: bool | None  # None: no such category at all

    def describe(self) -> str:
        state = {True: "active", False: "archived", None: "absent"}[self.active]
        return f"category {self.name} {state}"

    async def holds(self, world: World) -> bool:
        cats = await list_categories(world.uow(), world.user.id, include_inactive=True)
        match = [c for c in cats if c.name.casefold() == self.name.casefold()]
        if self.active is None:
            return not match
        return any(c.active is self.active for c in match)


@dataclass(frozen=True, slots=True)
class PayIs:
    day: int | None = None
    usual: str | None = None

    def describe(self) -> str:
        return f"paid on day {self.day}" if self.day else f"usual salary {self.usual}"

    async def holds(self, world: World) -> bool:
        async with world.uow() as tx:
            schedule = await tx.planning.get_salary_schedule(world.user.id)
        if schedule is None:
            return False
        if self.day is not None and schedule.day != self.day:
            return False
        return self.usual is None or (
            schedule.baseline is not None and schedule.baseline.amount == Decimal(self.usual)
        )


@dataclass(frozen=True, slots=True)
class UpdatesAre:
    frequency: str
    at: str | None = None  # the daily summary's time, HH:MM

    def describe(self) -> str:
        return f"Telegram updates {self.frequency}" + (f" at {self.at}" if self.at else "")

    async def holds(self, world: World) -> bool:
        settings = await notification_cases.get_settings(world.uow(), world.user.id)
        if self.at is not None and settings.daily_at.strftime("%H:%M") != self.at:
            return False
        return settings.frequency.value == self.frequency


@dataclass(frozen=True, slots=True)
class Remembers:
    """Some memory mentions ``text`` (or, with ``present=False``, none does)."""

    text: str
    present: bool = True

    def describe(self) -> str:
        return f"{'a' if self.present else 'no'} memory mentioning {self.text!r}"

    async def holds(self, world: World) -> bool:
        found = await memory_cases.list_memories(world.uow(), world.user.id)
        mentioned = any(self.text.casefold() in m.text.casefold() for m in found)
        return mentioned is self.present


@dataclass(frozen=True, slots=True)
class Booked:
    """An itinerary entry like this is on the seeded Tokyo trip (or any trip)."""

    title: str  # found in its title, any case
    reference: str | None = None
    booked_via: str | None = None
    starts: date | None = None
    cost: str | None = None  # the amount, in any currency
    absent: tuple[str, ...] = ()  # text that must not be stored anywhere in it

    def describe(self) -> str:
        parts = [f"an itinerary entry '{self.title}'"]
        if self.starts:
            parts.append(f"from {self.starts}")
        if self.reference:
            parts.append(f"ref {self.reference}")
        if self.booked_via:
            parts.append(f"booked on {self.booked_via}")
        if self.cost:
            parts.append(f"costing {self.cost}")
        if self.absent:
            parts.append("without " + ", ".join(self.absent))
        return ", ".join(parts)

    async def holds(self, world: World) -> bool:
        async with world.uow() as tx:
            bookings = await tx.trips.list_bookings(world.user.id)
        for b in bookings:
            d = b.draft
            if b.trip_id is None or self.title.casefold() not in d.title.casefold():
                continue
            if self.reference and (d.reference or "").replace(" ", "") != self.reference:
                continue
            if (
                self.booked_via
                and self.booked_via.casefold() not in (d.booked_via or "").casefold()
            ):
                continue
            if self.starts and d.starts != self.starts:
                continue
            if self.cost and (b.cost is None or b.cost.amount != Decimal(self.cost)):
                continue
            stored = str(d.as_dict()).casefold()
            if any(a.casefold() in stored for a in self.absent):
                continue
            return True
        return False
