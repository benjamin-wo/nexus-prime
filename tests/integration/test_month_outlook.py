"""Where a month ends up, against the database: the user's own scenario (13 November, payday
on the 25th still ahead, a carry-over from October), agreement with Home's "left to spend",
other months, foreign currencies, wallets, timezones, and the chat tools and the snapshot that
carry the figures to the model. Made-up data only."""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import ToolMessage

from nexus.agent import snapshot as snapshot_module
from nexus.agent.snapshot import money_snapshot
from nexus.agent.tools import ToolContext
from nexus.application import bills as bill_cases
from nexus.application import salary as salary_cases
from nexus.application import wallets as wallet_cases
from nexus.application.cashflow import ExpectedKind
from nexus.application.month_outlook import month_outlook
from nexus.application.users import RegisterUser, register_user
from nexus.application.wallet_figures import month_plan
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, User
from nexus.domain.money import Money
from nexus.domain.planning import Cadence, PayRule
from nexus.evals import seed
from nexus.evals.runner import FixedRates
from tests.fakes import FakeRates, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, tool_results
from tests.integration.test_email import person
from tests.integration.test_notifications import log

pytestmark = pytest.mark.integration

RATES = FixedRates()
NOV = seed.NOV_NOW  # Friday 13 November 2026, 2pm in Singapore


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def november(uow: UowFactory, telegram_id: int = 6100) -> User:
    return (await seed.seed_user(uow, telegram_id, november=True)).user


async def test_the_users_scenario_is_the_seeds_figures(uow: UowFactory) -> None:
    user = await november(uow)
    o = await month_outlook(uow, RATES, user, now=NOV)
    assert o.status == "current" and o.month == date(2026, 11, 1) and o.today == date(2026, 11, 13)
    assert (o.received, o.spent, o.net_so_far) == (
        sgd(seed.NOV_RECEIVED),
        sgd(seed.NOV_SPENT),
        sgd(seed.NOV_NET_SO_FAR),
    )
    assert (o.expected_in, o.expected_out) == (
        sgd(seed.NOV_EXPECTED_IN),
        sgd(seed.NOV_EXPECTED_OUT),
    )
    assert o.projected_net == sgd(seed.NOV_PROJECTED) and o.headroom == sgd(seed.NOV_PROJECTED)
    assert o.no_amount == ["Electricity"]
    by_name = {i.name: i for i in o.items}
    assert {n: (i.day, i.kind) for n, i in by_name.items()} == {
        "Electricity": (date(2026, 11, 20), ExpectedKind.BILL),
        "Salary": (date(2026, 11, 25), ExpectedKind.SALARY),
        "Singtel": (date(2026, 11, 28), ExpectedKind.BILL),
        "Gym": (date(2026, 11, 30), ExpectedKind.BILL),
    }
    assert by_name["Salary"].amount == sgd("4798") and by_name["Electricity"].amount is None
    # Rent (1 Nov) and Netflix (12 Nov) are past, so they are not expected again.
    assert "Rent" not in by_name and "Netflix" not in by_name


async def test_with_no_amounts_given_it_is_homes_left_to_spend(uow: UowFactory) -> None:
    user = await november(uow)
    o = await month_outlook(uow, RATES, user, now=NOV)
    plan = await month_plan(uow, RATES, user, now=NOV)
    assert o.projected_net == plan.left_to_spend
    assert plan.skipped == o.no_amount == ["Electricity"]


async def test_the_carry_over_and_the_correction(uow: UowFactory) -> None:
    """ "+2308.42 (net from oct) how much leeway do i have to have positive net overall?",
    then "you forgot the 4000+ coming in at the end of the month": payday (4,798) is already
    counted, so the carry-over is the only amount to add."""
    user = await november(uow)
    o = await month_outlook(
        uow, RATES, user, now=NOV, adjustments=[("+2308.42", "net from October")]
    )
    assert o.overall == sgd(seed.NOV_OVERALL) == sgd("5300.64")
    assert o.headroom == sgd("5300.64") and o.shortfall == sgd("0")


