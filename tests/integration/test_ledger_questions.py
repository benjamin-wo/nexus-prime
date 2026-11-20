"""Questions about the ledger, answered from structured arguments: filters, groups,
measures and a comparison, in the home currency. Figures are the eval seed's."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application.ledger_questions import (
    GroupBy,
    LedgerQuestion,
    LedgerSpan,
    Measure,
    ask_ledger,
    ledger_span,
    previous_period,
)
from nexus.application.transactions import NewTransaction, delete_transaction, log_transaction
from nexus.application.users import RegisterUser, get_user, register_user
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, Transaction, TransactionStatus, User
from nexus.domain.money import Money
from nexus.evals import seed
from nexus.evals.runner import FixedRates
from tests.integration.conftest import UowFactory, make_user

pytestmark = pytest.mark.integration

SEPT = datetime(2026, 9, 1, tzinfo=seed.TZ)
OCT = datetime(2026, 10, 1, tzinfo=seed.TZ)


@pytest.fixture
async def user(uow: UowFactory) -> User:
    return (await seed.seed_user(uow, 7100)).user


async def ask(uow: UowFactory, user: User, args: dict[str, Any]) -> str:
    spec = build_tools(lambda _: "")["query_ledger"]
    ctx = ToolContext(user, uow, seed.NOW, FixedRates())
    return (await run_tool(spec, ctx, args)).text


async def test_a_merchant_on_weekends(uow: UowFactory, user: User) -> None:
    text = await ask(uow, user, {"merchant": "grab", "days": ["weekends"]})
    assert f"{seed.SEPT_WEEKEND_GRAB} SGD over 3 transactions" in text


async def test_foreign_amounts_count_in_the_home_currency(uow: UowFactory, user: User) -> None:
    text = await ask(uow, user, {"merchant": "chatgpt"})
    assert "27.00 SGD over 1 transaction" in text
    assert "includes 20.00 USD converted" in text
    assert "= 27.00 SGD" in text  # the item itself shows both
    whole = await ask(uow, user, {})
    assert f"{seed.SEPT_SPENT} SGD" in whole


async def test_compare_months_by_merchant(uow: UowFactory, user: User) -> None:
    text = await ask(
        uow,
        user,
        {
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "merchant": "grab",
            "group_by": "merchant",
            "compare_previous": True,
        },
    )
    assert f"Grab: {seed.SEPT_GRAB} SGD (4)" in text
    assert f"2026-08-01 to 2026-08-31: {seed.AUG_GRAB} SGD over 3" in text
    assert f"Grab: {seed.AUG_GRAB} SGD before, +41.50 SGD, +76%" in text


async def test_largest_and_ranked_groups(uow: UowFactory, user: User) -> None:
    text = await ask(uow, user, {"measure": "largest", "top": 2})
    lines = text.splitlines()
    assert "Jumbo Seafood" in lines[lines.index("Largest:") + 1]
    assert "FairPrice" in lines[lines.index("Largest:") + 2]  # 88.45, the next biggest

    by_cat = await ask(uow, user, {"group_by": "category", "top": 2})
    assert "Dining Out: 143.90 SGD (5)" in by_cat
    assert "Transport: 96.30 SGD (4)" in by_cat
    assert "more not shown" in by_cat


async def test_amounts_count_and_time_groups(uow: UowFactory, user: User) -> None:
    text = await ask(uow, user, {"min_amount": "30", "measure": "count"})
    assert "over 4 transactions" in text  # Jumbo, FairPrice, Shopee, Grab; ChatGPT is 27 SGD
    months = await ask(
        uow,
        user,
        {"start_date": "2026-08-01", "group_by": "month", "category": "transport"},
    )
    assert months.index("2026-08: 54.80 SGD") < months.index("2026-09: 96.30 SGD")
    income = await ask(uow, user, {"direction": "in"})
    assert "Received, in SGD" in income and "5,000.00 SGD over 1" in income


async def test_bad_arguments_are_refused(uow: UowFactory, user: User) -> None:
    for args in (
        {"min_amount": "50", "max_amount": "10"},
        {"category": "nope"},
        {"start_date": "2026-10-01", "end_date": "2026-09-01"},
        {"top": 500},
        {"group_by": "user_id"},
    ):
        assert (await ask(uow, user, args)).startswith("Error:"), args
    with pytest.raises(InvalidInput):
        await ask_ledger(uow, FixedRates(), user, LedgerQuestion(start=OCT, end=SEPT))


async def test_only_the_users_own_money(uow: UowFactory, user: User) -> None:
    await seed.seed_user(uow, 7101)  # a second user with the same spending
    question = LedgerQuestion(start=SEPT, end=OCT, group_by=GroupBy.MERCHANT)
    mine = await ask_ledger(uow, FixedRates(), user, question)
    assert mine.current.total.amount == Decimal(seed.SEPT_SPENT)
    empty = await get_user(uow(), await make_user(uow, 7102))
    none = await ask_ledger(uow, FixedRates(), empty, question)
    assert none.current.count == 0 and none.current.groups == []


async def test_unconverted_amounts_are_reported_not_guessed(uow: UowFactory, user: User) -> None:
    class NoRates:
        async def rate(self, *_: Any) -> None:
            return None

    answer = await ask_ledger(
        uow, NoRates(), user, LedgerQuestion(start=SEPT, end=OCT, measure=Measure.TOTAL)
    )
    assert [str(m) for m in answer.current.unconverted] == ["20.00 USD"]
    assert answer.current.total.amount == Decimal(seed.SEPT_SPENT) - Decimal("27.00")


def test_the_period_before() -> None:
    assert previous_period(SEPT, OCT, seed.TZ) == (datetime(2026, 8, 1, tzinfo=seed.TZ), SEPT)
    jan = datetime(2026, 1, 1, tzinfo=seed.TZ)
    assert previous_period(jan, datetime(2026, 3, 1, tzinfo=seed.TZ), seed.TZ)[0] == datetime(
        2025, 11, 1, tzinfo=seed.TZ
    )
    start = datetime.combine(seed.NOW.date(), time(), tzinfo=seed.TZ)
    end = datetime(2026, 9, 29, tzinfo=seed.TZ)
    assert previous_period(start, end, seed.TZ) == (datetime(2026, 9, 27, tzinfo=seed.TZ), start)


async def test_time_groups_compare_only_the_totals(uow: UowFactory, user: User) -> None:
    text = await ask(uow, user, {"group_by": "week", "compare_previous": True})
    assert "Period before, 2026-08-04 to 2026-08-31" in text  # the same 28 days before
    assert "SGD before," not in text  # no week of August matches a week of September


# --- how far the ledger goes back, and what a default period says about it ----------------------


async def fresh(uow: UowFactory, telegram_id: int) -> User:
    """A user in the seed's timezone with an empty ledger."""
    registration = await register_user(
        uow(),
        RegisterUser(
            telegram_user_id=telegram_id,
            telegram_chat_id=telegram_id,
            home_currency="SGD",
            timezone="Asia/Singapore",
        ),
    )
    return registration.user


