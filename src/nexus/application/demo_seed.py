"""The demo persona: what a visitor to the public live demo finds in their new account.

A made-up young professional in Singapore (SGD, Asia/Singapore): a salary from "Acme Pte Ltd"
on the 25th, about two months of everyday spending (much of it paid with one of two made-up
credit cards, the Citi one the usual card), a few bills and subscriptions, monthly budgets
with one near its limit, a trip to Japan three weeks away, and a small US-stock portfolio.
Every name, merchant and figure is invented; nothing here is real data.

Everything is dated from ``now`` (the ledger runs back about nine weeks from today, the trip
starts three weeks on), so the demo looks current whenever it is opened. There is no
randomness: the same ``now`` gives the same account. The data goes in through the application
use cases, as the agent and the web app do, so it is as valid as anything a user enters.

Prices are not seeded. Closes and quotes are shared market data, and the normal price jobs
fetch them for any stock somebody holds or watches (the use cases below queue that); writing
made-up closes would overwrite the real ones every other account reads.
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import bills as bill_cases
from nexus.application import bookings as booking_cases
from nexus.application import budgets as budget_cases
from nexus.application import category_rules as rule_cases
from nexus.application import investments as investment_cases
from nexus.application import research as research_cases
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application import trips as trip_cases
from nexus.application import wallets as wallet_cases
from nexus.application.categories import list_categories
from nexus.application.ports import UnitOfWork
from nexus.domain.bookings import BookingDraft
from nexus.domain.investments import TradeSide
from nexus.domain.ledger import (
    Direction,
    ShareRequest,
    Source,
    Transaction,
    User,
    Wallet,
    WalletKind,
)
from nexus.domain.money import Money
from nexus.domain.packing import PackItem
from nexus.domain.planning import Cadence, PayRule, month_start, next_month_start, paydays
from nexus.domain.recurring import Subscription, SubscriptionStatus, merchant_key
from nexus.domain.trips import Stop

type UowFactory = Callable[[], UnitOfWork]

# How far back the ledger goes.
HISTORY_DAYS = 62
FRIEND = "Ann"
PAYER = "Acme Pte Ltd"
SALARY = "6200"
RENT = "1850"
# The trip starts this many days from today and lasts six days.
TRIP_LEAD_DAYS = 21
TRIP_DAYS = 6


@dataclass(frozen=True, slots=True)
class _Spend:
    """One everyday expense. ``category`` None leaves it to the user's category rules
    (a Grab ride is filed as Transport by the rule seeded below). ``with_friend`` splits
    the bill with Ann, who owes her half."""

    days_ago: int
    at: str
    merchant: str
    amount: str
    category: str | None
    note: str | None = None
    with_friend: bool = False


# The two made-up cards (the digits are invented too). Citi is the usual card.
CITI = "Citi PremierMiles"
DBS = "DBS Altitude"
# Groceries, rides and subscriptions go on the DBS card; shopping, outings and dinners out of
# SGD 15 or more on the Citi card. Hawker and coffee money, transport top-ups, health, the
# odd errand and the household bills (rent, phone, electricity) stay untagged, as if paid in
# cash or by transfer. It is decided from the entry itself, so there is no randomness.
_ON_DBS = frozenset({"FairPrice", "Sheng Siong", "Cold Storage", "Grab", "Netflix", "Spotify"})
_ON_CITI = frozenset({"Shopping", "Activities", "Socialising"})
_CITI_DINING_FROM = Decimal(15)

# Newest first. Times and amounts vary on purpose; none of it is anyone's real spending.
_SPENDING: tuple[_Spend, ...] = (
    _Spend(0, "08:05", "Kopi Corner", "4.60", "Dining Out"),
    _Spend(0, "08:40", "Grab", "11.80", None),
    _Spend(0, "12:40", "Hawker Centre", "6.80", "Dining Out"),
    _Spend(0, "18:10", "FairPrice", "23.45", "Groceries"),
    _Spend(1, "09:15", "EZ-Link top-up", "20.00", "Transport"),
    _Spend(1, "19:45", "Prata Place", "12.90", "Dining Out"),
    _Spend(2, "13:10", "Chicken Rice Stall", "5.50", "Dining Out"),
    _Spend(2, "21:20", "Grab", "16.40", None),
    _Spend(3, "20:30", "Sushi Express", "86.40", "Dining Out", "Dinner with Ann", True),
    _Spend(3, "22:10", "Grab", "18.90", None, "Home after dinner"),
    _Spend(4, "08:20", "Kopi Corner", "4.80", "Dining Out"),
    _Spend(4, "15:30", "Daiso", "12.80", "Shopping"),
    _Spend(5, "12:50", "Hawker Centre", "7.20", "Dining Out"),
    _Spend(5, "19:00", "Sheng Siong", "38.90", "Groceries"),
    _Spend(6, "11:00", "Guardian", "23.60", "Health"),
    _Spend(6, "19:15", "Ramen House", "18.50", "Dining Out"),
    _Spend(7, "16:45", "Uniqlo", "79.90", "Shopping", "Work shirts"),
    _Spend(8, "08:30", "Grab", "13.20", None),
    _Spend(8, "13:05", "Dim Sum Garden", "24.30", "Dining Out"),
    _Spend(9, "08:10", "Kopi Corner", "5.10", "Dining Out"),
    _Spend(9, "20:05", "Golden Village", "28.00", "Activities", "Movie night"),
    _Spend(10, "18:30", "Cold Storage", "77.20", "Groceries"),
    _Spend(10, "21:00", "Bubble Tea Stop", "6.90", "Dining Out"),
    _Spend(11, "12:35", "Hawker Centre", "6.20", "Dining Out"),
    _Spend(12, "10:20", "GP Clinic", "38.00", "Health"),
    _Spend(12, "22:40", "Grab", "21.70", None, "Missed the last train"),
    _Spend(13, "19:40", "Korean BBQ Table", "64.80", "Dining Out", "Team dinner"),
    _Spend(14, "08:25", "Kopi Corner", "4.60", "Dining Out"),
    _Spend(14, "14:00", "Shopee", "23.50", "Shopping"),
    _Spend(15, "17:50", "FairPrice", "54.60", "Groceries"),
    _Spend(16, "12:55", "Hawker Centre", "7.00", "Dining Out"),
    _Spend(16, "19:30", "Escape Room Co", "72.00", "Activities", "Birthday outing", True),
    _Spend(17, "09:00", "Grab", "12.30", None),
    _Spend(18, "20:15", "Craft Beer Bar", "48.00", "Socialising"),
    _Spend(19, "13:20", "Chicken Rice Stall", "5.50", "Dining Out"),
    _Spend(20, "11:15", "Decathlon", "64.90", "Shopping", "Gym gear"),
    _Spend(21, "19:10", "Prata Place", "13.40", "Dining Out"),
    _Spend(22, "08:15", "Grab", "14.60", None),
    _Spend(23, "12:45", "Dim Sum Garden", "26.10", "Dining Out", "Lunch with colleagues"),
    _Spend(24, "18:20", "Sheng Siong", "41.80", "Groceries"),
    _Spend(25, "21:10", "Takashimaya", "128.00", "Shopping", "Mum's birthday gift"),
    _Spend(26, "08:05", "Kopi Corner", "4.80", "Dining Out"),
    _Spend(27, "13:00", "Hawker Centre", "6.60", "Dining Out"),
    _Spend(28, "20:20", "Ramen House", "19.80", "Dining Out"),
    _Spend(29, "17:30", "Grab", "17.50", None),
    _Spend(30, "10:30", "Post Office", "6.40", "Other"),
    _Spend(31, "19:00", "FairPrice", "66.15", "Groceries"),
    _Spend(32, "13:15", "Hawker Centre", "7.40", "Dining Out"),
    _Spend(33, "14:30", "Climbing Gym", "24.00", "Activities", "Day pass"),
    _Spend(34, "21:30", "Sushi Express", "58.20", "Dining Out"),
    _Spend(35, "09:10", "EZ-Link top-up", "20.00", "Transport"),
    _Spend(36, "12:30", "Dim Sum Garden", "22.90", "Dining Out"),
    _Spend(37, "18:45", "Cold Storage", "59.30", "Groceries"),
    _Spend(38, "08:40", "Grab", "15.80", None),
    _Spend(39, "19:20", "Bubble Tea Stop", "7.20", "Dining Out"),
    _Spend(40, "16:00", "Barber Lounge", "28.00", "Other"),
    _Spend(41, "20:00", "Rooftop Bar", "56.50", "Socialising"),
    _Spend(42, "12:50", "Chicken Rice Stall", "5.80", "Dining Out"),
    _Spend(43, "18:10", "FairPrice", "47.90", "Groceries"),
    _Spend(44, "22:15", "Grab", "24.30", None),
    _Spend(45, "13:40", "Ramen House", "17.90", "Dining Out"),
    _Spend(46, "11:30", "Popular Bookstore", "28.40", "Shopping"),
    _Spend(47, "19:35", "Prata Place", "12.50", "Dining Out"),
    _Spend(48, "09:00", "ComfortDelGro", "18.40", "Transport", "Taxi in the rain"),
    _Spend(50, "12:40", "Hawker Centre", "6.90", "Dining Out"),
    _Spend(51, "18:50", "Sheng Siong", "52.35", "Groceries"),
    _Spend(52, "15:10", "Watsons", "18.90", "Health"),
    _Spend(53, "13:05", "Dim Sum Garden", "25.50", "Dining Out"),
    _Spend(54, "08:20", "Grab", "12.90", None),
    _Spend(55, "19:50", "Craft Beer Bar", "42.00", "Socialising"),
    _Spend(56, "12:35", "Kopi Corner", "5.40", "Dining Out"),
    _Spend(57, "17:20", "Uniqlo", "49.90", "Shopping"),
    _Spend(58, "21:15", "Ramen House", "18.50", "Dining Out"),
    _Spend(59, "18:05", "FairPrice", "72.40", "Groceries"),
    _Spend(60, "12:55", "Hawker Centre", "7.10", "Dining Out"),
    _Spend(61, "09:20", "EZ-Link top-up", "20.00", "Transport"),
)

# The electricity bill varies; the last three, newest first (what the bill itself estimates
# is ELECTRICITY_ESTIMATE).
_ELECTRICITY = ("104.75", "91.40", "87.20")
ELECTRICITY_ESTIMATE = "98.00"
PHONE = "38.90"
SUBS = "Subscriptions & Software"
BILLS = "Bills & Utilities"

# Subscriptions: (name, amount now, amount before, days since the last charge).
# Netflix went up a dollar at the last charge.
_NETFLIX = ("Netflix", "17.98", "15.98", 5)
_SPOTIFY = ("Spotify", "10.98", "10.98", 12)

# Each monthly budget: the share of it used this month that the figure aims for (low, high
# percent), and the least the limit is (early in a month there is little spending to size it by).
DINING = "Dining Out"
_BUDGETS: dict[str, tuple[int, int, int]] = {
    DINING: (86, 94, 200),  # near its limit: it is on Home's list
    "Groceries": (45, 58, 300),
    "Transport": (55, 68, 120),
    "Shopping": (30, 45, 250),
}

# (symbol, shares, price paid in USD, days ago). Several buys of one stock average out.
_TRADES: tuple[tuple[str, str, str, int], ...] = (
    ("NVDA", "8", "121.40", 58),
    ("VOO", "6", "498.30", 57),
    ("AAPL", "15", "212.60", 44),
    ("MSFT", "6", "418.90", 36),
    ("NVDA", "4", "139.80", 27),
    ("VOO", "2", "509.10", 20),
)
_WATCHED = ("AMD", "GOOGL")

# The Japan trip's plans: (day of the trip, from, to, name, category, note).
_PLANS: tuple[tuple[int, str, str, str, str, str | None], ...] = (
    (0, "19:30", "20:45", "Ramen at Kyoto Station", "Food", None),
    (1, "08:00", "10:30", "Fushimi Inari Shrine", "Sight", "Go early, before the crowds"),
    (1, "12:00", "13:30", "Lunch at Nishiki Market", "Food", None),
    (1, "14:30", "16:30", "Kiyomizu-dera", "Sight", None),
    (1, "17:30", "18:30", "Evening walk through Gion", "Sight", None),
    (1, "19:00", "21:00", "Kaiseki dinner", "Food", "Booked for two"),
    (2, "09:00", "10:15", "Arashiyama Bamboo Grove", "Sight", None),
    (2, "10:30", "11:45", "Tenryu-ji Temple", "Sight", None),
    (2, "12:30", "13:45", "Tofu lunch in Arashiyama", "Food", None),
    (2, "15:00", "16:15", "Kinkaku-ji", "Sight", None),
    (2, "19:00", "21:00", "Dinner on Pontocho Alley", "Food", None),
    (3, "11:00", "12:30", "Train to Osaka", "Transport", "Check out of the Kyoto hotel first"),
    (3, "14:00", "16:00", "Osaka Castle", "Sight", None),
    (3, "18:30", "21:00", "Street food in Dotonbori", "Food", None),
)
_DAY_LABELS = {1: "Temples and old Kyoto", 2: "Arashiyama", 3: "Into Osaka"}

# Places to visit with no day yet: (list, name, category, note).
_IDEAS: tuple[tuple[str, str, str, str | None], ...] = (
    ("Food", "Nishiki Market snacks", "Food", "Skewers and pickles; go hungry"),
    ("Food", "Okonomiyaki in Osaka", "Food", None),
    ("Food", "Matcha tea house", "Food", "Somewhere quiet in Uji"),
    ("Sights", "Nara Park deer", "Sight", "Half a day by train from Kyoto"),
    ("Sights", "Philosopher's Path", "Sight", None),
    ("Rainy day", "Osaka Aquarium", "Sight", "Plan B if it pours"),
)

_PACKING = (
    ("Passport", True),
    ("Travel insurance papers", False),
    ("Yen in cash", False),
    ("eSIM or pocket Wi-Fi", False),
    ("Power bank", True),
    ("Comfortable walking shoes", True),
    ("Light jacket", False),
    ("Compact umbrella", False),
    ("Coin purse for change", False),
)


def _months_before(day: date, months: int) -> date:
    """The same day of the month ``months`` earlier (the last day if that month is shorter)."""
    index = day.year * 12 + day.month - 1 - months
    year, month = index // 12, index % 12 + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


def _limit_for(spent: Decimal, low: int, high: int) -> Decimal:
    """A round monthly limit that leaves ``spent`` between ``low`` and ``high`` percent used:
    the roundest one there is. Zero when nothing is spent."""
    if spent <= 0:
        return Decimal(0)
    for step in (50, 25, 10, 5, 1):
        limit = (spent * 100 / high / step).to_integral_value(ROUND_CEILING) * step
        if spent * 100 / limit >= low:
            return limit
    return (spent * 100 / high).to_integral_value(ROUND_CEILING)


class _Days:
    """Dates and moments in the user's own time, counted back from ``now``."""

    def __init__(self, user: User, now: datetime) -> None:
        self.tz = ZoneInfo(user.timezone)
        self.now = now
        self.today = now.astimezone(self.tz).date()

    def on(self, day: date, at: str = "09:00") -> datetime:
        """``day`` at ``at`` local time, never later than a minute ago."""
        hours, minutes = (int(part) for part in at.split(":"))
        moment = datetime.combine(day, time(hours, minutes), tzinfo=self.tz)
        return min(moment, self.now - timedelta(minutes=1))

    def ago(self, days: int, at: str = "09:00") -> datetime:
        return self.on(self.today - timedelta(days=days), at)

    @property
    def first(self) -> date:
        """The first day of the history."""
        return self.today - timedelta(days=HISTORY_DAYS)


