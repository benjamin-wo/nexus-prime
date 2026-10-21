"""Home's Today page: the richer "Needs you" items (plan prices reached, big moves, earnings,
bookings about to happen, trips to get ready for), their order, and the setup checklist.
Every name, ticker and figure here is made up.

The made-up user lives in Singapore (UTC+8). ``NOW`` is 09:00 on Wednesday 21 October there:
01:00 UTC the same day, but 21:00 on Tuesday 20 October in New York (daylight time, UTC-4), so
the user's local date and the New York trading day differ."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import bills as bill_cases
from nexus.application import budgets as budget_cases
from nexus.application import prep as prep_cases
from nexus.application import research as research_cases
from nexus.application import salary as salary_cases
from nexus.application import setup as setup_cases
from nexus.application import trips as trip_cases
from nexus.application.home import FeedItem, needs_you
from nexus.domain.alerts import MINUS, AlertKind, MarketAlert, move_text, moved_in
from nexus.domain.bookings import Booking, BookingDraft, BookingKind, Segment
from nexus.domain.email import ConnectionStatus
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.domain.news import EarningsDate
from nexus.domain.planning import Cadence, PayRule
from nexus.domain.plans import SavedPlan, Verdict
from nexus.infra.db.migrations import alembic_config
from tests.fakes import FakeMailbox, FakeRates
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import connect, person
from tests.integration.test_quotes import hold
from tests.integration.test_web_api import OWNER, World
from tests.unit.test_plan_follow import saved

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

D = Decimal
SG = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=SG)
NY_TODAY = date(2026, 10, 20)  # the New York trading day at NOW
LOCAL_TODAY = date(2026, 10, 21)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def shown(feed: list[FeedItem], *kinds: str) -> list[tuple[str, str, str, str]]:
    """(kind, text, link, when) of the items of these kinds, in the feed's order."""
    return [(i.kind, i.text, i.link, i.when) for i in feed if i.kind in kinds]


async def feed_of(uow: UowFactory, user: User, now: datetime = NOW) -> list[FeedItem]:
    return await needs_you(uow, FakeRates(), user, now=now)


# --- investment: plan prices, big moves, earnings -------------------------------------------


async def make_plan(uow: UowFactory, user: User, **changes: Any) -> SavedPlan:
    """A plan for NVDA: buy zone 124 to 125, stop 182.40, first target 130, valid to 30 Oct."""
    fields: dict[str, Any] = {
        "user_id": user.id,
        "symbol": "NVDA",
        "as_of": date(2026, 10, 16),
        "valid_until": date(2026, 10, 30),
        "created_at": datetime(2026, 10, 16, 22, tzinfo=UTC),
        "stop": D("182.40"),
    }
    plan = saved(Verdict.WAIT, **{**fields, **changes})
    async with uow() as tx:
        await tx.investments.insert_plan(plan)
        await tx.commit()
    return plan


async def alert(
    uow: UowFactory,
    user: User,
    symbol: str,
    kind: AlertKind,
    *,
    day: date = NY_TODAY,
    urgent: bool = False,
    words: str | None = None,
) -> None:
    at = datetime(2026, 10, 20, 14, 42, tzinfo=UTC)
    async with uow() as tx:
        made = await tx.investments.insert_alert(
            MarketAlert(
                uuid4(), user.id, symbol, kind, day, words or f"{symbol} {kind.value}", urgent, at
            )
        )
        await tx.commit()
    assert made


async def report(uow: UowFactory, symbol: str, day: date) -> None:
    async with uow() as tx:
        await tx.investments.save_news(symbol, [], [EarningsDate(symbol, day, None)], at=NOW)
        await tx.commit()