async def test_a_purchase_the_user_is_weighing_comes_off_as_a_negative(uow: UowFactory) -> None:
    user = await november(uow)
    o = await month_outlook(uow, RATES, user, now=NOV, adjustments=[("-500", "dinner")])
    assert o.overall == sgd(seed.NOV_AFTER_DINNER)
    big = await month_outlook(uow, RATES, user, now=NOV, adjustments=[("-3,500", "a holiday")])
    assert big.overall == sgd("-507.78") and big.shortfall == sgd("507.78")
    assert big.headroom == sgd("0")


async def test_too_many_or_bad_adjustments_are_refused(uow: UowFactory) -> None:
    user = await november(uow)
    with pytest.raises(InvalidInput):
        await month_outlook(uow, RATES, user, now=NOV, adjustments=[("a lot", "x")])
    with pytest.raises(InvalidInput):
        await month_outlook(uow, RATES, user, now=NOV, adjustments=[("1", "x")] * 21)


async def test_a_month_that_is_over_has_actuals_only(uow: UowFactory) -> None:
    user = await november(uow)
    august = await month_outlook(uow, RATES, user, now=NOV, month="2026-08")
    assert august.status == "past" and august.items == []
    assert august.net_so_far == sgd(seed.AUG_NET)
    september = await month_outlook(uow, RATES, user, now=NOV, month="2026-09")
    assert (september.received, september.spent) == (sgd("5000"), sgd(seed.SEPT_SPENT))
    assert september.net_so_far == sgd("4539.97") and september.expected_in == sgd("0")


async def test_a_month_ahead_shows_what_is_scheduled_in_it(uow: UowFactory) -> None:
    user = await november(uow)
    december = await month_outlook(uow, RATES, user, now=NOV, month="2026-12")
    assert december.status == "future" and december.received == sgd("0")
    names = {(i.day.day, i.name) for i in december.items}
    assert (25, "Salary") in names and (1, "Rent") in names and (28, "Singtel") in names
    assert december.expected_in == sgd("4798")
    with pytest.raises(InvalidInput):
        await month_outlook(uow, RATES, user, now=NOV, month="2031-01")


async def test_today_counts_as_still_due_but_not_as_payday_to_come(uow: UowFactory) -> None:
    """On payday itself the salary is not expected again (it may be logged already); a bill
    due today is still ahead: the same rules as Home's left to spend."""
    user = await november(uow)
    on_payday = datetime(2026, 11, 25, 14, tzinfo=seed.TZ)
    o = await month_outlook(uow, RATES, user, now=on_payday)
    assert "Salary" not in {i.name for i in o.items}
    assert (await month_plan(uow, RATES, user, now=on_payday)).left_to_spend == o.projected_net
    on_bill_day = datetime(2026, 11, 28, 14, tzinfo=seed.TZ)
    assert "Singtel" in {
        i.name for i in (await month_outlook(uow, RATES, user, now=on_bill_day)).items
    }


