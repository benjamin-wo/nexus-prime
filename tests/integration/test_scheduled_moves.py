"""Scheduled moves: a not-spending bill that points at a wallet. Marking it done logs the
move, cash flow shows it, and Home asks about one that never showed up. Every name and
figure is made up."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import bills as bill_cases
from nexus.application import budgets as budget_cases
from nexus.application import salary as salary_cases
from nexus.application.cashflow import ExpectedKind, cash_flow
from nexus.application.home import needs_you
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import delete_transaction, list_ledger
from nexus.application.users import get_user
from nexus.application.wallet_figures import month_plan
from nexus.application.wallets import add_wallet, delete_wallet, list_wallets, log_move
from nexus.domain.errors import DuplicateSource, InvalidInput, NotFound
from nexus.domain.ledger import Direction, Transaction, User, UserId, Wallet, WalletKind
from nexus.domain.money import Money
from nexus.domain.planning import Bill, Cadence, PayRule
from nexus.infra.db.tables import bill_occurrences, bills
from tests.fakes import FakeRates
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

SG = ZoneInfo("Asia/Singapore")


def at(month: int, day: int, hour: int = 12) -> datetime:
    """Noon in Singapore on a day of 2026."""
    return datetime(2026, month, day, hour, tzinfo=SG)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def wallets_of(uow: UowFactory, user: UserId) -> dict[str, Wallet]:
    return {w.name: w for w in await list_wallets(uow(), user)}


async def setup(
    uow: UowFactory,
    *,
    who: int = 4242,
    amount: str | None = "1000",
    cadence: Cadence = Cadence.MONTHLY,
    due: date = date(2026, 9, 25),
    created: datetime | None = None,
) -> tuple[User, Bill, dict[str, Wallet]]:
    """A user with IBKR and Savings wallets and an "IBKR top-up" of 1,000 due on the 25th."""
    user = await person(uow, who)
    await add_wallet(uow(), user.id, "IBKR", WalletKind.INVESTMENT)
    await add_wallet(uow(), user.id, "Savings", WalletKind.SAVINGS)
    wallets = await wallets_of(uow, user.id)
    bill = await bill_cases.add_bill(
        uow(),
        user,
        "IBKR top-up",
        due,
        cadence,
        sgd(amount) if amount else None,
        now=created or at(9, 1),
        spending=False,
        wallet_id=wallets["IBKR"].id,
    )
    return user, bill, wallets


async def moves_of(uow: UowFactory, user: UserId) -> list[Transaction]:
    page = await list_ledger(uow(), user, LedgerQuery(direction=Direction.MOVE, limit=100))
    return page.items


async def put(
    uow: UowFactory, user: UserId, to: Wallet, amount: str, when: datetime
) -> Transaction:
    return await log_move(uow(), user, amount=sgd(amount), to_wallet_id=to.id, occurred_at=when)


async def nudges(uow: UowFactory, user: User, now: datetime) -> list[Any]:
    feed = await needs_you(uow, FakeRates(), user, now=now)
    return [i for i in feed if i.kind == "missed_move"]


# --- adding one ---------------------------------------------------------------------


async def test_a_scheduled_move_points_at_a_wallet(uow: UowFactory) -> None:
    user, bill, wallets = await setup(uow)
    assert (bill.spending, bill.wallet_id) == (False, wallets["IBKR"].id)
    (view,) = await bill_cases.list_bills(uow, user, now=at(9, 20))
    assert view.bill.wallet_id == wallets["IBKR"].id and view.due == date(2026, 9, 25)


async def test_a_spending_bill_cannot_have_a_wallet_and_the_wallet_must_be_real(
    uow: UowFactory,
) -> None:
    user, _, wallets = await setup(uow)
    args = (user, "Rent", date(2026, 10, 1), Cadence.MONTHLY, sgd("1800"))
    with pytest.raises(InvalidInput, match="counts as spending"):
        await bill_cases.add_bill(
            uow(), *args, now=at(9, 1), spending=True, wallet_id=wallets["IBKR"].id
        )
    with pytest.raises(InvalidInput, match="other than Spending"):
        await bill_cases.add_bill(
            uow(), *args, now=at(9, 1), spending=False, wallet_id=wallets["Spending"].id
        )
    stranger = await person(uow, 5151)
    theirs = await add_wallet(uow(), stranger.id, "Brokerage", WalletKind.INVESTMENT)
    with pytest.raises(NotFound):
        await bill_cases.add_bill(uow(), *args, now=at(9, 1), spending=False, wallet_id=theirs.id)
    assert [v.bill.name for v in await bill_cases.list_bills(uow, user, now=at(9, 20))] == [
        "IBKR top-up"
    ]


async def test_the_database_refuses_a_wallet_on_a_spending_bill(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    _, bill, _ = await setup(uow)
    async with engine.begin() as db:
        with pytest.raises(IntegrityError, match="wallet_not_spending"):
            await db.execute(
                text("UPDATE bills SET spending = true WHERE id = :id"), {"id": bill.id}
            )


# --- marking it done ----------------------------------------------------------------


async def test_marking_done_logs_one_move_from_spending_to_the_wallet(uow: UowFactory) -> None:
    user, bill, wallets = await setup(uow)
    now = at(9, 25)
    done = await bill_cases.mark_paid(uow, user, bill.id, now=now)
    assert done.moved is not None and done.logged is None and done.already_moved is None
    assert done.message(SG) == (
        "Marked IBKR top-up (25 Sep) as done and logged a move of 1000.00 SGD from "
        "Spending to IBKR."
    )
    (move,) = await moves_of(uow, user.id)
    assert move.id == done.moved.id
    assert (move.from_wallet_id, move.to_wallet_id) == (wallets["Spending"].id, wallets["IBKR"].id)
    assert move.amount == sgd("1000") and move.occurred_at == now
    assert move.counterparty == "IBKR top-up" and move.category_id is None
    # Not spending: nothing went out as an expense.
    out = await list_ledger(uow(), user.id, LedgerQuery(direction=Direction.OUT))
    assert out.total == 0
    # The next due date takes over.
    (view,) = await bill_cases.list_bills(uow, user, now=now)
    assert view.due == date(2026, 10, 25)


async def test_marking_the_same_due_date_twice_logs_once(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow)
    await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 26), due=date(2026, 9, 25))
    with pytest.raises(InvalidInput, match="already marked"):
        await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 26), due=date(2026, 9, 25))
    assert len(await moves_of(uow, user.id)) == 1


async def test_the_external_id_keeps_a_due_date_to_one_move(uow: UowFactory) -> None:
    """The bill:<id>:<due> claim is the second line of defence, for a move the matching
    can't see (here a different amount) that already took the id."""
    user, bill, wallets = await setup(uow)
    ext = f"bill:{bill.id}:2026-09-25"
    for _ in range(2):
        try:
            await log_move(
                uow(), user.id, amount=sgd("500"), to_wallet_id=wallets["IBKR"].id,
                occurred_at=at(9, 25), external_id=ext,
            )  # fmt: skip
        except DuplicateSource:
            break
    else:
        raise AssertionError("the same external id was recorded twice")
    done = await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 25))
    assert done.moved is None and done.already_moved is None
    assert done.message(SG) == (
        "Marked IBKR top-up (25 Sep) as done. That move was already logged, so I didn't log "
        "it again."
    )
    assert len(await moves_of(uow, user.id)) == 1