async def test_a_broken_stop_on_a_held_stock_is_urgent_and_links_its_plan(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    plan = await make_plan(uow, user)
    await hold(uow, user, "NVDA")
    await alert(uow, user, "NVDA", AlertKind.PLAN_STOP, urgent=True)
    feed = await feed_of(uow, user)
    assert shown(feed, "plan_hit") == [
        ("plan_hit", "NVDA reached its stop (182.40)", f"/investment/plans/{plan.id}", "now")
    ]
    assert feed[0].department == "investment" and feed[0].urgent


async def test_a_buy_zone_and_a_first_target_reached_are_about_today_not_urgent(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    plan = await make_plan(uow, user)
    await alert(uow, user, "NVDA", AlertKind.PLAN_ENTRY)
    await alert(uow, user, "NVDA", AlertKind.PLAN_TARGET)
    link = f"/investment/plans/{plan.id}"
    assert shown(await feed_of(uow, user), "plan_hit") == [
        ("plan_hit", "NVDA reached its buy zone (124.00 to 125.00)", link, "today"),
        ("plan_hit", "NVDA reached its first target (130.00)", link, "today"),
    ]


async def test_a_zone_with_one_price_reads_as_that_price(uow: UowFactory) -> None:
    user = await person(uow)
    await make_plan(uow, user, entry_low=None)
    await alert(uow, user, "NVDA", AlertKind.PLAN_ENTRY)
    (item,) = shown(await feed_of(uow, user), "plan_hit")
    assert item[1] == "NVDA reached its buy zone (125.00)"


async def test_a_plan_alert_without_one_clear_plan_links_the_stock(uow: UowFactory) -> None:
    """The alert row doesn't name its plan: with no plan running that day with that price, or
    two of them, the item links the stock page and leaves the price out."""
    user = await person(uow)
    await alert(uow, user, "NVDA", AlertKind.PLAN_STOP, urgent=True)  # no plan at all
    await make_plan(uow, user, symbol="AMD", valid_until=date(2026, 10, 19))  # ran out before
    await alert(uow, user, "AMD", AlertKind.PLAN_STOP)
    await make_plan(uow, user, symbol="MSFT")
    await make_plan(uow, user, symbol="MSFT", created_at=datetime(2026, 10, 17, 22, tzinfo=UTC))
    await alert(uow, user, "MSFT", AlertKind.PLAN_STOP)
    got = {i[1]: i[2] for i in shown(await feed_of(uow, user), "plan_hit")}
    assert got == {
        "NVDA reached its stop": "/investment/stocks/NVDA",
        "AMD reached its stop": "/investment/stocks/AMD",
        "MSFT reached its stop": "/investment/stocks/MSFT",
    }


async def test_a_big_move_is_about_today_and_links_the_stock(uow: UowFactory) -> None:
    user = await person(uow)
    words = move_text("AMD", D("-6.2"), D("112.30"), NOW, SG)
    await alert(uow, user, "AMD", AlertKind.BIG_MOVE, words=words)
    feed = await feed_of(uow, user)
    assert shown(feed, "big_move") == [
        ("big_move", f"AMD {MINUS}6.2% today", "/investment/stocks/AMD", "today")
    ]
    assert not feed[0].urgent and feed[0].department == "investment"


def test_the_change_is_read_back_from_a_big_move_alert() -> None:
    at = datetime(2026, 10, 20, 14, 42, tzinfo=UTC)
    for change, written in [(D("-6.2"), f"{MINUS}6.2%"), (D("5.44"), "+5.4%")]:
        assert moved_in(move_text("AMD", change, D("112.30"), at, SG)) == written
    assert moved_in("something else") is None


async def test_only_todays_alerts_count_and_only_the_users_own(uow: UowFactory) -> None:
    user = await person(uow, 4242)
    other = await person(uow, 5151)
    await make_plan(uow, user)
    await make_plan(uow, other)
    await alert(uow, user, "NVDA", AlertKind.PLAN_STOP, day=NY_TODAY - timedelta(days=1))
    # The user's local date is the 21st, but the trading day is still New York's 20th.
    await alert(uow, user, "AMD", AlertKind.BIG_MOVE, day=LOCAL_TODAY)
    await alert(uow, other, "NVDA", AlertKind.PLAN_STOP, urgent=True)
    await alert(uow, other, "AMD", AlertKind.BIG_MOVE)
    assert shown(await feed_of(uow, user), "plan_hit", "big_move") == []
    assert len(shown(await feed_of(uow, other), "plan_hit", "big_move")) == 2
    # Once it is the 21st in New York too, the alert keyed to the 21st is today's.
    later = datetime(2026, 10, 21, 14, 0, tzinfo=UTC)
    got = shown(await feed_of(uow, user, later), "plan_hit", "big_move")
    assert [g[0] for g in got] == ["big_move"]


async def test_earnings_today_or_tomorrow_in_new_york_for_stocks_held_or_watched(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    await hold(uow, user, "MSFT")
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    await hold(uow, user, "ORCL")
    await report(uow, "MSFT", NY_TODAY + timedelta(days=1))  # the 21st in New York
    await report(uow, "AMD", NY_TODAY)  # the 20th: today there, though the user's date is the 21st
    await report(uow, "ORCL", NY_TODAY + timedelta(days=2))  # the day after tomorrow
    await report(uow, "NVDA", NY_TODAY)  # not held or watched
    assert shown(await feed_of(uow, user), "earnings") == [
        ("earnings", "AMD reports earnings today", "/investment/stocks/AMD", "today"),
        ("earnings", "MSFT reports earnings tomorrow", "/investment/stocks/MSFT", "soon"),
    ]


async def test_an_earnings_date_that_has_passed_is_not_listed(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "MSFT")
    await report(uow, "MSFT", NY_TODAY - timedelta(days=1))
    assert shown(await feed_of(uow, user), "earnings") == []


async def test_nobody_else_sees_a_stock_they_neither_hold_nor_watch_report(
    uow: UowFactory,
) -> None:
    user = await person(uow, 4242)
    other = await person(uow, 5151)
    await hold(uow, user, "MSFT")
    await report(uow, "MSFT", NY_TODAY)
    assert len(shown(await feed_of(uow, user), "earnings")) == 1
    assert shown(await feed_of(uow, other), "earnings") == []


# --- travel: bookings about to happen, trips to get ready for ----------------------------------


async def trip(
    uow: UowFactory, user: User, start: date, end: date | None = None, where: str = "Tokyo"
) -> Any:
    return await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft(where, start, end or start + timedelta(days=8), "JPY", sgd("3000")),
        now=NOW,
    )


async def book(
    uow: UowFactory,
    user: User,
    trip_id: Any,
    kind: BookingKind,
    *,
    departs: datetime | None = None,
    number: str | None = "SQ12",
    to: str | None = "Tokyo",
    check_in: date | None = None,
    hotel: str | None = None,
) -> Booking:
    segments = (
        (Segment(number, "SIN", to, departs, departs + timedelta(hours=7)),) if departs else ()
    )
    draft = BookingDraft(
        kind,
        "Acme Air",
        segments,
        hotel,
        None,
        check_in,
        check_in + timedelta(days=3) if check_in else None,
    )
    made = Booking(uuid4(), user.id, trip_id, None, draft, None, None, NOW)
    async with uow() as tx:
        assert await tx.trips.insert_booking(made)
        await tx.commit()
    return made


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """A booking's local time: a plain wall-clock time, no timezone."""
    return datetime(day.year, day.month, day.day, hour, minute)


async def test_flights_and_stays_today_or_tomorrow_on_a_trip_are_listed(uow: UowFactory) -> None:
    user = await person(uow)
    tokyo = await trip(uow, user, LOCAL_TODAY, LOCAL_TODAY + timedelta(days=8))
    tomorrow = LOCAL_TODAY + timedelta(days=1)
    await book(uow, user, tokyo.id, BookingKind.FLIGHT, departs=at(tomorrow, 9, 40))
    await book(
        uow, user, tokyo.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 18, 30), number="SQ638"
    )
    await book(uow, user, tokyo.id, BookingKind.RAIL, departs=at(tomorrow, 7, 5), number="N700")
    await book(uow, user, tokyo.id, BookingKind.HOTEL, check_in=LOCAL_TODAY, hotel="Hotel Sakura")
    await book(uow, user, tokyo.id, BookingKind.HOTEL, check_in=tomorrow, hotel="Inn Kiku")
    link = f"/travel/trips/{tokyo.id}"
    got = shown(await feed_of(uow, user), "booking_soon")
    assert got == [
        ("booking_soon", "Check in at Hotel Sakura today", link, "now"),
        ("booking_soon", "Flight SQ638 to Tokyo today 18:30", link, "now"),
        ("booking_soon", "Check in at Inn Kiku tomorrow", link, "soon"),
        ("booking_soon", "Train N700 to Tokyo tomorrow 07:05", link, "soon"),
        ("booking_soon", "Flight SQ12 to Tokyo tomorrow 09:40", link, "soon"),
    ]


async def test_a_departure_that_has_left_or_is_two_days_away_is_not_listed(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    tokyo = await trip(uow, user, LOCAL_TODAY, LOCAL_TODAY + timedelta(days=8))
    await book(uow, user, tokyo.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 7, 0))  # left
    await book(uow, user, tokyo.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 9, 0))  # leaving
    day_after = LOCAL_TODAY + timedelta(days=2)
    await book(uow, user, tokyo.id, BookingKind.FLIGHT, departs=at(day_after, 9, 0))
    await book(uow, user, tokyo.id, BookingKind.HOTEL, check_in=day_after, hotel="Inn Kiku")
    await book(uow, user, tokyo.id, BookingKind.HOTEL, check_in=LOCAL_TODAY - timedelta(days=1))
    got = shown(await feed_of(uow, user), "booking_soon")
    assert [g[1] for g in got] == ["Flight SQ12 to Tokyo today 09:00"]


