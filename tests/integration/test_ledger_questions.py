"""Questions about the ledger, answered from structured arguments: filters, groups,
measures and a comparison, in the home currency. Figures are the eval seed's."""

from datetime import datetime, time
from decimal import Decimal
from typing import Any

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application.ledger_questions import (
    GroupBy,
    LedgerQuestion,
    Measure,
    ask_ledger,
    previous_period,
)
from nexus.application.users import get_user
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import User
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
    assert "Received, in SGD" in income and "5000.00 SGD over 1" in income


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