async def test_a_move_already_logged_in_chat_is_not_logged_again(uow: UowFactory) -> None:
    user, bill, wallets = await setup(uow)
    earlier = await put(uow, user.id, wallets["IBKR"], "1004", at(9, 27))  # within 1%, 2 days on
    done = await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 28))
    assert done.moved is None and done.already_moved is not None
    assert done.already_moved.id == earlier.id
    assert done.message(SG) == (
        "Marked IBKR top-up (25 Sep) as done. The move is already logged: 1004.00 SGD to "
        "IBKR on 27 Sep, so I didn't log it again."
    )
    assert [m.id for m in await moves_of(uow, user.id)] == [earlier.id]


async def test_a_move_that_is_too_far_off_in_amount_date_or_wallet_does_not_match(
    uow: UowFactory,
) -> None:
    user, bill, wallets = await setup(uow)
    await put(uow, user.id, wallets["IBKR"], "1020", at(9, 25))  # 2% off
    await put(uow, user.id, wallets["IBKR"], "1000", at(10, 1))  # 6 days later
    await put(uow, user.id, wallets["Savings"], "1000", at(9, 25))  # another wallet
    done = await bill_cases.mark_paid(uow, user, bill.id, now=at(10, 2))
    assert done.moved is not None
    assert len(await moves_of(uow, user.id)) == 4