async def test_a_flight_without_a_number_or_place_still_reads_plainly(uow: UowFactory) -> None:
    user = await person(uow)
    tokyo = await trip(uow, user, LOCAL_TODAY)
    await book(
        uow, user, tokyo.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 23), number=None, to=None
    )
    (item,) = shown(await feed_of(uow, user), "booking_soon")
    assert item[1] == "Flight today 23:00"


async def test_today_is_the_users_local_date_not_utc(uow: UowFactory) -> None:
    """00:30 on the 21st in Singapore is still the 20th in UTC."""
    user = await person(uow)
    tokyo = await trip(uow, user, LOCAL_TODAY)
    early = datetime(2026, 10, 21, 0, 30, tzinfo=SG)
    await book(uow, user, tokyo.id, BookingKind.HOTEL, check_in=LOCAL_TODAY, hotel="Hotel Sakura")
    await book(uow, user, tokyo.id, BookingKind.HOTEL, check_in=date(2026, 10, 20), hotel="Old")
    got = shown(await feed_of(uow, user, early), "booking_soon")
    assert [(g[1], g[3]) for g in got] == [("Check in at Hotel Sakura today", "now")]


async def test_bookings_not_on_a_trip_and_plans_are_not_booking_soon(uow: UowFactory) -> None:
    user = await person(uow)
    tokyo = await trip(uow, user, LOCAL_TODAY)
    await book(uow, user, None, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 18, 0))
    dinner = BookingDraft(
        BookingKind.ACTIVITY, None, (), None, None, None, None, name="Dinner", day=LOCAL_TODAY
    )
    async with uow() as tx:
        await tx.trips.insert_booking(
            Booking(uuid4(), user.id, tokyo.id, None, dinner, None, None, NOW)
        )
        await tx.commit()
    feed = await feed_of(uow, user)
    assert shown(feed, "booking_soon") == []
    assert [i.kind for i in feed] == ["booking"]  # the loose one is still "not on a trip"