async def log(
    uow: UowFactory, user: User, day: date, *, status: TransactionStatus | None = None
) -> Transaction:
    return await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            Direction.OUT,
            Money.of("10", "SGD"),
            datetime.combine(day, time(12), seed.TZ),
            status=status or TransactionStatus.CONFIRMED,
        ),
    )


async def test_the_span_is_the_first_and_last_transaction(uow: UowFactory, user: User) -> None:
    assert await ledger_span(uow(), user) == LedgerSpan(date(2026, 8, 3), date(2026, 9, 28))


async def test_the_span_counts_the_users_own_confirmed_live_transactions_only(
    uow: UowFactory,
) -> None:
    empty = await fresh(uow, 7110)
    assert await ledger_span(uow(), empty) is None
    await seed.seed_user(uow, 7111)  # someone else's history: August and September
    assert await ledger_span(uow(), empty) is None

    gone = await log(uow, empty, date(2026, 5, 1))
    await log(uow, empty, date(2026, 6, 1), status=TransactionStatus.PENDING)
    await delete_transaction(uow(), empty.id, gone.id)
    assert await ledger_span(uow(), empty) is None  # one deleted, one not confirmed

    await log(uow, empty, date(2026, 7, 4))
    await log(uow, empty, date(2026, 7, 20))
    assert await ledger_span(uow(), empty) == LedgerSpan(date(2026, 7, 4), date(2026, 7, 20))