async def test_a_foreign_bill_and_a_foreign_expense_are_converted_at_a_rate(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    now = datetime(2026, 11, 13, 12, tzinfo=seed.TZ)
    rates = FakeRates({("USD", "SGD"): {date(2026, 11, 1): "1.30"}})
    await log(uow, user, "10", datetime(2026, 11, 3, 12, tzinfo=seed.TZ), currency="USD")
    await log(uow, user, "1000", datetime(2026, 11, 5, 12, tzinfo=seed.TZ), direction=Direction.IN)
    await bill_cases.add_bill(
        uow(), user, "Insurance", date(2026, 11, 18), Cadence.YEARLY, Money.of("100", "USD"),
        now=now,
    )  # fmt: skip
    await bill_cases.add_bill(
        uow(), user, "Pound bill", date(2026, 11, 19), Cadence.MONTHLY, Money.of("50", "GBP"),
        now=now,
    )  # fmt: skip
    o = await month_outlook(uow, rates, user, now=now)
    assert o.spent == sgd("13.00") and o.received == sgd("1000")
    insurance = next(i for i in o.items if i.name == "Insurance")
    assert insurance.amount == sgd("130.00") and insurance.original == Money.of("100", "USD")
    # No GBP rate: listed, named, left out of the totals.
    assert next(i for i in o.items if i.name == "Pound bill").amount is None
    assert o.no_amount == ["Pound bill"] and o.expected_out == sgd("130")
    assert o.projected_net == sgd("857.00")


async def test_money_moved_to_own_wallets_comes_off_the_projection_not_the_spending(
    uow: UowFactory,
) -> None:
    user = await november(uow)
    wallets = {w.name: w for w in await wallet_cases.list_wallets(uow(), user.id)}
    main = next(w for w in wallets.values() if w.kind.value == "spending")
    await wallet_cases.log_move(
        uow(),
        user.id,
        amount=Money.of("1000", "SGD"),
        from_wallet_id=main.id,
        to_wallet_id=wallets["Savings"].id,
        occurred_at=datetime(2026, 11, 4, 12, tzinfo=seed.TZ),
    )
    o = await month_outlook(uow, RATES, user, now=NOV)
    assert o.spent == sgd(seed.NOV_SPENT)  # a move is never spending
    assert o.net_so_far == sgd(seed.NOV_NET_SO_FAR) and o.moved == sgd("1000")
    assert o.projected_net == sgd("1992.22") and o.projected_net_before_moves == sgd("2992.22")
    assert o.projected_net == (await month_plan(uow, RATES, user, now=NOV)).left_to_spend


async def test_the_month_and_today_are_the_users_own(uow: UowFactory) -> None:
    """At 11pm UTC on 31 October it is already 1 November in Auckland."""
    reg = await register_user(
        uow(),
        RegisterUser(
            telegram_user_id=6200,
            telegram_chat_id=6200,
            home_currency="SGD",
            timezone="Pacific/Auckland",
        ),
    )
    user = reg.user
    nz = ZoneInfo(user.timezone)
    await log(uow, user, "42", datetime(2026, 11, 1, 0, 30, tzinfo=nz))  # 1 Nov local
    await log(uow, user, "7", datetime(2026, 10, 31, 23, 30, tzinfo=nz))  # 31 Oct local
    now = datetime(2026, 10, 31, 23, 0, tzinfo=UTC)  # 12:00 on 1 Nov in Auckland
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=30, now=now)
    await salary_cases.set_baseline(uow(), user, sgd("1000"), now=now)
    o = await month_outlook(uow, RATES, user, now=now)
    assert o.month == date(2026, 11, 1) and o.today == date(2026, 11, 1)
    assert o.spent == sgd("42")  # not October's 7
    assert [(i.day, i.name) for i in o.items] == [(date(2026, 11, 30), "Salary")]


# --- the chat tools --------------------------------------------------------------------------


async def test_the_chat_tool_reports_the_users_scenario(uow: UowFactory) -> None:
    user = await november(uow, 6300)
    model = scripted(
        call(
            "month_outlook",
            adjustments=[{"amount": "+2308.42", "label": "net from October"}],
        ),
        say("About +5,300.64 overall."),
    )
    await build(uow, model, clock=lambda: NOV).handle_text(user.id, "leeway?", "tg:1:1")
    [text] = tool_results(model)
    for expected in (
        "Outlook for November 2026, as of Fri 13 Nov",
        "- Net so far: -1,672.78 (received less spent)",
        "- Wed 25 Nov Salary (payday) +4,798.00",
        "- Fri 20 Nov Electricity (bill) amount not set, not counted",
        "Expected in 4,798.00, out 133.00.",
        "Projected month-end net: +2,992.22",
        "+2,308.42 (net from October)",
        "Overall with those: +5,300.64",
        "Headroom (the leeway): 5,300.64",
    ):
        assert expected in text, expected


async def test_the_tool_is_offered_every_turn_without_loading_a_skill(uow: UowFactory) -> None:
    from nexus.agent.graph import CORE_TOOLS
    from nexus.agent.tools import READ_ONLY

    assert {"month_outlook", "calculate"} <= set(CORE_TOOLS)
    assert {"month_outlook", "calculate"} <= READ_ONLY  # it only reads: fine on an image turn
    user = await november(uow, 6310)
    model = scripted(say("Hi."))
    await build(uow, model, clock=lambda: NOV).handle_text(user.id, "hello", "tg:1:1")
    assert {"month_outlook", "calculate"} <= {t for t in model.bound[0]}


