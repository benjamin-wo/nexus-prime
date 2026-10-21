"""The made-up user every evaluation case starts from: two months of ordinary
spending in Singapore, a salary, a split dinner, a budget, bills, a pay schedule,
a category rule, a tracked subscription, a trip to Japan in December, wallets
(IBKR, Savings, Card) with no moves between them, and two open research plans (NVDA, and
AMD with Keep fresh on). Nothing here is real data.

"Now" is Monday 28 September 2026, 2pm in Singapore. The figures the cases check
against are the constants below; a test recomputes them from the ledger.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import bills as bill_cases
from nexus.application import bookings as booking_cases
from nexus.application import budgets as budget_cases
from nexus.application import category_rules as rule_cases
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application import trip_access as access_cases
from nexus.application import trips as trip_cases
from nexus.application import wallets as wallet_cases
from nexus.application.categories import list_categories
from nexus.application.plans import PlanResult
from nexus.application.ports import UnitOfWork
from nexus.application.users import RegisterUser, register_user
from nexus.domain.ledger import Direction, ShareRequest, Source, User
from nexus.domain.money import Money
from nexus.domain.planning import Cadence, PayRule
from nexus.domain.plans import PlanStatus, SavedPlan, Verdict
from nexus.domain.recurring import Subscription, SubscriptionStatus, merchant_key

type UowFactory = Callable[[], UnitOfWork]

TZ = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 9, 28, 14, 0, tzinfo=TZ)
USD_SGD = Decimal("1.35")  # the one published rate, from 1 Sep 2026

# (day, merchant, amount, currency, category, direction)
_ROWS: tuple[tuple[date, str, str, str, str, Direction], ...] = (
    (date(2026, 8, 3), "Grab", "14.20", "SGD", "Transport", Direction.OUT),
    (date(2026, 8, 8), "Grab", "22.60", "SGD", "Transport", Direction.OUT),
    (date(2026, 8, 9), "Grab", "18.00", "SGD", "Transport", Direction.OUT),
    (date(2026, 8, 12), "Netflix", "15.98", "SGD", "Subscriptions & Software", Direction.OUT),
    (date(2026, 8, 14), "NTUC FairPrice", "64.30", "SGD", "Groceries", Direction.OUT),
    (date(2026, 8, 20), "Kopitiam", "6.80", "SGD", "Dining Out", Direction.OUT),
    (date(2026, 8, 22), "Uniqlo", "59.90", "SGD", "Shopping", Direction.OUT),
    (date(2026, 8, 25), "ACME Pte Ltd", "5000.00", "SGD", "Income", Direction.IN),
    (date(2026, 8, 28), "Singtel", "45.00", "SGD", "Bills & Utilities", Direction.OUT),
    (date(2026, 9, 2), "Grab", "12.50", "SGD", "Transport", Direction.OUT),
    (date(2026, 9, 3), "Shopee", "34.90", "SGD", "Shopping", Direction.OUT),
    (date(2026, 9, 5), "Grab", "25.40", "SGD", "Transport", Direction.OUT),
    (date(2026, 9, 6), "Grab", "16.30", "SGD", "Transport", Direction.OUT),
    (date(2026, 9, 8), "OpenAI ChatGPT", "20.00", "USD", "Subscriptions & Software", Direction.OUT),
    (date(2026, 9, 10), "NTUC FairPrice", "88.45", "SGD", "Groceries", Direction.OUT),
    (date(2026, 9, 12), "Netflix", "17.98", "SGD", "Subscriptions & Software", Direction.OUT),
    (date(2026, 9, 15), "Kopitiam", "7.20", "SGD", "Dining Out", Direction.OUT),
    (date(2026, 9, 18), "Toast Box", "5.60", "SGD", "Dining Out", Direction.OUT),
    (date(2026, 9, 19), "Jumbo Seafood", "120.00", "SGD", "Dining Out", Direction.OUT),
    (date(2026, 9, 21), "Guardian", "23.50", "SGD", "Health", Direction.OUT),
    (date(2026, 9, 24), "Golden Village", "28.00", "SGD", "Activities", Direction.OUT),
    (date(2026, 9, 25), "ACME Pte Ltd", "5000.00", "SGD", "Income", Direction.IN),
    (date(2026, 9, 26), "Starbucks", "6.90", "SGD", "Dining Out", Direction.OUT),
    (date(2026, 9, 27), "Grab", "42.10", "SGD", "Transport", Direction.OUT),
    (date(2026, 9, 28), "Kopitiam", "4.20", "SGD", "Dining Out", Direction.OUT),
)

# What the cases check replies against (home currency, SGD).
SEPT_SPENT = "460.03"  # includes USD 20.00 at 1.35
AUG_SPENT = "246.78"
SEPT_GRAB = "96.30"
AUG_GRAB = "54.80"
SEPT_WEEKEND_GRAB = "83.80"
SEPT_DINING = "143.90"
SEPT_BIGGEST = "120.00"  # Jumbo Seafood, 19 Sep
ANN_OWES = "40.00"  # from the Jumbo Seafood dinner, split three ways
DINING_BUDGET = "300.00"


# The owner of the shared Japan trip gets this id on top of the case user's.
OWNER_OFFSET = 5_000_000
OWNER_NAME = "Alex"
JAPAN_BUDGET = "3000"


@dataclass(frozen=True, slots=True)
class Seeded:
    user: User
    # With ``shared``: the made-up person who owns the Japan trip the user was added to,
    # and the trip's id. Otherwise the user owns the trip and these are None.
    owner: User | None = None
    trip_id: UUID | None = None


async def _japan(new_uow: UowFactory, owner: User) -> UUID:
    """A trip to Japan in December with a budget and a hotel, for ``owner``."""
    trip = await trip_cases.create_trip(
        new_uow(),
        owner,
        trip_cases.TripDraft(
            "Tokyo, Japan", date(2026, 12, 10), date(2026, 12, 18), "JPY",
            Money.of(JAPAN_BUDGET, "SGD"), ["Ann"],
        ),
        now=NOW,
    )  # fmt: skip
    await booking_cases.add_manual(
        new_uow(), owner.id, trip.id,
        {"kind": "hotel", "hotel": "Hotel Sakura", "check_in": "2026-12-10",
         "check_out": "2026-12-14"},
        None, now=NOW,
    )  # fmt: skip
    return trip.id


def open_plan(user: User, symbol: str, close: str, *, keep_fresh: bool) -> SavedPlan:
    """A made-up open research plan: wait for a dip to a buy zone, with a stop and a target."""
    low, high, stop, target = (
        Decimal(close) * Decimal(f) for f in ("0.94", "0.96", "0.90", "1.10")
    )
    low, high, stop, target = (v.quantize(Decimal("0.01")) for v in (low, high, stop, target))
    made = datetime(2026, 9, 25, 22, 0, tzinfo=TZ)
    result = PlanResult(
        plan_id=uuid4(),
        symbol=symbol,
        as_of=date(2026, 9, 25),
        close=Decimal(close),
        verdict=Verdict.WAIT,
        verdict_text="Wait for a dip to buy",
        reason="It's above the buy zone; support at the 50-day average is a better price.",
        entry_low=low,
        entry_high=high,
        entry_why="50-day average",
        stop=stop,
        risk=high - stop,
        targets=[],
        valid_until=date(2026, 10, 9),
        earnings_in_window=None,
        trend=None,
        held=None,
        held_gain_percent=None,
        levels=[],
        technical="",
        news=[],
        risks=[],
        bull=[],
        bear=[],
        summary="Wait for a dip to the buy zone.",
        invalidation=f"A daily close below {stop} would prove it wrong.",
        sources=[],
        atr=Decimal("3.50"),
    )
    return SavedPlan(
        id=result.plan_id,
        user_id=user.id,
        run_id=None,
        symbol=symbol,
        verdict=result.verdict,
        as_of=result.as_of,
        valid_until=result.valid_until,
        close=result.close,
        entry_low=low,
        entry_high=high,
        stop=stop,
        body=result.model_dump(mode="json"),
        status=PlanStatus.OPEN,
        created_at=made,
        keep_fresh=keep_fresh,
    )


async def seed_user(new_uow: UowFactory, telegram_id: int, *, shared: bool = False) -> Seeded:
    """The case's user. With ``shared`` they don't own the Japan trip: Alex does, and
    the user was added to it as a member."""
    user = (
        await register_user(
            new_uow(),
            RegisterUser(
                telegram_user_id=telegram_id,
                telegram_chat_id=telegram_id,
                home_currency="SGD",
                timezone="Asia/Singapore",
            ),
        )
    ).user
    cats = {c.name: c.id for c in await list_categories(new_uow(), user.id)}
    # Wallets for the move cases. No moves are seeded, so every figure below stands.
    await wallet_cases.add_wallet(new_uow(), user.id, "IBKR", "investment", ["interactive brokers"])
    await wallet_cases.add_wallet(new_uow(), user.id, "Savings", "savings")
    await wallet_cases.add_wallet(new_uow(), user.id, "Card", "card", ["credit card"])
    jumbo = None
    for day, merchant, amount, currency, category, direction in _ROWS:
        tx = await tx_cases.log_transaction(
            new_uow(),
            user.id,
            tx_cases.NewTransaction(
                direction=direction,
                amount=Money.of(amount, currency),
                occurred_at=datetime.combine(day, time(12, 0), tzinfo=TZ),
                counterparty=merchant,
                category_id=cats[category],
                source=Source.TEXT,
            ),
        )
        if merchant == "Jumbo Seafood":
            jumbo = tx
    if jumbo is None:  # pragma: no cover - the rows above include it
        raise RuntimeError("the seed has no Jumbo Seafood dinner to split")
    await split_cases.split_bill(
        new_uow(), user.id, jumbo.id, [ShareRequest("Ann"), ShareRequest("Ben")]
    )
    await budget_cases.set_budget(
        new_uow(), user, cats["Dining Out"], Money.of(DINING_BUDGET, "SGD"), now=NOW
    )
    await bill_cases.add_bill(
        new_uow(), user, "Rent", date(2026, 10, 1), Cadence.MONTHLY, Money.of("1800", "SGD"),
        now=NOW,
    )  # fmt: skip
    await bill_cases.add_bill(
        new_uow(), user, "Singtel", date(2026, 10, 28), Cadence.MONTHLY, Money.of("45", "SGD"),
        now=NOW,
    )  # fmt: skip
    await salary_cases.set_schedule(new_uow(), user, PayRule.MONTHLY_DAY, day=25, now=NOW)
    await salary_cases.set_baseline(new_uow(), user, Money.of("5000", "SGD"), now=NOW)
    await rule_cases.set_rule(new_uow(), user, "grab", cats["Transport"], now=NOW)
    async with new_uow() as db:
        await db.investments.insert_plan(open_plan(user, "NVDA", "130.00", keep_fresh=False))
        await db.investments.insert_plan(open_plan(user, "AMD", "140.00", keep_fresh=True))
        await db.planning.insert_subscription(
            Subscription(
                id=uuid4(),
                user_id=user.id,
                key=merchant_key("Netflix") or "netflix",
                name="Netflix",
                cadence=Cadence.MONTHLY,
                amount=Money.of("17.98", "SGD"),
                last_charged_on=date(2026, 9, 12),
                status=SubscriptionStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
                previous_amount=Money.of("15.98", "SGD"),
                price_changed_on=date(2026, 9, 12),
            )
        )
        await db.commit()
    if not shared:
        return Seeded(user, trip_id=await _japan(new_uow, user))
    owner = (
        await register_user(
            new_uow(),
            RegisterUser(
                telegram_user_id=telegram_id + OWNER_OFFSET,
                telegram_chat_id=telegram_id + OWNER_OFFSET,
                home_currency="SGD",
                timezone="Asia/Singapore",
            ),
        )
    ).user
    async with new_uow() as db:
        await db.ledger.set_display_name(owner.id, OWNER_NAME)
        await db.commit()
    trip_id = await _japan(new_uow, owner)
    issued = await access_cases.create_invite(new_uow(), owner, trip_id, now=NOW)
    await access_cases.accept_invite(new_uow(), user, issued.token, now=NOW)
    return Seeded(user, owner, trip_id)
