"""The morning summary of the US market: who gets it and when, what it says, and that it
is sent once, in the user's morning, whatever quiet hours say. Every ticker and figure here
is made up. October 2026 is still daylight time in New York (UTC-4); the made-up user lives
in Singapore (UTC+8), so 08:00 on Tuesday 20 October there is 20:00 on Monday 19 October in
New York, four hours after the close."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import market_summary as summary_cases
from nexus.application import moves as move_cases
from nexus.application import notifications as notify_cases
from nexus.application import plans as plan_cases
from nexus.application import research as research_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.users import RegisterUser, register_user
from nexus.domain.alerts import MINUS, AlertKind, MarketAlert
from nexus.domain.ledger import User
from nexus.domain.market import PriceKind, Session
from nexus.infra.db.tables import jobs
from nexus.jobs.handlers import SCHEDULES, build_handlers
from nexus.jobs.runner import JobRunner, Schedule
from tests.fakes import FakeTelegram
from tests.integration.conftest import UowFactory
from tests.integration.test_email import person
from tests.integration.test_market_alerts import (
    MONDAY,
    QUIET,
    bar,
    check,
    plan,
    price,
    save_bar,
)
from tests.integration.test_moves import RATES, bars, book, headlines, quotes
from tests.integration.test_quotes import MON_OPEN, hold, ny

pytestmark = pytest.mark.integration

SGT = ZoneInfo("Asia/Singapore")
MORNING = datetime(2026, 10, 20, 8, 0, tzinfo=SGT)  # Monday 20:00 in New York


async def queued(engine: AsyncEngine, kind: str) -> list[Any]:
    async with engine.connect() as db:
        return list(await db.execute(select(jobs).where(jobs.c.kind == kind).order_by(jobs.c.id)))


async def run_morning(uow: UowFactory, engine: AsyncEngine, at: datetime = MORNING) -> FakeTelegram:
    """The sweep, the per-user job and the sender, as the job runner runs them."""
    telegram = FakeTelegram()
    handlers = build_handlers(uow, telegram, RATES, lambda: at)
    wanted = {
        k: handlers[k] for k in (summary_cases.SWEEP_JOB, summary_cases.USER_JOB, TELEGRAM_SEND)
    }
    runner = JobRunner(
        engine,
        wanted,
        schedules=[Schedule(summary_cases.SWEEP_JOB, timedelta(minutes=10))],
        clock=lambda: at,
    )
    for _ in range(4):  # sweep, then the user's job, then the message
        await runner.tick()
    return telegram


async def add_alert(
    uow: UowFactory, user: User, kind: AlertKind, symbol: str, text: str, created: datetime
) -> MarketAlert:
    alert = MarketAlert(uuid4(), user.id, symbol, kind, MONDAY, text, False, created)
    async with uow() as tx:
        assert await tx.investments.insert_alert(alert)
        await tx.commit()
    return alert


EXPECTED = [
    "📊 Portfolio +0.9% yesterday (SGD +45.50)",
    "Biggest movers:",
    "• NVDA +6.0% to 106.00: Nvidia wins a big order (Wire)",
    f"• AMD {MINUS}3.0% to 97.00",
    "• TSLA +1.0% to 101.00: Tesla recalls some cars (Wire)",
]


# --- what it says -------------------------------------------------------------------------


async def test_the_summary_tells_the_portfolio_the_movers_and_what_was_held_back(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await book(uow)
    during = await add_alert(
        uow, user, AlertKind.BIG_MOVE, "NVDA", "📈 NVDA +6.0% today at 10:41pm, 106.00", QUIET
    )
    after = await add_alert(
        uow,
        user,
        AlertKind.PLAN_TARGET,
        "TSLA",
        "🎯 TSLA reached its first target, 130.00, on 19 Oct.",
        ny("2026-10-19 19:00"),
    )
    telegram = await run_morning(uow, engine)
    (sent,) = telegram.sent
    assert sent.chat_id == 4242
    assert sent.text.split("\n") == [
        *EXPECTED,
        "While the market was open:",
        "• 📈 NVDA +6.0% today at 10:41pm, 106.00",
        "Your plans after the close:",
        "• 🎯 TSLA reached its first target, 130.00, on 19 Oct.",
    ]
    (job,) = await queued(engine, TELEGRAM_SEND)
    assert job.payload["anytime"] is True  # the user's morning, quiet hours or not
    assert (job.payload["kind"], job.payload["level"]) == ("market_summary", "now")
    async with uow() as tx:
        assert await tx.investments.unsent_alerts(user.id, MONDAY) == []  # marked sent
    assert during.id != after.id


async def test_a_summary_without_alerts_is_the_portfolio_and_the_movers(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    await book(uow)
    telegram = await run_morning(uow, engine)
    assert telegram.sent[0].text.split("\n") == EXPECTED


async def test_a_losing_day_says_so_with_a_real_minus_sign(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await hold(uow, user, "AMD", "10")
    await bars(uow, "AMD")
    await quotes(uow, AMD="95")
    telegram = await run_morning(uow, engine)
    assert telegram.sent[0].text.split("\n")[:2] == [
        f"📊 Portfolio {MINUS}5.0% yesterday (SGD {MINUS}65.00)",
        "Biggest movers:",
    ]


async def test_a_watcher_with_no_holdings_gets_the_watched_stocks(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await research_cases.watch(uow(), user.id, "NVDA", now=MON_OPEN)
    await bars(uow, "NVDA")
    await quotes(uow, NVDA="106")
    await headlines(uow, NVDA=[(ny("2026-10-19 10:00"), "Nvidia unveils a new chip")])
    telegram = await run_morning(uow, engine)
    assert telegram.sent[0].text.split("\n") == [
        "📊 Your stocks yesterday",
        "Your watchlist moved most:",
        "• NVDA +6.0% to 106.00: Nvidia unveils a new chip (Wire)",
    ]


async def test_a_long_list_of_alerts_is_cut_with_the_count(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await book(uow)
    for n in range(13):
        await add_alert(uow, user, AlertKind.BIG_MOVE, f"S{n:02d}", f"alert {n}", QUIET)
    telegram = await run_morning(uow, engine)
    lines = telegram.sent[0].text.split("\n")
    assert lines[-1] == "and 3 more." and lines.count("• alert 0") == 1 and "• alert 9" in lines


async def test_the_days_wording_follows_the_users_calendar() -> None:
    report = move_cases.Today(
        Session.CLOSED_TODAY, MONDAY, "SGD", None, None,
        PriceKind.CLOSE, None, False, [],
    )  # fmt: skip
    assert summary_cases.describe(report, [], MONDAY, date(2026, 10, 20)) is None  # nothing to say
    one = move_cases.Mover(
        "NVDA", False, Decimal("106"), Decimal("6"),
        PriceKind.CLOSE, None, MONDAY, None,
    )  # fmt: skip
    wide = replace(report, movers=[one])
    assert summary_cases.describe(wide, [], MONDAY, date(2026, 10, 22)) == (
        "📊 Your stocks on Mon 19 Oct\nYour watchlist moved most:\n• NVDA +6.0% to 106.00"
    )


# --- end to end: held through the night, then told ----------------------------------------


async def test_what_was_held_overnight_arrives_in_the_morning_summary(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await book(uow)
    await plan(uow, user)
    await hold(uow, user, "NVDA")
    # 23:30 in Singapore: a big move and a buy zone, both held back.
    await price(uow, "NVDA", "2026-10-19 11:30", "124.50", before="140")
    assert await check(uow, QUIET) == 2
    # The close finds a dip the quotes missed in another plan; 07:00 in Singapore: held too.
    await save_bar(uow, bar("NVDA", MONDAY, "126.50", "123.90", "127.00"))
    assert await plan_cases.follow_plans(uow, now=ny("2026-10-19 19:00")) == 0  # told already
    telegram = await run_morning(uow, engine)
    text = telegram.sent[0].text
    assert text.split("\n")[0].startswith("📊 Portfolio ")
    section = text.split("While the market was open:\n")[1].split("\n")
    assert any(line.startswith("• 📉 NVDA") for line in section)
    assert any(line.startswith("• 🟢 NVDA dipped into its buy zone") for line in section)
    assert "Your plans after the close:" not in text  # nothing new came from the follow


async def test_a_plan_event_found_only_by_the_evening_follow_is_in_the_summary(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await book(uow)
    await plan(uow, user, symbol="AAPL")
    await save_bar(uow, bar("AAPL", MONDAY, "126.50", "123.90", "127.00"))
    assert await plan_cases.follow_plans(uow, now=ny("2026-10-19 19:00")) == 1  # 07:00: held
    assert await queued(engine, TELEGRAM_SEND) == []
    telegram = await run_morning(uow, engine)
    lines = telegram.sent[0].text.split("\n")
    i = lines.index("Your plans after the close:")
    assert lines[i + 1].startswith("• 🟢 AAPL dipped into its buy zone")
    assert len(telegram.sent) == 1  # one message, not the summary and the plan's own


# --- who gets it, and when ----------------------------------------------------------------


async def test_it_is_scheduled_every_ten_minutes() -> None:
    assert Schedule(summary_cases.SWEEP_JOB, timedelta(minutes=10)) in SCHEDULES


async def test_it_is_sent_once_per_user_and_day(uow: UowFactory, engine: AsyncEngine) -> None:
    await book(uow)
    telegram = await run_morning(uow, engine)
    assert len(telegram.sent) == 1
    # More sweeps through the morning queue nothing more.
    for minutes in (10, 60, 200):
        assert await summary_cases.sweep(uow, now=MORNING + timedelta(minutes=minutes)) == 0
    assert len(await queued(engine, summary_cases.USER_JOB)) == 1
    assert len(telegram.sent) == 1


async def test_not_before_eight_after_noon_or_on_a_weekend(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    await book(uow)
    for at in (
        datetime(2026, 10, 20, 7, 59, tzinfo=SGT),
        datetime(2026, 10, 20, 12, 0, tzinfo=SGT),
        datetime(2026, 10, 25, 8, 0, tzinfo=SGT),  # Sunday
        datetime(2026, 10, 26, 8, 0, tzinfo=SGT),  # Monday: the market has been shut since Fri
    ):
        assert await summary_cases.sweep(uow, now=at) == 0, at
    assert await queued(engine, summary_cases.USER_JOB) == []
    # Saturday morning tells of Friday's session.
    saturday = datetime(2026, 10, 24, 8, 0, tzinfo=SGT)
    assert await summary_cases.sweep(uow, now=saturday) == 1


async def test_not_the_morning_after_a_market_holiday(uow: UowFactory, engine: AsyncEngine) -> None:
    await book(uow)
    # Thanksgiving, Thursday 26 November 2026: nothing traded, so Friday morning is quiet,
    # and so is Saturday's (Friday's session closed early but did trade: it is told).
    assert await summary_cases.sweep(uow, now=datetime(2026, 11, 27, 8, tzinfo=SGT)) == 0
    assert await summary_cases.sweep(uow, now=datetime(2026, 11, 28, 8, tzinfo=SGT)) == 1


async def test_only_those_who_want_it_and_follow_a_stock_get_it(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    wanted = await book(uow)
    off = await person(uow, 4343)
    await hold(uow, off, "NVDA")
    await notify_cases.set_market(uow(), off.id, now=MORNING, market_summary=False)
    await person(uow, 4545)  # follows no stock
    assert await summary_cases.sweep(uow, now=MORNING) == 1
    (job,) = await queued(engine, summary_cases.USER_JOB)
    assert job.payload["user_id"] == str(wanted.id)
    assert job.payload["day"] == "2026-10-19" and job.payload["date"] == "2026-10-20"


async def test_each_user_gets_it_in_their_own_morning(uow: UowFactory, engine: AsyncEngine) -> None:
    singapore = await book(uow)
    new_york = (
        await register_user(
            uow(),
            RegisterUser(
                telegram_user_id=4343,
                telegram_chat_id=4343,
                home_currency="SGD",
                timezone="America/New_York",
            ),
        )
    ).user
    await hold(uow, new_york, "NVDA")
    # 08:00 in Singapore is 20:00 in New York: only the Singapore user's morning.
    assert await summary_cases.sweep(uow, now=MORNING) == 1
    # 08:00 in New York the next morning (12:00 UTC): their turn, for Monday's session.
    at = datetime(2026, 10, 20, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    assert await summary_cases.sweep(uow, now=at) == 1
    users = {j.payload["user_id"] for j in await queued(engine, summary_cases.USER_JOB)}
    assert users == {str(singapore.id), str(new_york.id)}


async def test_nothing_is_sent_when_there_is_nothing_to_tell(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")  # no price of any kind yet
    telegram = await run_morning(uow, engine)
    assert telegram.sent == [] and await queued(engine, TELEGRAM_SEND) == []


async def test_turning_the_summary_off_between_the_sweep_and_the_message_sends_nothing(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await book(uow)
    assert await summary_cases.sweep(uow, now=MORNING) == 1
    await notify_cases.set_market(uow(), user.id, now=MORNING, market_summary=False)
    (job,) = await queued(engine, summary_cases.USER_JOB)
    assert await summary_cases.send(uow, RATES, job.payload, now=MORNING) is False
    assert await queued(engine, TELEGRAM_SEND) == []


async def test_a_summary_built_twice_is_queued_once(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await book(uow)
    await add_alert(uow, user, AlertKind.BIG_MOVE, "NVDA", "held", QUIET)
    assert await summary_cases.sweep(uow, now=MORNING) == 1
    (job,) = await queued(engine, summary_cases.USER_JOB)
    assert await summary_cases.send(uow, RATES, job.payload, now=MORNING) is True
    assert await summary_cases.send(uow, RATES, job.payload, now=MORNING) is False
    assert len(await queued(engine, TELEGRAM_SEND)) == 1