async def test_a_deleted_move_does_not_count_as_already_logged(uow: UowFactory) -> None:
    user, bill, wallets = await setup(uow)
    gone = await put(uow, user.id, wallets["IBKR"], "1000", at(9, 25))
    await delete_transaction(uow(), user.id, gone.id)
    done = await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 26))
    assert done.moved is not None


async def test_a_scheduled_move_with_no_amount_is_marked_done_and_logs_nothing(
    uow: UowFactory,
) -> None:
    user, bill, _ = await setup(uow, amount=None)
    done = await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 25))
    assert done.moved is None and done.amount is None
    assert done.message(SG) == (
        "Marked IBKR top-up (25 Sep) as done. It has no set amount, so no move was logged; "
        "tell me how much it was to log it."
    )
    assert await moves_of(uow, user.id) == []


async def test_a_scheduled_move_can_be_marked_with_the_amount_given(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow, amount=None)
    done = await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 25), amount=sgd("750"))
    assert done.moved is not None and done.moved.amount == sgd("750")


async def test_a_not_spending_bill_without_a_wallet_logs_nothing(uow: UowFactory) -> None:
    user = await person(uow)
    plain = await bill_cases.add_bill(
        uow(), user, "Pocket money", date(2026, 9, 25), Cadence.MONTHLY, sgd("400"),
        now=at(9, 1), spending=False,
    )  # fmt: skip
    done = await bill_cases.mark_paid(uow, user, plain.id, now=at(9, 25))
    assert done.moved is None and done.logged is None
    assert done.message(SG) == (
        "Marked Pocket money (25 Sep) as done. It doesn't count as spending, so nothing was logged."
    )
    assert await moves_of(uow, user.id) == []


async def test_only_a_real_due_date_can_be_named(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow)
    with pytest.raises(InvalidInput, match="isn't due on 26 Sep"):
        await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 26), due=date(2026, 9, 26))
    with pytest.raises(InvalidInput, match="isn't due on 26 Sep"):
        await bill_cases.skip(uow, user, bill.id, now=at(9, 26), due=date(2026, 9, 26))


# --- skipping one -------------------------------------------------------------------


async def test_skipping_a_due_date_logs_nothing_and_the_next_takes_over(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user, bill, _ = await setup(uow)
    skipped = await bill_cases.skip(uow, user, bill.id, now=at(9, 27))
    assert skipped.due == date(2026, 9, 25)
    assert await moves_of(uow, user.id) == []
    (view,) = await bill_cases.list_bills(uow, user, now=at(9, 27))
    assert view.due == date(2026, 10, 25)
    with pytest.raises(InvalidInput, match="already marked"):
        await bill_cases.skip(uow, user, bill.id, now=at(9, 27), due=date(2026, 9, 25))
    async with engine.connect() as db:
        (row,) = (await db.execute(select(bill_occurrences))).all()
    assert row.skipped_at is not None and row.paid_at is None


# --- cash flow and the plan ---------------------------------------------------------


async def test_cash_flow_shows_a_scheduled_move_as_its_own_kind_out_of_spending(
    uow: UowFactory,
) -> None:
    user, _, _ = await setup(uow)
    await bill_cases.add_bill(
        uow(), user, "Pocket money", date(2026, 10, 26), Cadence.MONTHLY, sgd("400"),
        now=at(9, 1), spending=False,
    )  # fmt: skip
    now = at(10, 17)
    flow = await cash_flow(uow, FakeRates(), user, date(2026, 10, 1), date(2026, 10, 31), now=now)
    found = {(d.day, e.name): e for d in flow.days for e in d.expected}
    top_up = found[(date(2026, 10, 25), "IBKR top-up → IBKR")]
    assert (top_up.kind, top_up.direction, top_up.home) == (
        ExpectedKind.MOVE,
        Direction.OUT,
        sgd("1000"),
    )
    plain = found[(date(2026, 10, 26), "Pocket money")]
    assert plain.kind is ExpectedKind.BILL  # without a wallet: as before
    assert flow.expected_out == sgd("1400")


async def test_a_skipped_or_done_date_is_no_longer_expected(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow, due=date(2026, 10, 25))
    await bill_cases.skip(uow, user, bill.id, now=at(10, 17))
    flow = await cash_flow(
        uow, FakeRates(), user, date(2026, 10, 17), date(2026, 10, 31), now=at(10, 17)
    )
    assert [e for d in flow.days for e in d.expected] == []


async def test_left_to_spend_and_the_plan_check_count_a_scheduled_move_like_the_same_bill(
    uow: UowFactory,
) -> None:
    """The same 1,000 top-up, with a wallet for one user and without for the other."""
    now = at(10, 17)
    plans = []
    for who, with_wallet in ((4242, True), (4343, False)):
        user = await person(uow, who)
        wallet = await add_wallet(uow(), user.id, "IBKR", WalletKind.INVESTMENT)
        await budget_cases.set_budget(uow(), user, None, sgd("4500"), now=at(10, 1))
        await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=28, now=at(10, 1))
        await salary_cases.set_baseline(uow(), user, sgd("5000"), now=at(10, 1))
        await bill_cases.add_bill(
            uow(), user, "IBKR top-up", date(2026, 10, 25), Cadence.MONTHLY, sgd("1000"),
            now=at(10, 1), spending=False, wallet_id=wallet.id if with_wallet else None,
        )  # fmt: skip
        plans.append(await month_plan(uow, FakeRates(), user, now=now))
    with_wallet_plan, plain_plan = plans
    assert with_wallet_plan.still_due_out == plain_plan.still_due_out == sgd("1000")
    assert with_wallet_plan.left_to_spend == plain_plan.left_to_spend
    assert with_wallet_plan.plan_warning is not None
    assert with_wallet_plan.plan_warning == plain_plan.plan_warning


