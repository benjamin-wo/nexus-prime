"""Put away, total out and the saving rate, and proof that moves between wallets leave
every spending and income figure alone. Made-up names and amounts only."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.snapshot import money_snapshot
from nexus.agent.tools import ToolContext
from nexus.application import budgets as budget_cases
from nexus.application import duplicates as duplicate_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application import transactions as tx_cases
from nexus.application import trips as trip_cases
from nexus.application.cashflow import cash_flow
from nexus.application.categories import list_categories
from nexus.application.ledger_questions import LedgerQuestion, ask_ledger
from nexus.application.notifications import set_frequency
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import NewTransaction, delete_transaction, log_transaction
from nexus.application.wallet_figures import (
    month_figures,
    month_range,
    put_away,
    total_out,
    wallet_figures,
)
from nexus.application.wallets import add_wallet, list_wallets, log_move
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, Source, User, WalletKind
from nexus.domain.money import Money
from nexus.domain.notifications import Frequency
from tests.fakes import FakeRates
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person
from tests.integration.test_notifications import check, sent
from tests.integration.test_notifications import log as log_at
from tests.integration.test_trips import MADE, draft, spend

pytestmark = pytest.mark.integration

SG = ZoneInfo("Asia/Singapore")
RATES = FakeRates({("USD", "SGD"): {date(2026, 9, 1): "1.30"}})


def sg(day: int, hour: int = 12, month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=SG)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def dec(value: str) -> Decimal:
    return Decimal(value)


class Wallets:
    """A user's wallets by kind, for building moves."""

    def __init__(self, uow: UowFactory, user: User) -> None:
        self.uow, self.user = uow, user
        self.spending: UUID
        self.card: UUID
        self.investments: UUID
        self.savings: UUID

    @classmethod
    async def create(cls, uow: UowFactory, user: User) -> "Wallets":
        found = cls(uow, user)
        found.spending = (await list_wallets(uow(), user.id))[0].id
        found.card = (await add_wallet(uow(), user.id, "Card", WalletKind.CARD)).id
        found.investments = (
            await add_wallet(uow(), user.id, "Investments", WalletKind.INVESTMENT)
        ).id
        found.savings = (await add_wallet(uow(), user.id, "Savings", WalletKind.SAVINGS)).id
        return found

    async def move(
        self,
        amount: str,
        origin: UUID,
        target: UUID,
        at: datetime,
        *,
        currency: str = "SGD",
        counterparty: str | None = None,
    ) -> UUID:
        tx = await log_move(
            self.uow(),
            self.user.id,
            amount=Money.of(amount, currency),
            from_wallet_id=origin,
            to_wallet_id=target,
            occurred_at=at,
            counterparty=counterparty,
        )
        return tx.id


async def log(
    uow: UowFactory,
    user: User,
    amount: str,
    at: datetime,
    *,
    direction: Direction = Direction.OUT,
    category: str | None = None,
    counterparty: str | None = None,
    source: Source = Source.MANUAL,
) -> UUID:
    category_id = None
    if category:
        category_id = next(
            c.id for c in await list_categories(uow(), user.id) if c.name == category
        )
    tx = await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            direction,
            sgd(amount),
            at,
            counterparty=counterparty,
            category_id=category_id,
            source=source,
        ),
    )
    return tx.id


async def seed_month(uow: UowFactory, user: User) -> None:
    """September: 5,000 earned, 2,600 spent."""
    await log(uow, user, "5000", sg(1), direction=Direction.IN, counterparty="Employer")
    await log(uow, user, "1500", sg(2), category="Bills & Utilities", counterparty="Landlord")
    await log(uow, user, "700", sg(8), category="Dining Out", counterparty="Hawker Row")
    await log(uow, user, "400", sg(12), category="Shopping", counterparty="Mall")


async def worked_example_moves(w: Wallets) -> None:
    await w.move("900", w.spending, w.card, sg(3))
    await w.move("1000", w.spending, w.investments, sg(4))
    await w.move("500", w.spending, w.savings, sg(5))
    await w.move("300", w.savings, w.spending, sg(6))


# --- the numbers --------------------------------------------------------------------