async def seed_demo(uow: UowFactory, user: User, *, now: datetime) -> None:
    """Fill a new, empty account with the demo persona. See the module docstring.

    The three parts are independent, so they are made side by side (a few connections at
    once) to keep a visitor's wait short. If anything fails, the rest is stopped and the
    error raised; what was already written stays, so the caller should discard the account."""
    days = _Days(user, now)
    await _together(
        _everyday(uow, user, days), _japan(uow, user, days), _investments(uow, user, days)
    )


async def _together(*work: Coroutine[Any, Any, object]) -> None:
    """Run side by side. The first to fail stops the others and its own error is raised."""
    try:
        async with asyncio.TaskGroup() as group:
            for job in work:
                group.create_task(job)
    except ExceptionGroup as failed:
        raise failed.exceptions[0] from None


@dataclass(frozen=True, slots=True)
class _Cards:
    """The two cards that expenses are tagged with."""

    citi: Wallet
    dbs: Wallet

    def paying(self, merchant: str, category: str | None, amount: str) -> UUID | None:
        """The card an expense was paid with; None leaves it untagged."""
        if merchant in _ON_DBS:
            return self.dbs.id
        if category in _ON_CITI or (category == DINING and Decimal(amount) >= _CITI_DINING_FROM):
            return self.citi.id
        return None