async def test_another_users_bookings_and_trips_never_appear(uow: UowFactory) -> None:
    user = await person(uow, 4242)
    other = await person(uow, 5151)
    theirs = await trip(uow, other, LOCAL_TODAY + timedelta(days=2), where="Osaka")
    await book(uow, other, theirs.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 18, 0))
    await prep_cases.add_todo(uow(), other, theirs.id, "Get yen", None, now=NOW)
    assert shown(await feed_of(uow, user), "booking_soon", "prep") == []
    assert len(shown(await feed_of(uow, other), "booking_soon", "prep")) == 2


async def test_a_member_of_a_shared_trip_is_not_told_about_its_bookings(
    uow: UowFactory,
) -> None:
    """Like ``next_trip`` and ``list_trips``, the items cover the user's own trips only."""
    owner = await person(uow, 4242)
    member = await person(uow, 5151)
    shared = await trip(uow, owner, LOCAL_TODAY + timedelta(days=2))
    await book(uow, owner, shared.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 18, 0))
    await prep_cases.add_todo(uow(), owner, shared.id, "Get yen", None, now=NOW)
    async with uow() as tx:
        assert await tx.trips.add_member(owner.id, shared.id, member.id, None, NOW)
        await tx.commit()
    assert shown(await feed_of(uow, member), "booking_soon", "prep") == []
    assert len(shown(await feed_of(uow, owner), "booking_soon", "prep")) == 2