async def test_the_worked_example(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await seed_month(uow, user)
    await worked_example_moves(w)

    figures = await month_figures(uow, FakeRates(), user, now=sg(15))
    assert figures.spent == sgd("2600")
    assert figures.income == sgd("5000")
    assert figures.put_away == sgd("1200")  # 1,000 + 500 in, 300 back out
    assert figures.saving_rate == dec("0.24")
    assert figures.total_out == sgd("4100")  # 2,600 spent + 1,000 + 500; the card is no extra
    assert figures.unconverted == []
    assert (figures.start, figures.end) == (sg(1, 0), sg(1, 0, month=10))

    # The same numbers on their own, for any period.
    assert await put_away(uow, FakeRates(), user, sg(1, 0), sg(1, 0, 10)) == sgd("1200")
    assert await total_out(uow, FakeRates(), user, sg(1, 0), sg(1, 0, 10)) == sgd("4100")
    # Only the first four days: the 300 back from Savings hasn't happened yet.
    early = await wallet_figures(uow, FakeRates(), user, sg(1, 0), sg(6, 0))
    assert early.put_away == sgd("1500")


async def test_money_between_savings_and_investments_nets_to_nothing(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await seed_month(uow, user)
    await w.move("1000", w.spending, w.savings, sg(3))
    await w.move("600", w.savings, w.investments, sg(4))
    await w.move("250", w.investments, w.savings, sg(5))

    figures = await month_figures(uow, FakeRates(), user, now=sg(15))
    assert figures.put_away == sgd("1000")
    assert figures.total_out == sgd("3600")


async def test_only_savings_and_investments_count_as_put_away(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    other = (await add_wallet(uow(), user.id, "Shoebox", WalletKind.OTHER)).id
    await seed_month(uow, user)
    await w.move("400", w.spending, other, sg(3))  # out of Spending, but not put away
    await w.move("100", w.card, w.spending, sg(4))  # neither
    await w.move("50", other, w.investments, sg(5))  # from any other wallet counts

    figures = await month_figures(uow, FakeRates(), user, now=sg(15))
    assert figures.put_away == sgd("50")
    assert figures.total_out == sgd("3000")  # 2,600 + 400 to a non-card wallet


async def test_a_foreign_currency_move_is_converted_at_its_days_rate(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await seed_month(uow, user)
    await w.move("100", w.spending, w.investments, sg(5), currency="USD")  # 130.00 SGD
    await w.move("40", w.investments, w.spending, sg(9), currency="USD")  # 52.00 back

    figures = await month_figures(uow, RATES, user, now=sg(15))
    assert figures.put_away == sgd("78")
    assert figures.total_out == sgd("2730")  # 2,600 + 130
    assert figures.saving_rate == dec("0.0156")

    # With no rate for the day, the amount is reported, not guessed.
    bare = await month_figures(uow, FakeRates(), user, now=sg(15))
    assert bare.put_away == sgd("0") and bare.total_out == sgd("2600")
    assert bare.unconverted == [Money.of("140", "USD")]


async def test_there_is_no_saving_rate_without_income(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await log(uow, user, "20", sg(2), counterparty="Kopi")
    await w.move("100", w.spending, w.savings, sg(3))
    figures = await month_figures(uow, FakeRates(), user, now=sg(15))
    assert figures.income == sgd("0") and figures.put_away == sgd("100")
    assert figures.saving_rate is None


async def test_deleted_and_out_of_period_moves_are_left_out(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await seed_month(uow, user)
    kept = await w.move("500", w.spending, w.savings, sg(5))
    gone = await w.move("700", w.spending, w.savings, sg(6))
    await w.move("900", w.spending, w.savings, sg(30, 12, 8))  # August
    await w.move("800", w.spending, w.savings, sg(1, 0, 10))  # the first instant of October
    await delete_transaction(uow(), user.id, gone)

    figures = await month_figures(uow, FakeRates(), user, now=sg(15))
    assert figures.put_away == sgd("500") and kept != gone
    assert figures.total_out == sgd("3100")


async def test_a_month_is_the_users_own(uow: UowFactory) -> None:
    user = await person(uow)  # Singapore, eight hours ahead of UTC
    w = await Wallets.create(uow, user)
    # 00:30 on 1 October in Singapore is still 30 September in UTC.
    await w.move("200", w.spending, w.savings, sg(1, 0, 10).replace(minute=30))
    await w.move("100", w.spending, w.savings, datetime(2026, 9, 30, 15, 59, tzinfo=UTC))

    start, end = month_range(user, datetime(2026, 10, 20, tzinfo=UTC))
    assert (start, end) == (sg(1, 0, 10), sg(1, 0, 11))
    october = await month_figures(uow, FakeRates(), user, now=datetime(2026, 10, 20, tzinfo=UTC))
    september = await month_figures(uow, FakeRates(), user, now=sg(15))
    assert (october.put_away, september.put_away) == (sgd("200"), sgd("100"))


async def test_a_bad_period_is_refused(uow: UowFactory) -> None:
    user = await person(uow)
    with pytest.raises(InvalidInput):
        await wallet_figures(uow, FakeRates(), user, sg(2), sg(1))
    with pytest.raises(InvalidInput):
        await wallet_figures(uow, FakeRates(), user, datetime(2026, 9, 1), sg(1))


# --- moves leave the other figures alone ---------------------------------------------


async def test_moves_leave_budgets_and_summaries_alone(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    dining = next(c.id for c in await list_categories(uow(), user.id) if c.name == "Dining Out")
    await budget_cases.set_budget(uow(), user, None, sgd("3000"), now=sg(1))
    await budget_cases.set_budget(uow(), user, dining, sgd("800"), now=sg(1))
    await seed_month(uow, user)
    await log(uow, user, "12", sg(9), category="Dining Out", counterparty="Coffee")
    await log(uow, user, "10", sg(10), counterparty="USD shop")  # SGD, just to vary

    async def picture() -> tuple[object, ...]:
        statuses = await budget_cases.budget_statuses(uow, RATES, user, now=sg(15))
        home = await tx_cases.summarize_in_home(uow(), RATES, user, sg(1, 0), sg(1, 0, 10))
        plain = await tx_cases.summarize(uow(), user.id, sg(1, 0), sg(1, 0, 10))
        return (
            [(s.name, s.spent, s.unconverted, s.percent) for s in statuses],
            home.totals,
            home.spending_by_category,
            plain.totals,
            plain.spending_by_category,
        )

    before = await picture()
    await worked_example_moves(w)
    await w.move("100", w.spending, w.investments, sg(5), currency="USD")
    assert await picture() == before

    statuses = await budget_cases.budget_statuses(uow, RATES, user, now=sg(15))
    assert [(s.name, s.spent) for s in statuses] == [
        ("Overall", sgd("2622")),
        ("Dining Out", sgd("712")),
    ]
    # The month's spending, as the web chart and summary read it: by direction.
    home = await tx_cases.summarize_in_home(uow(), RATES, user, sg(1, 0), sg(1, 0, 10))
    assert [t.direction for t in home.totals] == [Direction.OUT, Direction.IN]
    assert home.out.total == sgd("2622") and home.income.total == sgd("5000")


async def test_a_move_has_no_repayments_in_the_repository_totals(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await w.move("800", w.spending, w.investments, sg(5))
    async with uow() as tx:
        by_direction = await tx.ledger.totals_by_direction(user.id, sg(1, 0), sg(1, 0, 10))
        by_day = await tx.ledger.totals_by_day(user.id, sg(1, 0), sg(1, 0, 10), user.timezone)
    assert [(t.direction, t.total) for t in by_direction] == [(Direction.MOVE, sgd("800"))]
    assert [(t.direction, t.total) for t in by_day] == [(Direction.MOVE, sgd("800"))]


async def test_moves_leave_cash_flow_alone(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await seed_month(uow, user)

    async def days() -> list[tuple[date, Money, Money]]:
        flow = await cash_flow(uow, RATES, user, date(2026, 9, 1), date(2026, 9, 30), now=sg(15))
        return [(d.day, d.money_in, d.money_out) for d in flow.days]

    before = await days()
    await worked_example_moves(w)
    await w.move("100", w.spending, w.investments, sg(5), currency="USD")
    assert await days() == before
    flow = await cash_flow(uow, RATES, user, date(2026, 9, 1), date(2026, 9, 30), now=sg(15))
    assert (flow.logged_in, flow.logged_out) == (sgd("5000"), sgd("2600"))


async def test_a_summary_lists_moves_apart_from_spending_and_income(
    engine: AsyncEngine, uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    ann = await person(uow, 4242)
    ben = await person(uow, 4243)
    wallets = await Wallets.create(uow, ann)
    assert await check(uow, ann, sg(28, 8)) is False
    assert await check(uow, ben, sg(28, 8)) is False
    for user in (ann, ben):  # logged as of their own time, so the summary finds them
        await log_at(uow, user, "40", sg(28, 9), category="Dining Out", counterparty="Hawker Row")
        await log_at(uow, user, "3000", sg(28, 10), direction=Direction.IN, counterparty="Employer")
    # A move is stored as logged at the moment of the call.
    monkeypatch.setattr("nexus.application.wallets.utcnow", lambda: sg(28, 11))
    await wallets.move("800", wallets.spending, wallets.investments, sg(28, 11))
    await wallets.move("300", wallets.savings, wallets.spending, sg(28, 12))

    assert await check(uow, ann, sg(28, 21).replace(minute=2))
    assert await check(uow, ben, sg(28, 21).replace(minute=2))
    by_user = {p["user_id"]: p["text"].splitlines() for p in await sent(engine)}
    mine, theirs = by_user[str(ann.id)], by_user[str(ben.id)]
    assert [line for line in mine if not line.startswith("Moved")] == theirs
    assert "Moved 800.00 SGD to Investments." in mine
    assert "Moved 300.00 SGD from Savings to Spending." in mine
    assert "You spent 40.00 SGD (1 transaction)." in mine
    assert "You received 3000.00 SGD (1 transaction)." in mine


async def test_an_instant_message_names_the_wallet(
    engine: AsyncEngine, uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await person(uow)
    wallets = await Wallets.create(uow, user)
    await set_frequency(uow(), user.id, Frequency.INSTANT, now=sg(28, 8))
    monkeypatch.setattr("nexus.application.wallets.utcnow", lambda: sg(28, 9))
    await wallets.move("800", wallets.spending, wallets.investments, sg(28, 9))
    assert await check(uow, user, sg(28, 10))
    [message] = await sent(engine)
    assert message["text"] == "🧾 Moved 800.00 SGD to Investments."


async def test_moves_are_not_trip_spending(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    trip = await trip_cases.create_trip(uow(), user, draft(), now=MADE)
    await spend(uow, user, "2000", datetime(2027, 1, 10, 13, tzinfo=SG))
    on_day_3 = datetime(2027, 1, 12, 22, tzinfo=SG)
    rates = FakeRates({("JPY", "SGD"): {date(2026, 11, 1): "0.0090"}})
    before = await trip_cases.trip_view(uow, rates, user, trip.id, now=on_day_3)

    # In the trip's currency and on its days: it would be spending, were it money out.
    moved = await w.move(
        "50000", w.spending, w.savings, datetime(2027, 1, 11, tzinfo=SG), currency="JPY"
    )
    after = await trip_cases.trip_view(uow, rates, user, trip.id, now=on_day_3)
    assert after.spending == before.spending and len(after.items) == len(before.items) == 1
    with pytest.raises(InvalidInput):
        await trip_cases.add_expense(uow(), user.id, trip.id, moved, now=MADE)


async def test_moves_are_not_subscriptions(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    for month in (7, 8, 9):  # the same amount, to the same place, every month
        await w.move(
            "15.98", w.spending, w.savings, sg(12, 9, month), counterparty=f"NETFLIX.COM {month}"
        )
    await subscription_cases.check(uow, user, now=sg(20))
    assert await sent(engine) == []
    overview = await subscription_cases.overview(uow(), user.id)
    assert overview.proposed == [] and overview.tracked == []


async def test_a_move_is_never_a_duplicate_of_an_expense(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    # Same amount, same day, no merchant on either side, from different places.
    expense = await log(uow, user, "800", sg(5), source=Source.TEXT)
    moved = await w.move("800", w.spending, w.investments, sg(5))
    assert await duplicate_cases.find_pairs(uow, user, sg(1, 0), sg(1, 0, 10)) == []
    live = (await tx_cases.list_ledger(uow(), user.id, LedgerQuery(limit=50))).items
    assert await duplicate_cases.matches(uow(), user, live) == {}
    with pytest.raises(InvalidInput):
        await duplicate_cases.merge(uow, user.id, expense, moved)


async def test_a_move_can_be_asked_about_without_disturbing_spending(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await seed_month(uow, user)
    await worked_example_moves(w)
    start, end = sg(1, 0), sg(1, 0, 10)

    spent = await ask_ledger(uow, RATES, user, LedgerQuestion(start=start, end=end))
    assert (spent.current.total, spent.current.count) == (sgd("2600"), 3)
    moves = await ask_ledger(
        uow, RATES, user, LedgerQuestion(start=start, end=end, direction=Direction.MOVE)
    )
    assert (moves.current.total, moves.current.count) == (sgd("2700"), 4)


async def test_the_snapshot_shows_a_move_by_where_it_went(uow: UowFactory) -> None:
    user = await person(uow)
    w = await Wallets.create(uow, user)
    await log(uow, user, "12", sg(14), category="Dining Out", counterparty="Coffee")
    await w.move("800", w.spending, w.investments, sg(15))
    text = await money_snapshot(ToolContext(user, uow, sg(16), FakeRates()))
    assert "Tue 15 Sep: 800.00 SGD → Investments (move)" in text
    assert "Mon 14 Sep: -12.00 SGD Coffee (Dining Out)" in text
    assert "+800" not in text and "-800" not in text