async def _everyday(uow: UowFactory, user: User, days: _Days) -> None:
    """Money: wallets, salary, the ledger, bills, subscriptions and budgets."""
    now = days.now
    categories = {c.name: c.id for c in await list_categories(uow(), user.id)}
    wallets, cards, _, recent = await asyncio.gather(
        _wallets(uow, user),
        _cards(uow, user),
        rule_cases.set_rule(uow(), user, "grab", categories["Transport"], now=now),
        _schedule(uow, user, days),
    )
    shared, _ = await asyncio.gather(
        _ledger(uow, user, days, categories, recent, cards, *wallets),
        _log_salary(uow, user, days, recent),
    )
    # Splits first: a budget counts only the user's own share of a shared bill.
    await asyncio.gather(
        *(split_cases.split_bill(uow(), user.id, tx.id, [ShareRequest(FRIEND)]) for tx in shared)
    )
    await asyncio.gather(
        _bills(uow, user, days),
        _subscriptions(uow, user, days),
        _budgets(uow, user, days, categories),
    )


async def _wallets(uow: UowFactory, user: User) -> tuple[Wallet, Wallet, Wallet]:
    """Spending (everyone has it), Savings and the IBKR investment wallet."""
    savings, ibkr = await asyncio.gather(
        wallet_cases.add_wallet(uow(), user.id, "Savings", "savings"),
        wallet_cases.add_wallet(
            uow(), user.id, "IBKR", "investment", ["interactive brokers", "ibkr"]
        ),
    )
    everything = await wallet_cases.list_wallets(uow(), user.id)
    return next(w for w in everything if w.kind is WalletKind.SPENDING), savings, ibkr