async def test_prep_counts_open_to_dos_on_a_trip_starting_within_a_week(uow: UowFactory) -> None:
    user = await person(uow)
    week = await trip(uow, user, LOCAL_TODAY + timedelta(days=7), where="Tokyo")
    for words in ("Get yen", "Book a taxi", "Print the visa"):
        await prep_cases.add_todo(uow(), user, week.id, words, None, now=NOW)
    done_one = await prep_cases.add_todo(uow(), user, week.id, "Buy a charger", None, now=NOW)
    assert done_one[1] is not None
    await prep_cases.set_todos(
        uow(),
        user,
        week.id,
        [replace(t, done=t.id == done_one[1].id) for t in done_one[0].todos],
        now=NOW,
    )
    got = shown(await feed_of(uow, user), "prep")
    assert got == [
        ("prep", "3 things to sort before Tokyo", f"/travel/trips/{week.id}?tab=prep", "soon")
    ]


async def test_prep_boundaries_and_wording(uow: UowFactory) -> None:
    user = await person(uow)
    far = await trip(uow, user, LOCAL_TODAY + timedelta(days=8), where="Far")
    started = await trip(uow, user, LOCAL_TODAY - timedelta(days=1), where="Begun")
    today = await trip(uow, user, LOCAL_TODAY, where="Kyoto")
    clear = await trip(uow, user, LOCAL_TODAY + timedelta(days=3), where="Clear")
    for made in (far, started, today):
        await prep_cases.add_todo(uow(), user, made.id, "Get yen", None, now=NOW)
    # A trip with nothing left to do isn't mentioned.
    _, todo = await prep_cases.add_todo(uow(), user, clear.id, "Get yen", None, now=NOW)
    assert todo is not None
    await prep_cases.set_todos(uow(), user, clear.id, [replace(todo, done=True)], now=NOW)
    got = shown(await feed_of(uow, user), "prep")
    assert [g[1] for g in got] == ["1 thing to sort before Kyoto"]


# --- order ------------------------------------------------------------------------------------


async def test_the_list_is_urgent_first_then_today_then_the_rest_by_department(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    await bill_cases.add_bill(
        uow(), user, "Visa", LOCAL_TODAY + timedelta(days=3), Cadence.MONTHLY, None, now=NOW
    )
    await bill_cases.add_bill(uow(), user, "Rent", LOCAL_TODAY, Cadence.MONTHLY, None, now=NOW)
    await make_plan(uow, user)
    await hold(uow, user, "NVDA")
    await alert(uow, user, "NVDA", AlertKind.PLAN_STOP, urgent=True)
    await alert(
        uow, user, "AMD", AlertKind.BIG_MOVE, words=move_text("AMD", D("6.2"), D("1"), NOW, SG)
    )
    await hold(uow, user, "MSFT")
    await report(uow, "MSFT", NY_TODAY + timedelta(days=1))
    tokyo = await trip(uow, user, LOCAL_TODAY + timedelta(days=3))
    await prep_cases.add_todo(uow(), user, tokyo.id, "Get yen", None, now=NOW)
    flight = await trip(uow, user, LOCAL_TODAY - timedelta(days=1), where="Seoul")
    await book(uow, user, flight.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY, 20))
    await book(
        uow, user, flight.id, BookingKind.FLIGHT, departs=at(LOCAL_TODAY + timedelta(days=1), 8)
    )
    feed = await feed_of(uow, user)
    assert [(i.when, i.department, i.kind) for i in feed] == [
        ("now", "accounting", "bill"),
        ("now", "investment", "plan_hit"),
        ("now", "travel", "booking_soon"),
        ("today", "investment", "big_move"),
        ("soon", "accounting", "bill"),
        ("soon", "investment", "earnings"),
        ("soon", "travel", "booking_soon"),
        ("soon", "travel", "prep"),
    ]
    assert feed[0].text.startswith("Rent")