async def test_the_span_is_in_the_users_own_days(uow: UowFactory) -> None:
    user = await fresh(uow, 7112)
    late = datetime(2026, 7, 31, 23, 30, tzinfo=seed.TZ)  # 31 July in Singapore, 15:30 UTC
    await log_transaction(uow(), user.id, NewTransaction(Direction.OUT, Money.of("5", "SGD"), late))
    span = await ledger_span(uow(), user)
    assert span is not None and span.first == date(2026, 7, 31)


async def test_a_default_period_says_so_and_where_the_ledger_goes_back_to(
    uow: UowFactory, user: User
) -> None:
    text = await ask(uow, user, {})  # on 28 September, with August before it
    assert "Period defaulted to this month." in text
    assert "The ledger goes back to 3 Aug 2026: pass start_date for earlier." in text
    assert f"{seed.SEPT_SPENT} SGD" in text  # still this month's figures
    by_cat = await ask(uow, user, {"group_by": "category", "compare_previous": True})
    assert "The ledger goes back to 3 Aug 2026" in by_cat


async def test_a_start_date_is_not_a_default(uow: UowFactory, user: User) -> None:
    text = await ask(uow, user, {"start_date": "2026-09-01"})
    assert "defaulted" not in text and "goes back" not in text


async def test_months_default_to_the_whole_ledger_not_this_month(
    uow: UowFactory, user: User
) -> None:
    text = await ask(uow, user, {"group_by": "month"})
    assert "Period defaulted to the whole ledger." in text
    assert "The ledger begins 3 Aug 2026, so that is all of it." in text
    assert "2026-08-01 to 2026-09-28" in text
    assert f"2026-08: {seed.AUG_SPENT} SGD" in text and f"2026-09: {seed.SEPT_SPENT} SGD" in text
    explicit = await ask(uow, user, {"group_by": "month", "start_date": "2026-09-01"})
    assert "2026-08:" not in explicit and "defaulted" not in explicit


async def test_months_default_to_at_most_the_last_twelve(uow: UowFactory, user: User) -> None:
    await log(uow, user, date(2025, 3, 14))  # before the window
    await log(uow, user, date(2025, 10, 2))  # its first month: 12 months with September
    text = await ask(uow, user, {"group_by": "month"})
    assert "Period defaulted to the last 12 months." in text
    assert "The ledger goes back to 14 Mar 2025: pass start_date for earlier." in text
    assert "2025-10-01 to 2026-09-28" in text
    assert "2025-10: 10.00 SGD" in text and "2025-03" not in text
    assert f"2026-09: {seed.SEPT_SPENT} SGD" in text  # the newest month is never the one cut
    assert "more not shown" not in text


async def test_a_ledger_that_begins_this_month_says_that_is_all_of_it(uow: UowFactory) -> None:
    user = await fresh(uow, 7113)
    assert "The ledger is empty." in await ask(uow, user, {})
    await log(uow, user, date(2026, 9, 9))
    text = await ask(uow, user, {})
    assert "The ledger begins 9 Sep 2026, so that is all of it." in text
    assert "goes back" not in text