async def test_a_scheduled_move_without_an_amount_is_named_once_in_the_skipped_list(
    uow: UowFactory,
) -> None:
    user, _, _ = await setup(uow, amount=None, due=date(2026, 10, 25))
    await budget_cases.set_budget(uow(), user, None, sgd("4500"), now=at(10, 1))
    plan = await month_plan(uow, FakeRates(), user, now=at(10, 17))
    assert plan.skipped == ["IBKR top-up → IBKR"]


# --- the missed-move nudge -----------------------------------------------------------


async def test_the_nudge_appears_three_days_after_the_due_date_with_two_actions(
    uow: UowFactory,
) -> None:
    user, bill, _ = await setup(uow)
    assert await nudges(uow, user, at(9, 27)) == []  # two days on: too soon
    feed = await needs_you(uow, FakeRates(), user, now=at(9, 28))
    # Three days on: asked once, with buttons, not also as an overdue bill.
    assert [(i.kind, i.urgent) for i in feed] == [("missed_move", False)]
    (item,) = feed
    assert item.text == (
        "Your SGD 1,000.00 IBKR top-up on 25 Sep hasn't shown up. Did it go through?"
    )
    assert (item.department, item.link) == ("accounting", "/accounting/budgets")
    assert [(a.key, a.label, a.method, a.path) for a in item.actions] == [
        ("went_through", "It went through", "POST", f"/bills/{bill.id}/paid?due=2026-09-25"),
        ("skip", "Skip this month", "POST", f"/bills/{bill.id}/skip?due=2026-09-25"),
    ]
    assert (await bill_cases.missed_moves(uow, user, now=at(9, 28)))[0].due == date(2026, 9, 25)


async def test_it_asks_about_each_missed_date_within_35_days_and_no_older(uow: UowFactory) -> None:
    user, _, _ = await setup(uow, cadence=Cadence.ONCE, due=date(2026, 9, 1), created=at(8, 28))
    assert len(await nudges(uow, user, at(10, 6))) == 1  # 35 days on
    assert await nudges(uow, user, at(10, 7)) == []  # 36: let go

    other, _, _ = await setup(uow, who=4343)  # monthly: 25 Sep and then 25 Oct
    dues = [m.due for m in await bill_cases.missed_moves(uow, other, now=at(10, 30))]
    assert dues == [date(2026, 9, 25), date(2026, 10, 25)]


async def test_nothing_is_asked_about_before_the_bill_existed(uow: UowFactory) -> None:
    user, _, _ = await setup(uow, created=at(9, 27))  # added after the 25th
    assert await nudges(uow, user, at(9, 30)) == []