async def test_existing_items_keep_their_place_within_a_group(uow: UowFactory) -> None:
    user = await person(uow)
    for name, days in [("Visa", 2), ("Phone", 1), ("Water", 4)]:
        await bill_cases.add_bill(
            uow(), user, name, LOCAL_TODAY + timedelta(days=days), Cadence.MONTHLY, None, now=NOW
        )
    expected = [v.bill.name for v in await bill_cases.list_bills(uow, user, now=NOW)]
    feed = await feed_of(uow, user)
    assert [i.text.split(" ")[0] for i in feed] == expected and len(expected) == 3
    assert {i.when for i in feed} == {"soon"}


# --- through the web API ------------------------------------------------------------------------


async def test_the_home_feed_carries_when_and_comes_sorted(world: World) -> None:
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    for name, due in [("Visa", "2026-10-01"), ("Rent", "2026-09-28")]:  # the clock says 28 Sep
        made = await owner.send("POST", "/api/bills", {"name": name, "due": due})
        assert made.status_code == 201, made.text
    feed = (await owner.get("/api/home")).json()
    assert [(i["kind"], i["when"], i["urgent"]) for i in feed] == [
        ("bill", "now", True),
        ("bill", "soon", False),
    ]
    assert feed[0]["text"].startswith("Rent") and set(feed[0]) >= {"when", "actions", "link"}


# --- the setup checklist ----------------------------------------------------------------------


def done_keys(found: setup_cases.Setup) -> set[str]:
    return {i.key for i in found.items if i.done}


async def test_a_new_user_has_nothing_set_up(uow: UowFactory) -> None:
    user = await person(uow)
    found = await setup_cases.checklist(uow(), user)
    assert found.dismissed is False
    assert [(i.key, i.label, i.done) for i in found.items] == [
        ("payday", "Set your payday", False),
        ("receipts", "Get receipts in automatically", False),
        ("investments", "Add your stocks", False),
        ("budget", "Set a monthly budget", False),
    ]
    assert all(i.link.startswith("/") and i.ask.strip() for i in found.items)
    assert found.items[0].ask == "My payday is the 25th"


async def test_each_step_is_done_by_what_the_user_has(uow: UowFactory) -> None:
    user = await person(uow)
    await salary_cases.set_schedule(uow(), user, PayRule.MONTHLY_DAY, day=25, anchor=None, now=NOW)
    assert done_keys(await setup_cases.checklist(uow(), user)) == {"payday"}
    await research_cases.watch(uow(), user.id, "AMD", now=NOW)
    assert done_keys(await setup_cases.checklist(uow(), user)) == {"payday", "investments"}
    await budget_cases.set_budget(uow(), user, None, sgd("2000"), now=NOW)
    assert done_keys(await setup_cases.checklist(uow(), user)) == {
        "payday",
        "investments",
        "budget",
    }
    await connect(uow, user, FakeMailbox())
    assert len(done_keys(await setup_cases.checklist(uow(), user))) == 4


async def test_holding_a_stock_counts_as_much_as_watching_one(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "MSFT")
    assert done_keys(await setup_cases.checklist(uow(), user)) == {"investments"}


async def test_a_connection_that_needs_reconnecting_is_not_done(uow: UowFactory) -> None:
    user = await person(uow)
    connection = await connect(uow, user, FakeMailbox())
    async with uow() as tx:
        await tx.email.update_connection(replace(connection, status=ConnectionStatus.BROKEN))
        await tx.commit()
    assert "receipts" not in done_keys(await setup_cases.checklist(uow(), user))


