"""The cash-flow calendar: what was logged each day in the home currency, and
what bills, tracked subscriptions and payday are expected to bring. Never a
balance."""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from nexus.application import bills as bill_cases
from nexus.application import salary as salary_cases
from nexus.application.cashflow import ExpectedKind, cash_flow
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, User
from nexus.domain.money import Money
from nexus.domain.planning import Cadence, PayRule
from nexus.domain.recurring import Subscription, SubscriptionStatus
from tests.fakes import FakeRates
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person
from tests.integration.test_notifications import log

pytestmark = pytest.mark.integration

SG = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 9, 15, 12, tzinfo=SG)
SEPT = (date(2026, 9, 1), date(2026, 9, 30))
RATES = FakeRates({("USD", "SGD"): {date(2026, 9, 1): "1.30"}})


def sg(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=SG)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def track(uow: UowFactory, user: User, name: str, amount: Money, last: date) -> None:
    sub = Subscription(
        uuid4(), user.id, name.casefold(), name, Cadence.MONTHLY, amount, last,
        SubscriptionStatus.ACTIVE, NOW, NOW,
    )  # fmt: skip
    async with uow() as tx:
        await tx.planning.insert_subscription(sub)
        await tx.commit()


async def test_days_so_far_show_what_was_logged_in_the_home_currency(uow: UowFactory) -> None:
    user = await person(uow)
    await log(uow, user, "12.40", sg(3))
    await log(uow, user, "10", sg(3), currency="USD")  # 13.00 SGD at the day's rate
    await log(uow, user, "5000", sg(5), direction=Direction.IN)
    await log(uow, user, "99", sg(20))  # dated after today: not shown as logged yet
    flow = await cash_flow(uow, RATES, user, *SEPT, now=NOW)
    by_day = {d.day: d for d in flow.days}
    assert len(flow.days) == 30 and flow.today == date(2026, 9, 15)
    assert (by_day[date(2026, 9, 3)].money_out, by_day[date(2026, 9, 3)].net) == (
        sgd("25.40"),
        sgd("-25.40"),
    )
    assert by_day[date(2026, 9, 5)].net == sgd("5000")
    assert by_day[date(2026, 9, 20)].money_out == sgd("0")
    assert (flow.logged_in, flow.logged_out) == (sgd("5000"), sgd("25.40"))


async def test_days_ahead_show_bills_subscriptions_and_payday(uow: UowFactory) -> None:
    user = await person(uow)
    rent = await bill_cases.add_bill(
        uow(), user, "Rent", date(2026, 9, 1), Cadence.MONTHLY, sgd("1800"), now=NOW
    )
    await bill_cases.add_bill(
        uow(), user, "Electricity", date(2026, 9, 20), Cadence.MONTHLY, None, now=NOW
    )
    await bill_cases.add_bill(
        uow(), user, "Insurance", date(2026, 9, 18), Cadence.YEARLY, Money.of("100", "USD"),
        now=NOW,
    )  # fmt: skip
    await track(uow, user, "Netflix", sgd("17.98"), date(2026, 8, 22))
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=25, now=NOW)
    await salary_cases.set_baseline(uow(), user, sgd("5000"), now=NOW)
    flow = await cash_flow(uow, RATES, user, *SEPT, now=NOW)

    expected = {(d.day, e.name): e for d in flow.days for e in d.expected}
    assert (date(2026, 9, 1), "Rent") not in expected  # before today: not expected any more
    netflix = expected[(date(2026, 9, 22), "Netflix")]
    assert (netflix.kind, netflix.home) == (ExpectedKind.SUBSCRIPTION, sgd("17.98"))
    electricity = expected[(date(2026, 9, 20), "Electricity")]
    assert electricity.amount is None and electricity.home is None
    insurance = expected[(date(2026, 9, 18), "Insurance")]
    assert insurance.home == sgd("130.00")  # converted at today's rate
    pay = expected[(date(2026, 9, 25), "Salary")]
    assert (pay.direction, pay.home) == (Direction.IN, sgd("5000"))
    assert (flow.expected_in, flow.expected_out) == (sgd("5000"), sgd("147.98"))
    assert flow.unknown_amounts == 1
    by_day = {d.day: d for d in flow.days}
    assert by_day[date(2026, 9, 25)].expected_net == sgd("5000")

    # Next month's rent, once marked paid, isn't expected any more.
    october = (date(2026, 10, 1), date(2026, 10, 31))
    ahead = await cash_flow(uow, RATES, user, *october, now=NOW)
    assert any(e.name == "Rent" for d in ahead.days for e in d.expected)
    await bill_cases.mark_paid(uow, user, rent.id, now=datetime(2026, 9, 29, tzinfo=SG))
    later = datetime(2026, 9, 29, 12, tzinfo=SG)
    paid = await cash_flow(uow, RATES, user, *october, now=later)
    assert not any(
        e.name == "Rent" and d.day == date(2026, 10, 1) for d in paid.days for e in d.expected
    )


async def test_only_tracked_subscriptions_and_only_this_users_things(uow: UowFactory) -> None:
    ann, ben = await person(uow, 1), await person(uow, 2)
    await track(uow, ben, "Spotify", sgd("10.98"), date(2026, 8, 20))
    async with uow() as tx:
        await tx.planning.insert_subscription(
            Subscription(
                uuid4(),
                ann.id,
                "gym",
                "Gym",
                Cadence.MONTHLY,
                sgd("80"),
                date(2026, 8, 20),
                SubscriptionStatus.PROPOSED,
                NOW,
                NOW,
            )
        )
        await tx.commit()
    await log(uow, ben, "50", sg(2))
    flow = await cash_flow(uow, RATES, ann, *SEPT, now=NOW)
    assert all(not d.expected for d in flow.days)  # a proposal isn't tracked yet
    assert flow.logged_out == sgd("0")


async def test_unconverted_amounts_are_named_and_ranges_are_checked(uow: UowFactory) -> None:
    user = await person(uow)
    await log(uow, user, "5000", sg(3), currency="JPY")  # no rate published
    flow = await cash_flow(uow, RATES, user, *SEPT, now=NOW)
    assert [(m.amount, m.currency) for m in flow.unconverted] == [(Decimal("5000.0000"), "JPY")]
    with pytest.raises(InvalidInput):
        await cash_flow(uow, RATES, user, date(2026, 9, 30), date(2026, 9, 1), now=NOW)
    with pytest.raises(InvalidInput):
        await cash_flow(uow, RATES, user, date(2026, 1, 1), date(2026, 12, 31), now=NOW)