async def test_a_matching_move_stops_the_nudge_and_marks_nothing(uow: UowFactory) -> None:
    user, _bill, wallets = await setup(uow)
    now = at(10, 3)
    assert len(await nudges(uow, user, now)) == 1
    await put(uow, user.id, wallets["IBKR"], "1008", at(9, 29))  # 4 days after, within 1%
    assert await nudges(uow, user, now) == []
    # Nothing was marked: the occurrence is still open.
    assert (await bill_cases.list_bills(uow, user, now=at(9, 29)))[0].due == date(2026, 9, 25)
    assert len(await moves_of(uow, user.id)) == 1


@pytest.mark.parametrize(
    ("amount", "wallet", "when"),
    [
        ("1020", "IBKR", at(9, 26)),  # 2% off
        ("1000", "IBKR", at(10, 1)),  # six days after
        ("1000", "IBKR", at(9, 19)),  # six days before
        ("1000", "Savings", at(9, 26)),  # the wrong wallet
    ],
)
async def test_a_move_that_does_not_match_leaves_the_nudge(
    uow: UowFactory, amount: str, wallet: str, when: datetime
) -> None:
    user, _, wallets = await setup(uow)
    await put(uow, user.id, wallets[wallet], amount, when)
    assert len(await nudges(uow, user, at(10, 3))) == 1


async def test_a_deleted_move_does_not_stop_the_nudge(uow: UowFactory) -> None:
    user, _, wallets = await setup(uow)
    gone = await put(uow, user.id, wallets["IBKR"], "1000", at(9, 25))
    assert await nudges(uow, user, at(10, 3)) == []
    await delete_transaction(uow(), user.id, gone.id)
    assert len(await nudges(uow, user, at(10, 3))) == 1


async def test_a_move_from_another_wallet_into_the_wallet_still_counts(uow: UowFactory) -> None:
    user, _, wallets = await setup(uow)
    await log_move(
        uow(), user.id, amount=sgd("1000"), to_wallet_id=wallets["IBKR"].id,
        from_wallet_id=wallets["Savings"].id, occurred_at=at(9, 25),
    )  # fmt: skip
    assert await nudges(uow, user, at(10, 3)) == []


async def test_done_or_skipped_dates_are_not_asked_about(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow, cadence=Cadence.MONTHLY, due=date(2026, 8, 25))
    # 25 Aug is too old, 25 Sep and 25 Oct are the ones in play on 30 Oct.
    now = at(10, 30)
    assert [m.due for m in await bill_cases.missed_moves(uow, user, now=now)] == [
        date(2026, 9, 25),
        date(2026, 10, 25),
    ]
    await bill_cases.skip(uow, user, bill.id, now=now, due=date(2026, 9, 25))
    await bill_cases.mark_paid(uow, user, bill.id, now=now, due=date(2026, 10, 25))
    assert await bill_cases.missed_moves(uow, user, now=now) == []


async def test_it_went_through_logs_the_move_and_clears_the_nudge(uow: UowFactory) -> None:
    user, bill, wallets = await setup(uow)
    now = at(10, 3)
    (item,) = await nudges(uow, user, now)
    assert item.actions[0].key == "went_through"
    done = await bill_cases.mark_paid(uow, user, bill.id, now=now, due=date(2026, 9, 25))
    assert done.moved is not None
    (move,) = await moves_of(uow, user.id)
    assert move.to_wallet_id == wallets["IBKR"].id and move.amount == sgd("1000")
    # Confirmed in October, it belongs to September: dated on its due date.
    assert move.occurred_at == at(9, 25)
    assert await nudges(uow, user, now) == []


async def test_skip_this_month_clears_the_nudge_without_logging(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow)
    now = at(10, 3)
    assert len(await nudges(uow, user, now)) == 1
    await bill_cases.skip(uow, user, bill.id, now=now, due=date(2026, 9, 25))
    assert await nudges(uow, user, now) == []
    assert await moves_of(uow, user.id) == []


async def test_only_scheduled_moves_with_an_amount_are_asked_about(uow: UowFactory) -> None:
    user = await person(uow)
    for name, spending in (("Rent", True), ("Pocket money", False)):
        await bill_cases.add_bill(
            uow(), user, name, date(2026, 9, 25), Cadence.MONTHLY, sgd("500"),
            now=at(9, 1), spending=spending,
        )  # fmt: skip
    await add_wallet(uow(), user.id, "IBKR", WalletKind.INVESTMENT)
    ibkr = (await wallets_of(uow, user.id))["IBKR"]
    await bill_cases.add_bill(
        uow(), user, "Top-up", date(2026, 9, 25), Cadence.MONTHLY, None,
        now=at(9, 1), spending=False, wallet_id=ibkr.id,
    )  # fmt: skip
    assert await bill_cases.missed_moves(uow, user, now=at(10, 3)) == []


