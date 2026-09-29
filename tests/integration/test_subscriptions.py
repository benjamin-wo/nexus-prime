"""Recurring payments: proposed after three regular charges, tracked only when the
user agrees, never proposed again once turned down, and price changes flagged."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import subscriptions as subscription_cases
from nexus.domain.errors import NotFound
from nexus.domain.ledger import Direction, Source
from nexus.domain.money import Money
from nexus.domain.recurring import SubscriptionStatus
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person
from tests.integration.test_notifications import log, sent

pytestmark = pytest.mark.integration

SG = ZoneInfo("Asia/Singapore")


def on(month: int, day: int = 12, hour: int = 9) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=SG)


async def netflix(uow: UowFactory, user: Any, *amounts: str, first_month: int = 7) -> None:
    for n, amount in enumerate(amounts):
        await log(uow, user, amount, on(first_month + n), counterparty=f"NETFLIX.COM {880 + n}")


async def test_three_monthly_charges_are_proposed_once(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await netflix(uow, user, "15.98", "15.98")
    await subscription_cases.check(uow, user, now=on(9, 20))
    assert await sent(engine) == []  # two charges aren't a pattern yet

    await log(uow, user, "15.98", on(9), counterparty="Netflix.com 999")
    await subscription_cases.check(uow, user, now=on(9, 20))
    await subscription_cases.check(uow, user, now=on(9, 21))
    [proposal] = await sent(engine)
    assert proposal["text"].startswith(
        "🔁 Netflix.com has charged you about 15.98 SGD every month, 3 times in a row"
    )
    [[track, no]] = proposal["buttons"]
    assert (track["label"], no["label"]) == ("Track it", "No")
    found = await subscription_cases.overview(uow(), user.id)
    assert [v.subscription.status for v in found.proposed] == [SubscriptionStatus.PROPOSED]
    assert found.tracked == [] and found.monthly_totals == []


async def test_tracking_follows_new_charges_and_flags_a_price_change(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await netflix(uow, user, "15.98", "15.98", "15.98")
    await subscription_cases.check(uow, user, now=on(9, 20))
    [proposed] = (await subscription_cases.overview(uow(), user.id)).proposed
    await subscription_cases.track(uow(), user.id, proposed.subscription.id, now=on(9, 20))

    await log(uow, user, "17.98", on(10), counterparty="NETFLIX.COM 1001")
    await subscription_cases.check(uow, user, now=on(10, 13))
    await subscription_cases.check(uow, user, now=on(10, 14))  # told once
    _, change = await sent(engine)
    assert change["text"] == (
        "💸 NETFLIX.COM went up from 15.98 SGD to 17.98 SGD a month (charged 12 Oct)."
    )
    [view] = (await subscription_cases.overview(uow(), user.id)).tracked
    sub = view.subscription
    assert sub.amount == Money.of("17.98", "SGD")
    assert sub.previous_amount == Money.of("15.98", "SGD")
    assert view.next_charge.isoformat() == "2026-11-12"
    assert subscription_cases.describe(view).endswith("(was 15.98 SGD until 12 Oct)")

    # A charge at the same price moves the date on without a message.
    await log(uow, user, "17.98", on(11), counterparty="NETFLIX.COM 1002")
    await subscription_cases.check(uow, user, now=on(11, 13))
    assert len(await sent(engine)) == 2


async def test_no_means_never_asked_again(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    await netflix(uow, user, "15.98", "15.98", "15.98")
    await subscription_cases.check(uow, user, now=on(9, 20))
    [proposed] = (await subscription_cases.overview(uow(), user.id)).proposed
    await subscription_cases.dismiss(uow(), user.id, proposed.subscription.id, now=on(9, 20))
    await log(uow, user, "15.98", on(10), counterparty="NETFLIX.COM 1001")
    await subscription_cases.check(uow, user, now=on(10, 13))
    assert len(await sent(engine)) == 1
    found = await subscription_cases.overview(uow(), user.id)
    assert found.proposed == [] and found.tracked == []


async def test_income_and_other_users_charges_dont_count(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    ann, ben = await person(uow, 1), await person(uow, 2)
    for month in (7, 8, 9):
        await log(uow, ann, "5000", on(month), direction=Direction.IN, counterparty="Employer")
        await log(uow, ben, "15.98", on(month), counterparty="Netflix", source=Source.TEXT)
    await subscription_cases.check(uow, ann, now=on(9, 20))
    assert await sent(engine) == []  # regular income isn't a subscription
    await subscription_cases.check(uow, ben, now=on(9, 20))
    [proposal] = (await subscription_cases.overview(uow(), ben.id)).proposed
    assert (await subscription_cases.overview(uow(), ann.id)).proposed == []
    with pytest.raises(NotFound):
        await subscription_cases.track(uow(), ann.id, proposal.subscription.id, now=on(9, 20))