async def test_a_bad_adjustment_is_an_error_the_model_can_correct(uow: UowFactory) -> None:
    user = await november(uow, 6320)
    model = scripted(
        call("month_outlook", adjustments=[{"amount": "lots", "label": "x"}]),
        say("Sorry, which amount?"),
    )
    await build(uow, model, clock=lambda: NOV).handle_text(user.id, "leeway?", "tg:1:1")
    [text] = tool_results(model)
    assert "can't use" in text


async def test_the_calculate_tool_does_the_sums(uow: UowFactory, alice: object) -> None:
    from nexus.domain.ledger import UserId

    actor: UserId = alice  # type: ignore[assignment]
    model = scripted(
        call("calculate", expression="1,234.50 + 987.25 - 42"),
        call("calculate", expression="186.40 / 3"),
        call("calculate", expression="2 ** 9"),
        call("calculate", expression="5 / 0"),
        say("Done."),
    )
    await build(uow, model).handle_text(actor, "sums", "tg:1:1")
    results = [str(m.content) for m in model.seen[-1] if isinstance(m, ToolMessage)]
    assert results[0] == "1234.50 + 987.25 - 42 = 2,179.75"
    assert "= 62.13" in results[1] and "exactly 62.1333333333" in results[1]
    assert "unexpected" in results[2] or "can't use" in results[2]
    assert "divide by zero" in results[3]


# --- the snapshot ----------------------------------------------------------------------------


async def test_the_snapshot_shows_what_is_expected_by_month_end(uow: UowFactory) -> None:
    user = await november(uow, 6400)
    text = await money_snapshot(ToolContext(user, uow, NOV, RATES))
    [line] = [ln for ln in text.splitlines() if ln.startswith("Expected by month end")]
    assert "in 4,798.00, out 133.00" in line
    assert "payday 25 Nov +4,798.00" in line
    assert "Electricity 20 Nov no amount" in line and "Gym 30 Nov -88.00" in line
    # The seven-day line is still there, and so is the cap.
    assert "Next 7 days: Fri 20 Nov bill Electricity." in text
    assert len(text) <= 2000


async def test_the_snapshot_always_names_payday_even_when_much_else_is_due(
    uow: UowFactory,
) -> None:
    user = await november(uow, 6410)
    for n in range(8):
        await bill_cases.add_bill(
            uow(), user, f"Bill number {n}", date(2026, 11, 14 + n), Cadence.MONTHLY,
            sgd("10"), now=NOV,
        )  # fmt: skip
    text = await money_snapshot(ToolContext(user, uow, NOV, RATES))
    [line] = [ln for ln in text.splitlines() if ln.startswith("Expected by month end")]
    assert line.index("payday 25 Nov +4,798.00") < line.index("Bill number 0")  # payday first
    assert "+" in line.rsplit("(", 1)[1] and " more)" in line  # the rest is counted, not listed


async def test_the_month_end_line_survives_the_character_cap(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await november(uow, 6420)
    monkeypatch.setattr(snapshot_module, "MAX_CHARS", 700)
    text = await money_snapshot(ToolContext(user, uow, NOV, RATES))
    assert len(text) <= 700
    assert "payday 25 Nov +4,798.00" in text  # cut from the end, never this line
    assert text.index("This month so far") < text.index("Expected by month end")


async def test_without_a_pay_schedule_nothing_is_said_about_payday(uow: UowFactory) -> None:
    user = await person(uow, 6430)
    now = datetime(2026, 11, 13, 12, tzinfo=seed.TZ)
    await bill_cases.add_bill(
        uow(), user, "Rent", date(2026, 11, 28), Cadence.MONTHLY, sgd("1800"), now=now
    )
    text = await money_snapshot(ToolContext(user, uow, now, RATES))
    [line] = [ln for ln in text.splitlines() if ln.startswith("Expected by month end")]
    assert line.endswith("in 0.00, out 1,800.00 (Rent 28 Nov -1,800.00).")


async def test_a_month_with_nothing_left_says_so(uow: UowFactory, alice: object) -> None:
    from nexus.application.users import get_user

    user = await get_user(uow(), alice)  # type: ignore[arg-type]
    text = await money_snapshot(ToolContext(user, uow, seed.NOW))
    assert "Expected by month end (30 Sep): nothing, no bills, subscriptions or payday." in text


def test_decimal_is_what_the_figures_are_made_of() -> None:
    assert isinstance(Money.of("1", "SGD").amount, Decimal)