async def test_one_users_setup_never_counts_for_another(uow: UowFactory) -> None:
    user = await person(uow, 4242)
    other = await person(uow, 5151)
    await hold(uow, user, "MSFT")
    await connect(uow, user, FakeMailbox())
    assert done_keys(await setup_cases.checklist(uow(), other)) == set()


async def test_dismissing_keeps_the_items_and_is_safe_to_repeat(uow: UowFactory) -> None:
    user = await person(uow, 4242)
    other = await person(uow, 5151)
    await setup_cases.dismiss(uow(), user, now=NOW)
    async with uow() as tx:
        user = await tx.ledger.get_user(user.id) or user
    assert user.setup_dismissed_at == NOW
    found = await setup_cases.checklist(uow(), user)
    assert found.dismissed is True and len(found.items) == 4
    await setup_cases.dismiss(uow(), user, now=NOW + timedelta(days=1))
    async with uow() as tx:
        again = await tx.ledger.get_user(user.id)
        theirs = await tx.ledger.get_user(other.id)
    assert again is not None and again.setup_dismissed_at == NOW
    assert theirs is not None and theirs.setup_dismissed_at is None


async def test_the_setup_api_reports_and_dismisses(world: World) -> None:
    owner, member = world.browser(), world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    invite = (await owner.send("POST", "/api/invites")).json()["url"].rsplit("/", 1)[-1]
    assert (await member.login(test_web_api.MEMBER, invite)).status_code == 200
    first = (await owner.get("/api/setup")).json()
    assert first["dismissed"] is False
    assert [i["key"] for i in first["items"]] == ["payday", "receipts", "investments", "budget"]
    assert set(first["items"][0]) == {"key", "label", "done", "link", "ask"}
    assert not any(i["done"] for i in first["items"])

    assert (
        await owner.send("PUT", "/api/salary", {"rule": "monthly_day", "day": 25})
    ).status_code == 204
    assert (await owner.send("PUT", "/api/budgets", {"amount": "2000"})).status_code == 204
    done = {i["key"] for i in (await owner.get("/api/setup")).json()["items"] if i["done"]}
    assert done == {"payday", "budget"}

    assert (await owner.send("POST", "/api/setup/dismiss")).status_code == 204
    assert (await owner.send("POST", "/api/setup/dismiss")).status_code == 204
    after = (await owner.get("/api/setup")).json()
    assert after["dismissed"] is True and len(after["items"]) == 4
    # A member has a checklist of their own.
    theirs = (await member.get("/api/setup")).json()
    assert theirs["dismissed"] is False and not any(i["done"] for i in theirs["items"])
    assert (await member.send("POST", "/api/setup/dismiss")).status_code == 204
    assert (await owner.get("/api/setup")).json()["dismissed"] is True


async def test_the_setup_api_needs_a_signed_in_user_and_a_csrf_token(world: World) -> None:
    stranger = world.browser()
    assert (await stranger.get("/api/setup")).status_code == 401
    assert (await stranger.send("POST", "/api/setup/dismiss")).status_code == 401
    owner = world.browser()
    await owner.login(OWNER)
    assert (
        await owner.send("POST", "/api/setup/dismiss", None, **{"X-CSRF-Token": "no"})
    ).status_code == 403
    assert (await owner.get("/api/setup")).json()["dismissed"] is False


# --- the migration ------------------------------------------------------------------------------


async def test_migration_0052_goes_up_and_down(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    user = await person(uow)
    assert user.setup_dismissed_at is None
    await setup_cases.dismiss(uow(), user, now=NOW)
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0051")

    async def columns() -> set[str]:
        async with engine.connect() as db:
            rows = await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
                )
            )
            return set(rows.scalars().all())

    assert "setup_dismissed_at" not in await columns()
    await upgrade(empty_database_url)
    assert "setup_dismissed_at" in await columns()
    async with engine.connect() as db:
        left: object = (await db.execute(text("SELECT setup_dismissed_at FROM users"))).scalar_one()
    assert left is None  # coming back, the checklist is shown again