async def _cards(uow: UowFactory, user: User) -> _Cards:
    """Two made-up credit cards (the only digits are the last four of each), the Citi one
    the usual card."""
    citi, dbs = await asyncio.gather(
        wallet_cases.add_wallet(
            uow(), user.id, CITI, "card",
            issuer="Citi", product="PremierMiles", network="visa", last4="4321",
        ),
        wallet_cases.add_wallet(
            uow(), user.id, DBS, "card",
            issuer="DBS", product="Altitude", network="mastercard", last4="8765",
        ),
    )  # fmt: skip
    await wallet_cases.set_usual_card(uow(), user.id, citi.id)
    return _Cards(citi, dbs)


# --- salary ----------------------------------------------------------------------------


async def _schedule(uow: UowFactory, user: User, days: _Days) -> list[date]:
    """Paid on the 25th by Acme, SGD 6,200 as a rule. Returns the last two paydays."""
    schedule = await salary_cases.set_schedule(
        uow(), user, PayRule.MONTHLY_DAY, day=25, payer=PAYER, now=days.now
    )
    await salary_cases.set_baseline(uow(), user, Money.of(SALARY, user.home_currency), now=days.now)
    return paydays(schedule, days.first, days.today)[-2:]


async def _log_salary(uow: UowFactory, user: User, days: _Days, recent: list[date]) -> None:
    """The salary that came in on each of those paydays."""
    for day in recent:
        await salary_cases.log_payday_salary(uow, user, day, now=days.on(day, "09:30"))


