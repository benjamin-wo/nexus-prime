"""What the user saved, month by month, against the database: the evals' ledger (August and
September in full, nothing in October, twelve days of November), agreement with Home and
``month_outlook`` for every month, moves to savings, other starts of a ledger, a foreign
currency, and the chat tool that carries the figures to the model. Made-up data only."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from nexus.agent.graph import CORE_TOOLS
from nexus.agent.tools import READ_ONLY
from nexus.application import wallets as wallet_cases
from nexus.application.money_history import money_history
from nexus.application.month_outlook import month_outlook
from nexus.application.wallet_figures import month_figures
from nexus.domain.ledger import Direction, User
from nexus.domain.money import Money
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


async def november(uow: UowFactory, telegram_id: int = 7100) -> User:
    return (await seed.seed_user(uow, telegram_id, november=True)).user


def at(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 12, tzinfo=seed.TZ)


async def test_the_evals_ledger_gives_the_figures_the_cases_grade(uow: UowFactory) -> None:
    user = await november(uow)
    h = await money_history(uow, RATES, user, now=NOV)
    assert h.currency == "SGD" and h.today == date(2026, 11, 13)
    # August is the first month with entries: nothing before it is listed.
    assert [m.month for m in h.months] == [date(2026, m, 1) for m in (8, 9, 10, 11)]
    assert h.first_day is not None and h.first_day.month == 8
    august, september, october, current = h.months
    assert august.net == sgd(seed.AUG_NET) and august.partial is False
    assert september.net == sgd(seed.SEP_NET)
    assert (september.received, september.spent) == (sgd("5000.00"), sgd(seed.SEPT_SPENT))
    assert not october.logged and october.net == sgd("0")  # a gap in the ledger
    assert current.partial and current.net == sgd(seed.NOV_NET_SO_FAR)
    assert (current.received, current.spent) == (sgd(seed.NOV_RECEIVED), sgd(seed.NOV_SPENT))

    # The empty October and the part-month are left out of the averages.
    s, g = h.summary, h.guide
    assert s is not None and g is not None
    assert s.months == 2
    assert s.average_net.amount in (Decimal(a) for a in seed.SAVE_AVERAGE)
    assert s.average_net == sgd("4646.60")
    assert (s.best.month, s.worst.month) == (date(2026, 8, 1), date(2026, 9, 1))
    assert g.usual_salary == sgd(seed.NOV_PAYDAY)
    assert g.benchmark == sgd("959.60")
    assert g.average_spent == s.average_spent


async def test_every_month_matches_home_and_the_month_outlook(uow: UowFactory) -> None:
    user = await november(uow, 7101)
    h = await money_history(uow, RATES, user, now=NOV)
    for m in h.months:
        outlook = await month_outlook(uow, RATES, user, now=NOV, month=f"{m.month:%Y-%m}")
        figures = await month_figures(
            uow, RATES, user, now=datetime(m.month.year, m.month.month, 15, tzinfo=seed.TZ)
        )
        assert (m.received, m.spent, m.net, m.moved) == (
            outlook.received,
            outlook.spent,
            outlook.net_so_far,
            outlook.moved,
        ), m.month
        assert (m.received, m.spent) == (figures.income, figures.spent), m.month


async def test_money_moved_to_savings_is_shown_and_is_part_of_the_net(uow: UowFactory) -> None:
    user = await november(uow, 7102)
    wallets = {w.name: w for w in await wallet_cases.list_wallets(uow(), user.id)}
    main = next(w for w in wallets.values() if w.kind.value == "spending")
    await wallet_cases.log_move(
        uow(),
        user.id,
        amount=Money.of("1000", "SGD"),
        from_wallet_id=main.id,
        to_wallet_id=wallets["Savings"].id,
        occurred_at=at(9, 26),
    )
    h = await money_history(uow, RATES, user, now=NOV)
    september = next(m for m in h.months if m.month == date(2026, 9, 1))
    assert september.moved == sgd("1000")
    assert september.spent == sgd(seed.SEPT_SPENT)  # a move is never spending
    assert september.net == sgd(seed.SEP_NET)  # and the net is the same


async def test_months_before_the_first_entry_are_not_listed(uow: UowFactory) -> None:
    user = await person(uow, 7103)
    await log(uow, user, "1000", at(10, 2), direction=Direction.IN)
    await log(uow, user, "400", at(10, 9))
    await log(uow, user, "50", at(11, 3))
    h = await money_history(uow, RATES, user, now=NOV)
    assert [m.month for m in h.months] == [date(2026, 10, 1), date(2026, 11, 1)]
    assert h.summary is not None and h.summary.months == 1
    october = h.months[0]
    assert october.net == sgd("600") and october.savings_rate == Decimal("0.6")
    # The month to date, with no income yet: no saving rate.
    assert h.months[1].partial and h.months[1].savings_rate is None


async def test_a_user_with_nothing_logged_has_no_history(uow: UowFactory) -> None:
    user = await person(uow, 7104)
    h = await money_history(uow, RATES, user, now=NOV)
    assert h.months == [] and h.first_day is None and h.summary is None and h.guide is None


async def test_the_first_month_alone_is_a_part_month_with_no_summary(uow: UowFactory) -> None:
    user = await person(uow, 7105)
    await log(uow, user, "20", at(11, 2))
    h = await money_history(uow, RATES, user, now=NOV)
    assert [m.month for m in h.months] == [date(2026, 11, 1)] and h.summary is None


async def test_the_number_of_months_is_capped_at_twelve(uow: UowFactory) -> None:
    user = await person(uow, 7106)
    await log(uow, user, "1000", datetime(2025, 1, 5, 12, tzinfo=seed.TZ), direction=Direction.IN)
    default = await money_history(uow, RATES, user, now=NOV)
    assert len(default.months) == 7  # six full months and this one
    assert default.months[0].month == date(2026, 5, 1)
    most = await money_history(uow, RATES, user, now=NOV, months=50)
    assert len(most.months) == 13 and most.months[0].month == date(2025, 11, 1)
    one = await money_history(uow, RATES, user, now=NOV, months=0)
    assert [m.month for m in one.months] == [date(2026, 10, 1), date(2026, 11, 1)]


async def test_a_foreign_amount_with_no_rate_is_named_and_left_out(uow: UowFactory) -> None:
    user = await person(uow, 7107)
    rates = FakeRates({("USD", "SGD"): {date(2026, 10, 1): "1.30"}})
    await log(uow, user, "1000", at(10, 5), direction=Direction.IN)
    await log(uow, user, "10", at(10, 6), currency="USD")
    await log(uow, user, "20", at(10, 7), currency="GBP")  # no rate
    h = await money_history(uow, rates, user, now=NOV)
    october = h.months[0]
    assert october.spent == sgd("13.00") and october.net == sgd("987.00")
    assert october.unconverted == [Money.of("20", "GBP")]


# --- the chat tool ------------------------------------------------------------------------


async def test_the_chat_tool_reports_the_evals_months(uow: UowFactory) -> None:
    user = await november(uow, 7300)
    model = scripted(call("money_history"), say("About +4,646.60 a month."))
    await build(uow, model, clock=lambda: NOV).handle_text(user.id, "how much do i save?", "tg:1:1")
    [text] = tool_results(model)
    for expected in (
        "Savings history as of Fri 13 Nov 2026",
        "- Aug 2026: received",
        "(received less spent), saving rate",
        "- Oct 2026: nothing logged (a gap in the ledger, not counted in the averages)",
        "- Nov 2026 so far",
        "Over the 2 full months with entries (Aug 2026 to Sep 2026): average net +",
        "usual salary 4,798.00",
        "20.0% of it 959.60",
    ):
        assert expected in text, expected


async def test_the_tool_is_offered_every_turn_and_is_read_only(uow: UowFactory) -> None:
    assert "money_history" in CORE_TOOLS and "money_history" in READ_ONLY
    user = await november(uow, 7310)
    model = scripted(say("Hi."))
    await build(uow, model, clock=lambda: NOV).handle_text(user.id, "hello", "tg:1:1")
    assert "money_history" in set(model.bound[0])


async def test_the_months_argument_is_passed_on(uow: UowFactory) -> None:
    user = await november(uow, 7320)
    model = scripted(call("money_history", months=1), say("Done."))
    await build(uow, model, clock=lambda: NOV).handle_text(user.id, "last month?", "tg:1:1")
    [text] = tool_results(model)
    assert "- Oct 2026" in text and "- Sep 2026" not in text
