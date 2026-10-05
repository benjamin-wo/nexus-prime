"""Trips: spending found by dates and currency (or added by hand), the user's own
share in the home currency, money set aside each payday, and who still owes what.
Every name and figure here is made up."""

from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from nexus.application import salary as salary_cases
from nexus.application import trips as trip_cases
from nexus.application.cashflow import ExpectedKind, cash_flow
from nexus.application.categories import list_categories
from nexus.application.splits import split_bill
from nexus.application.transactions import NewTransaction, create_transaction
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, ShareRequest, User
from nexus.domain.money import Money
from nexus.domain.planning import PayRule
from nexus.domain.trips import TripStatus
from tests.fakes import FakeRates
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

SG = ZoneInfo("Asia/Singapore")
MADE = datetime(2026, 11, 2, 9, tzinfo=SG)
RATES = FakeRates({("JPY", "SGD"): {date(2026, 11, 1): "0.0090"}})


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def draft(**changes: object) -> trip_cases.TripDraft:
    base: dict[str, object] = {
        "destination": "Tokyo",
        "start": date(2027, 1, 10),
        "end": date(2027, 1, 19),
        "currency": "JPY",
        "budget": sgd("3000"),
        "companions": ["Ann"],
    }
    base.update(changes)
    return trip_cases.TripDraft(**base)  # type: ignore[arg-type]


async def spend(
    uow: UowFactory,
    user: User,
    amount: str,
    at: datetime,
    *,
    currency: str = "JPY",
    category: str | None = None,
    direction: Direction = Direction.OUT,
) -> UUID:
    category_id = None
    if category:
        cats = await list_categories(uow(), user.id)
        category_id = next(c.id for c in cats if c.name == category)
    async with uow() as tx:
        made = await create_transaction(
            tx.ledger,
            user.id,
            NewTransaction(
                direction, Money.of(amount, currency), at, counterparty="Shop",
                category_id=category_id,
            ),
            now=at,
        )  # fmt: skip
        await tx.commit()
    return made.id


async def test_spending_is_found_by_dates_and_currency_or_by_hand(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(uow(), user, draft(), now=MADE)
    ramen = await spend(
        uow, user, "2000", datetime(2027, 1, 10, 13, tzinfo=SG), category="Dining Out"
    )
    await spend(uow, user, "10000", datetime(2027, 1, 12, 20, tzinfo=SG), category="Shopping")
    # Outside the dates, another currency, and money in: not the trip's.
    await spend(uow, user, "500", datetime(2027, 1, 9, 23, tzinfo=SG))
    await spend(uow, user, "15", datetime(2027, 1, 11, tzinfo=SG), currency="SGD")
    await spend(uow, user, "900", datetime(2027, 1, 11, tzinfo=SG), direction=Direction.IN)
    # Flights paid in SGD months before, added by hand.
    flight = await spend(uow, user, "800", datetime(2026, 11, 5, tzinfo=SG), currency="SGD")
    await trip_cases.add_expense(uow(), user.id, trip.id, flight, now=MADE)

    on_day_3 = datetime(2027, 1, 12, 22, tzinfo=SG)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=on_day_3)
    s = view.spending
    assert view.status is TripStatus.ONGOING and len(view.items) == 3
    # 2,000 + 10,000 yen at 0.009 is 108, plus the 800 flight.
    assert (s.spent, s.before, s.left, s.percent) == (sgd("908"), sgd("800"), sgd("2092"), 30)
    assert (s.today, s.per_day) == (sgd("90"), sgd("36.00"))  # 108 over 3 days
    assert s.per_day_left == sgd("261.50")  # 2,092 over the 8 days still to go
    assert [(c.name, c.spent) for c in s.categories] == [
        ("Other", sgd("800")),  # filed by the default rule
        ("Shopping", sgd("90")),
        ("Dining Out", sgd("18")),
    ]

    # Taken off by hand, it stays off though its date and currency match.
    await trip_cases.remove_expense(uow(), user.id, trip.id, ramen, now=MADE)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=on_day_3)
    assert view.spending.spent == sgd("890")
    lines = trip_cases.describe_view(view)
    assert "Spent so far: 890.00 SGD" in lines[1]