# --- the ledger ------------------------------------------------------------------------

# The ledger is written in this many units of work at once (it helps when the database is a
# network away, where each round trip counts).
LEDGER_PARTS = 3

type _Expense = tuple[tx_cases.NewTransaction, bool]  # and whether Ann shares the bill


@dataclass(frozen=True, slots=True)
class _Move:
    amount: int
    origin: Wallet
    target: Wallet
    day: date
    at: str
    note: str


def _expenses(
    user: User, days: _Days, categories: dict[str, UUID], cards: _Cards
) -> list[_Expense]:
    """Everyday spending, plus the subscriptions, rent, phone and electricity of the earlier
    months (this month's rent goes through its bill). Some are paid with a card."""
    home = user.home_currency

    def expense(
        when: datetime, merchant: str, amount: str, category: str | None, note: str | None = None
    ) -> tx_cases.NewTransaction:
        return tx_cases.NewTransaction(
            direction=Direction.OUT,
            amount=Money.of(amount, home),
            occurred_at=when,
            counterparty=merchant,
            category_id=categories[category] if category else None,
            notes=note,
            source=Source.TEXT,
            paid_with_wallet_id=cards.paying(merchant, category, amount),
        )

    found: list[_Expense] = [
        (
            expense(days.ago(r.days_ago, r.at), r.merchant, r.amount, r.category, r.note),
            r.with_friend,
        )
        for r in _SPENDING
    ]
    for name, amount, before, since in (_NETFLIX, _SPOTIFY):
        last = days.today - timedelta(days=since)
        for back in range(3):
            if (charged := _months_before(last, back)) >= days.first:
                price = amount if back == 0 else before
                found.append((expense(days.on(charged, "06:30"), name, price, SUBS), False))

    def bill(due: date, merchant: str, amount: str, at: str) -> _Expense:
        note = f"Bill due {due:%-d %b %Y}"
        return expense(days.on(due, at), merchant, amount, BILLS, note), False

    first = date(days.today.year, days.today.month, 1)
    for back in range(1, 4):
        if (due := _months_before(first, back)) >= days.first:
            found.append(bill(due, "Rent", RENT, "09:15"))
        if (due := _months_before(_phone_due(days), back)) >= days.first:
            found.append(bill(due, "Singtel", PHONE, "10:00"))
        if (due := _months_before(_electricity_due(days), back)) >= days.first:
            found.append(bill(due, "SP Group", _ELECTRICITY[back - 1], "10:00"))
    return found