async def test_a_snoozed_nudge_waits_a_day(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow)
    now = at(9, 30)
    await bill_cases.snooze(uow, user, bill.id, now=now)  # the overdue 25 Sep, held a day
    assert await nudges(uow, user, now) == []
    assert len(await nudges(uow, user, now + timedelta(days=1, minutes=1))) == 1


async def test_another_users_moves_do_not_stop_my_nudge(uow: UowFactory) -> None:
    user, _, _ = await setup(uow)
    other, _, other_wallets = await setup(uow, who=4343)
    await put(uow, other.id, other_wallets["IBKR"], "1000", at(9, 25))
    assert len(await nudges(uow, user, at(10, 3))) == 1
    assert await nudges(uow, other, at(10, 3)) == []


# --- deleting a wallet ----------------------------------------------------------------


async def test_deleting_a_wallet_points_its_scheduled_moves_at_the_replacement(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user, bill, wallets = await setup(uow)
    with pytest.raises(InvalidInput, match="has moves or scheduled payments"):
        await delete_wallet(uow(), user.id, wallets["IBKR"].id)
    done = await delete_wallet(uow(), user.id, wallets["IBKR"].id, wallets["Savings"].id)
    assert (done.bills, done.moved, done.into) == (1, 0, wallets["Savings"])
    (view,) = await bill_cases.list_bills(uow, user, now=at(9, 20))
    assert view.bill.id == bill.id and view.bill.wallet_id == wallets["Savings"].id
    assert "IBKR" not in await wallets_of(uow, user.id)


async def test_a_replacement_of_spending_leaves_a_plain_not_spending_bill(
    uow: UowFactory,
) -> None:
    user, _, wallets = await setup(uow)
    await delete_wallet(uow(), user.id, wallets["IBKR"].id, wallets["Spending"].id)
    (view,) = await bill_cases.list_bills(uow, user, now=at(9, 20))
    assert (view.bill.wallet_id, view.bill.spending) == (None, False)


async def test_a_removed_bill_does_not_hold_a_wallet_back(uow: UowFactory) -> None:
    user, bill, wallets = await setup(uow)
    await bill_cases.remove_bill(uow(), user.id, bill.id, now=at(9, 2))
    done = await delete_wallet(uow(), user.id, wallets["IBKR"].id)  # nothing to point anywhere
    assert (done.bills, done.into) == (0, None)
    async with uow() as tx:
        stored = await tx.planning.get_bill(user.id, bill.id)
    assert stored is not None and stored.wallet_id is None


async def test_preview_counts_the_scheduled_moves(uow: UowFactory) -> None:
    from nexus.application.wallets import preview_delete_wallet

    user, _, wallets = await setup(uow)
    plan = await preview_delete_wallet(uow(), user.id, wallets["IBKR"].id, wallets["Savings"].id)
    assert (plan.bills, plan.moved, plan.removed) == (1, 0, 0)
    with pytest.raises(InvalidInput, match="scheduled payments"):
        await preview_delete_wallet(uow(), user.id, wallets["IBKR"].id)
    assert "IBKR" in await wallets_of(uow, user.id)


# --- chat -----------------------------------------------------------------------------


async def run(uow: UowFactory, user: UserId, tool: str, args: dict[str, Any]) -> str:
    now = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
    ctx = ToolContext(await get_user(uow(), user), uow, now)
    return (await run_tool(build_tools(lambda _: "")[tool], ctx, args)).text


async def test_the_chat_tool_adds_a_scheduled_move(uow: UowFactory) -> None:
    user, _, wallets = await setup(uow, who=4545)
    await bill_cases.remove_bill(
        uow(), user.id, (await bill_cases.list_bills(uow, user, now=at(9, 20)))[0].bill.id,
        now=at(9, 2),
    )  # fmt: skip
    said = await run(
        uow,
        user.id,
        "add_bill",
        {
            "name": "Savings top-up",
            "due_date": "2026-10-25",
            "repeats": "monthly",
            "amount": "500",
            "to_wallet": "savings",
            "counts_as_spending": True,  # contradicts the wallet: the wallet wins
        },
    )
    assert said == (
        "Added Savings top-up 500.00 SGD: due in 27 days (Sun 25 Oct), every month on the "
        "25th, moved to Savings (not spending). I'll remind you 7, 3 and 1 days before."
    )
    (view,) = await bill_cases.list_bills(uow, user, now=at(9, 28))
    assert (view.bill.spending, view.bill.wallet_id) == (False, wallets["Savings"].id)
    assert "moved to Savings (not spending)" in await run(uow, user.id, "list_bills", {})


async def test_an_unknown_wallet_creates_nothing_and_tells_the_model_to_ask(
    uow: UowFactory,
) -> None:
    user = await person(uow, 4646)
    said = await run(
        uow,
        user.id,
        "add_bill",
        {"name": "Crypto top-up", "due_date": "2026-10-25", "to_wallet": "Coinbase"},
    )
    assert said.startswith("Error: there's no wallet called 'Coinbase'")
    assert "offer to add it as a new wallet" in said
    assert await bill_cases.list_bills(uow, user, now=at(9, 28)) == []
    assert list(await wallets_of(uow, user.id)) == ["Spending"]  # no wallet was made either


async def test_marking_done_in_chat_logs_the_move(uow: UowFactory) -> None:
    user, _, _ = await setup(uow, who=4747)
    said = await run(uow, user.id, "mark_bill_paid", {"name": "IBKR top-up"})
    assert said.startswith(
        "Marked IBKR top-up (25 Sep) as done and logged a move of 1000.00 SGD from "
        "Spending to IBKR."
    )
    assert len(await moves_of(uow, user.id)) == 1


async def test_a_bill_row_cannot_name_another_users_wallet(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    _, bill, _ = await setup(uow)
    other = await person(uow, 4343)
    theirs = (await wallets_of(uow, other.id))["Spending"]
    async with engine.begin() as db:
        with pytest.raises(IntegrityError, match="fk_bills_wallet_id_user_id_wallets"):
            await db.execute(
                bills.update().where(bills.c.id == bill.id).values(wallet_id=theirs.id)
            )


async def test_amount_is_decimal_exact(uow: UowFactory) -> None:
    user, bill, _ = await setup(uow, amount="1234.56")
    done = await bill_cases.mark_paid(uow, user, bill.id, now=at(9, 25))
    assert done.moved is not None and done.moved.amount.amount == Decimal("1234.56")


async def test_remind_me_to_put_money_into_a_wallet_reaches_the_model_and_adds_the_move(
    uow: UowFactory, alice: UserId
) -> None:
    from tests.fakes import say, scripted
    from tests.integration.test_agent import build, only, tool_results
    from tests.integration.test_agent_wallets import tool_call

    await add_wallet(uow(), alice, "IBKR", WalletKind.INVESTMENT)
    model = scripted(
        tool_call(
            "add_bill",
            {
                "name": "IBKR top-up",
                "due_date": "2026-10-25",
                "repeats": "monthly",
                "amount": "1000",
                "to_wallet": "IBKR",
            },
        ),
        say("Done: I'll remind you every 25th."),
    )
    agent = build(uow, model)
    text = "remind me to put 1000 into IBKR every 25th"
    reply = only(await agent.handle_text(alice, text, "tg:1:1"))
    assert reply.text == "Done: I'll remind you every 25th."  # the kernel let it through
    assert tool_results(model)[0].startswith("Added IBKR top-up 1000.00 SGD: due in 27 days")
    user = await get_user(uow(), alice)
    (view,) = await bill_cases.list_bills(uow, user, now=datetime(2026, 9, 28, 4, tzinfo=UTC))
    assert view.bill.wallet_id is not None and not view.bill.spending


async def test_the_migration_round_trips_and_keeps_the_bills(
    engine: AsyncEngine, uow: UowFactory, empty_database_url: str
) -> None:
    import asyncio

    from alembic import command

    from nexus.infra.db.migrations import alembic_config
    from tests.integration.conftest import upgrade

    user, bill, _ = await setup(uow)
    await bill_cases.skip(uow, user, bill.id, now=at(9, 27))
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0042")
    await upgrade(empty_database_url)
    async with engine.connect() as db:
        rows = (await db.execute(select(bills.c.name, bills.c.wallet_id))).all()
    # The pointer went with the column.
    assert [(r.name, r.wallet_id) for r in rows] == [("IBKR top-up", None)]