async def test_the_users_own_share_counts_and_companions_settle_up(uow: UowFactory) -> None:
    user = await person(uow)
    trip = await trip_cases.create_trip(uow(), user, draft(), now=MADE)
    hotel = await spend(uow, user, "60000", datetime(2027, 1, 10, 15, tzinfo=SG))
    await split_bill(uow(), user.id, hotel, [ShareRequest("Ann")])
    after = datetime(2027, 1, 25, 12, tzinfo=SG)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=after)
    assert view.status is TripStatus.FINISHED
    assert view.spending.spent == sgd("270")  # half of 540
    assert [(o.name, o.amounts, o.home) for o in view.owed] == [
        ("Ann", [Money.of("30000", "JPY")], sgd("270"))
    ]
    settle = await trip_cases.to_settle(uow, RATES, user, now=after)
    assert [(t.destination, len(o)) for t, o in settle] == [("Tokyo", 1)]


async def test_set_aside_shows_in_the_cash_flow_and_says_if_it_covers_the_budget(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=25, now=MADE)
    await salary_cases.set_baseline(uow(), user, sgd("5000"), now=MADE)
    trip = await trip_cases.create_trip(uow(), user, draft(set_aside=sgd("500")), now=MADE)
    flow = await cash_flow(uow, RATES, user, date(2026, 11, 2), date(2026, 12, 31), now=MADE)
    set_aside = [
        (d.day, e.home) for d in flow.days for e in d.expected if e.kind is ExpectedKind.TRIP
    ]
    assert set_aside == [(date(2026, 11, 25), sgd("500")), (date(2026, 12, 25), sgd("500"))]

    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=MADE)
    a = view.saving
    assert (a.paydays_done, a.paydays_left, a.by_start) == (0, 2, sgd("1000"))
    assert (a.covers_budget, a.suggested, a.fits) == (False, sgd("1500"), True)
    assert view.days_until == 69


async def test_trips_are_checked_found_by_name_and_kept_apart(uow: UowFactory) -> None:
    user = await person(uow)
    other = await person(uow, 5151)
    with pytest.raises(InvalidInput, match="ends before"):
        await trip_cases.create_trip(uow(), user, draft(end=date(2027, 1, 1)), now=MADE)
    with pytest.raises(InvalidInput, match="home currency"):
        await trip_cases.create_trip(uow(), user, draft(budget=Money.of("300000", "JPY")), now=MADE)
    tokyo = await trip_cases.create_trip(uow(), user, draft(destination="Tokyo, Japan"), now=MADE)
    await trip_cases.create_trip(
        uow(), user,
        draft(destination="Bali", start=date(2026, 12, 1), end=date(2026, 12, 5), currency="IDR"),
        now=MADE,
    )  # fmt: skip
    assert (await trip_cases.find_trip(uow(), user, "japan", now=MADE)).id == tokyo.id
    assert (await trip_cases.find_trip(uow(), user, None, now=MADE)).destination == "Bali"
    with pytest.raises(NotFound, match="no trip to Paris"):
        await trip_cases.find_trip(uow(), user, "Paris", now=MADE)
    with pytest.raises(NotFound):
        await trip_cases.get_trip(uow(), other.id, tokyo.id)
    with pytest.raises(NotFound):
        await trip_cases.delete_trip(uow(), other.id, tokyo.id)
    theirs = await spend(uow, other, "100", datetime(2027, 1, 11, tzinfo=SG))
    with pytest.raises(NotFound):
        await trip_cases.add_expense(uow(), user.id, tokyo.id, theirs, now=MADE)

    updated = await trip_cases.update_trip(
        uow(), user, tokyo.id,
        trip_cases.TripDraft("Tokyo, Japan", tokyo.start, tokyo.end, "JPY", None, ["Ann", "ann"]),
        now=MADE,
    )  # fmt: skip
    assert updated.budget is None and updated.companions == ("Ann",)
    await trip_cases.delete_trip(uow(), user.id, tokyo.id)
    assert [t.destination for t in await trip_cases.list_trips(uow(), user.id)] == ["Bali"]