def _moves(
    days: _Days, recent: list[date], spending: Wallet, savings: Wallet, ibkr: Wallet
) -> list[_Move]:
    """A thousand into Savings and some into the brokerage after each payday, and a
    top-up of the emergency fund in between."""
    found: list[_Move] = []
    for day in recent:
        found.append(_Move(1000, spending, savings, day, "18:00", "Monthly savings"))
        found.append(
            _Move(600, spending, ibkr, day + timedelta(days=1), "10:00", "Top up brokerage")
        )
    found.append(
        _Move(
            200,
            spending,
            savings,
            days.today - timedelta(days=33),
            "12:00",
            "Emergency fund top-up",
        )
    )
    return [m for m in found if m.day <= days.today]


async def _ledger(
    uow: UowFactory,
    user: User,
    days: _Days,
    categories: dict[str, UUID],
    recent: list[date],
    cards: _Cards,
    spending: Wallet,
    savings: Wallet,
    ibkr: Wallet,
) -> list[Transaction]:
    """Spending and moves, written a few units of work at once, each in a single
    transaction. Returns the expenses to split with Ann."""
    expenses = _expenses(user, days, categories, cards)
    moves = _moves(days, recent, spending, savings, ibkr)
    written = await asyncio.gather(
        *(
            _write(uow, user, days, expenses[part::LEDGER_PARTS], moves if part == 0 else [])
            for part in range(LEDGER_PARTS)
        )
    )
    return [tx for part in written for tx in part]


async def _write(
    uow: UowFactory, user: User, days: _Days, expenses: list[_Expense], moves: list[_Move]
) -> list[Transaction]:
    shared: list[Transaction] = []
    async with uow() as db:
        for command, with_friend in expenses:
            tx = await tx_cases.create_transaction(db.ledger, user.id, command, now=days.now)
            if with_friend:
                shared.append(tx)
        for move in moves:
            await wallet_cases.create_move(
                db.ledger,
                user.id,
                amount=Money.of(move.amount, user.home_currency),
                origin=move.origin,
                target=move.target,
                occurred_at=days.on(move.day, move.at),
                now=days.now,
                notes=move.note,
                source=Source.TEXT,
            )
        await db.commit()
    return shared


# --- bills and subscriptions -----------------------------------------------------------


def _phone_due(days: _Days) -> date:
    return days.today + timedelta(days=9)


def _electricity_due(days: _Days) -> date:
    """Due in three days: it is on Home's list."""
    return days.today + timedelta(days=3)


async def _bills(uow: UowFactory, user: User, days: _Days) -> None:
    """Rent (this month's paid), the phone, and electricity coming up. The earlier months'
    payments were logged with the ledger."""
    home, now = user.home_currency, days.now
    rent_due = date(days.today.year, days.today.month, 1)

    async def rent() -> None:
        bill = await bill_cases.add_bill(
            uow(), user, "Rent", rent_due, Cadence.MONTHLY, Money.of(RENT, home), now=now
        )
        await bill_cases.mark_paid(uow, user, bill.id, now=days.on(rent_due, "09:15"), due=rent_due)

    await asyncio.gather(
        rent(),
        bill_cases.add_bill(
            uow(), user, "Singtel", _phone_due(days), Cadence.MONTHLY, Money.of(PHONE, home),
            now=now,
        ),
        bill_cases.add_bill(
            uow(), user, "SP Group", _electricity_due(days), Cadence.MONTHLY,
            Money.of(ELECTRICITY_ESTIMATE, home), now=now,
        ),
    )  # fmt: skip


async def _subscriptions(uow: UowFactory, user: User, days: _Days) -> None:
    """Netflix and Spotify, tracked. Their charges are in the ledger."""
    home, now = user.home_currency, days.now
    async with uow() as db:
        for name, amount, before, since in (_NETFLIX, _SPOTIFY):
            raised = amount != before
            last = days.today - timedelta(days=since)
            await db.planning.insert_subscription(
                Subscription(
                    id=uuid4(),
                    user_id=user.id,
                    key=merchant_key(name) or name.casefold(),
                    name=name,
                    cadence=Cadence.MONTHLY,
                    amount=Money.of(amount, home),
                    last_charged_on=last,
                    status=SubscriptionStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                    previous_amount=Money.of(before, home) if raised else None,
                    price_changed_on=last if raised else None,
                )
            )
        await db.commit()


# --- budgets ---------------------------------------------------------------------------


async def _budgets(uow: UowFactory, user: User, days: _Days, categories: dict[str, UUID]) -> None:
    """A monthly limit per category, set from what this month's ledger shows so the figures
    land where the demo wants them whichever day of the month it is: Dining Out nearly used
    up, the others comfortably under."""
    home = user.home_currency
    month = month_start(days.today)
    summary = await tx_cases.summarize(
        uow(),
        user.id,
        datetime.combine(month, time(), tzinfo=days.tz),
        datetime.combine(next_month_start(month), time(), tzinfo=days.tz),
    )
    spent = {
        c.category_name: c.total.amount
        for c in summary.spending_by_category
        if c.total.currency == home
    }
    low, high, least = _BUDGETS[DINING]
    dining = spent.get(DINING, Decimal(0))
    if dining * 100 < least * low:
        # The month has only just begun: a celebration dinner brings Dining Out up to where
        # the demo wants it, so the budget is a believable size rather than a few dollars.
        dinner = (Decimal(least * (low + high)) / 200 - dining).quantize(Decimal("0.01"))
        await tx_cases.log_transaction(
            uow(),
            user.id,
            tx_cases.NewTransaction(
                direction=Direction.OUT,
                amount=Money.of(dinner, home),
                occurred_at=days.ago(0, "19:30"),
                counterparty="Jumbo Seafood",
                category_id=categories[DINING],
                notes="Anniversary dinner",
                source=Source.TEXT,
            ),
        )
        spent[DINING] = dining + dinner
    limits = {
        name: max(_limit_for(spent.get(name, Decimal(0)), low, high), Decimal(least))
        for name, (low, high, least) in _BUDGETS.items()
    }
    await asyncio.gather(
        *(
            budget_cases.set_budget(
                uow(), user, categories[name], Money.of(limit, home), now=days.now
            )
            for name, limit in limits.items()
        )
    )


# --- the trip --------------------------------------------------------------------------


async def _japan(uow: UowFactory, user: User, days: _Days) -> None:
    """Kyoto then Osaka, six days from three weeks out: flights, two hotels, a filled
    itinerary for the first days, places to visit with no day, and a packing list. None
    of the entries is tied to a Google Maps place."""
    home, now = user.home_currency, days.now
    start = days.today + timedelta(days=TRIP_LEAD_DAYS)
    end = start + timedelta(days=TRIP_DAYS - 1)
    switch = start + timedelta(days=3)  # Kyoto, then Osaka
    trip = await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft(
            "Japan", start, end, "JPY", Money.of("3800", home), [FRIEND],
            set_aside=Money.of("1500", home),
            planned={
                "Food": Money.of("650", home),
                "Transport": Money.of("250", home),
                "Activities": Money.of("300", home),
                "Shopping": Money.of("400", home),
            },
            notes="Kyoto for temples and food, then Osaka for the last two nights.",
        ),
        now=now,
    )  # fmt: skip

    async def add(details: dict[str, object], cost: str | None = None) -> None:
        await booking_cases.add_manual(
            uow(), user.id, trip.id, details, Money.of(cost, home) if cost else None, now=now
        )

    await add(
        {"kind": "flight", "provider": "Acme Air", "booked_via": "Acme Air", "reference": "K7Q2ZP",
         "segments": [
             {"number": "ZZ218", "from": "SIN", "to": "KIX",
              "departs": f"{start}T08:25", "arrives": f"{start}T16:20"},
             {"number": "ZZ219", "from": "KIX", "to": "SIN",
              "departs": f"{end}T11:45", "arrives": f"{end}T16:30"},
         ]},
        "486",
    )  # fmt: skip
    await add(
        {"kind": "hotel", "hotel": "Kamo River Inn", "address": "Shimogyo-ku, Kyoto",
         "check_in": start.isoformat(), "check_out": switch.isoformat(),
         "booked_via": "Agoda", "reference": "R41808"},
        "640",
    )  # fmt: skip
    await add(
        {"kind": "hotel", "hotel": "Namba Garden Hotel", "address": "Chuo-ku, Osaka",
         "check_in": switch.isoformat(), "check_out": end.isoformat(),
         "booked_via": "Agoda", "reference": "R41809"},
        "390",
    )  # fmt: skip
    await trip_cases.set_stops(
        uow(), user, trip.id, [Stop("Kyoto", start, switch), Stop("Osaka", switch, end)], now=now
    )
    for number, label in _DAY_LABELS.items():
        await trip_cases.set_day_label(
            uow(), user, trip.id, start + timedelta(days=number), label, now=now
        )
    # The plans and the places to visit go in together, one write (the day makes the
    # difference between them).
    entries = [
        {"kind": "activity", "name": name, "category": category, "note": note,
         "day": (start + timedelta(days=number)).isoformat(), "at": begins, "ends_at": ends}
        for number, begins, ends, name, category, note in _PLANS
    ] + [
        {"kind": "activity", "list_name": group, "name": name, "category": category, "note": note}
        for group, name, category, note in _IDEAS
    ]  # fmt: skip
    parsed = [BookingDraft.from_dict(entry) for entry in entries]
    drafts = [d for d in parsed if d is not None]
    if len(drafts) != len(parsed):  # pragma: no cover - the entries above are all valid
        raise RuntimeError("an entry of the demo trip is not a valid plan")
    await booking_cases.add_ideas(uow(), user.id, trip.id, drafts, now=now)
    await trip_cases.set_packing(
        uow(), user, trip.id, [PackItem(text, done) for text, done in _PACKING], now=now
    )


# --- investments -----------------------------------------------------------------------


async def _investments(uow: UowFactory, user: User, days: _Days) -> None:
    """Four US holdings built up over a few buys, and two stocks watched. Their prices come
    from the usual jobs (the use cases queue them)."""
    for symbol, shares, price, ago in _TRADES:
        await investment_cases.record(
            uow(), user.id, TradeSide.BUY, symbol, Decimal(shares), Money.of(price, "USD"),
            now=days.now, traded_on=days.today - timedelta(days=ago),
        )  # fmt: skip
    for symbol in _WATCHED:
        await research_cases.watch(uow(), user.id, symbol, now=days.now)
