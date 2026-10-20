"""Alerts while the US market is open: plan prices reached, big moves, once a day, held
through quiet hours for the morning summary except what is urgent, and the evening follow
on daily bars not saying it again. Every ticker and figure here is made up. October 2026
is still daylight time in New York (UTC-4); the made-up user lives in Singapore (UTC+8),
whose quiet hours are 23:00 to 08:00, so 10:42 in New York is 22:42 there and 11:00 is
23:00."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import market_alerts as alert_cases
from nexus.application import notifications as notify_cases
from nexus.application import plans as plan_cases
from nexus.application import quotes as quote_cases
from nexus.application import research as research_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.quotes import Quotes
from nexus.domain.alerts import MINUS, AlertKind, MarketAlert
from nexus.domain.ledger import User
from nexus.domain.market import Bar, MarketStatus
from nexus.domain.notifications import Frequency
from nexus.domain.plans import EventKind, Followed, PlanEvent, PlanStatus, SavedPlan, Verdict
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import jobs, market_alerts, users
from nexus.jobs.handlers import build_handlers
from nexus.jobs.runner import Defer
from tests.fakes import FakeQuotes, FakeRates, FakeTelegram, quote
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import person
from tests.integration.test_quotes import MON_OPEN, OPEN, hold, keep, ny
from tests.unit.test_plan_follow import saved

pytestmark = pytest.mark.integration

D = Decimal
MONDAY = date(2026, 10, 19)
QUIET = ny("2026-10-19 11:30")  # 23:30 in Singapore
SHUT = MarketStatus(False, "post-market", None, ny("2026-10-19 17:00"))


def open_at(when: datetime) -> MarketStatus:
    return MarketStatus(True, "regular", None, when)


async def plan(uow: UowFactory, user: User, **changes: Any) -> SavedPlan:
    """A buy plan for NVDA: buy zone 124 to 125, stop 122, first target 130."""
    fields: dict[str, Any] = {
        "user_id": user.id,
        "symbol": "NVDA",
        "as_of": date(2026, 10, 16),
        "valid_until": date(2026, 10, 30),
        "created_at": datetime(2026, 10, 16, 22, tzinfo=UTC),
    }
    verdict = changes.pop("verdict", Verdict.WAIT)
    made = saved(verdict, **{**fields, **changes})
    async with uow() as tx:
        await tx.investments.insert_plan(made)
        if made.entered_on is not None:  # kept as following the plan keeps it
            await tx.investments.save_followed(
                user.id,
                made.id,
                Followed(made.status, made.entered_on, made.entered_on, None, None, None, []),
                at=MON_OPEN,
            )
        if not made.alerts:
            await tx.investments.set_plan_alerts(user.id, made.id, False)
        await tx.commit()
        return await tx.investments.get_plan(user.id, made.id) or made


async def follow(uow: UowFactory, user: User) -> None:
    """The user watches a stock, so a morning summary will come for them."""
    await research_cases.watch(uow(), user.id, "AMD", now=MON_OPEN)


async def price(uow: UowFactory, symbol: str, now: str, last: str, before: str = "126") -> None:
    """The stored quote: ``last`` traded a minute before ``now``; yesterday closed ``before``."""
    at = ny(now) - timedelta(minutes=1)
    await keep(uow, [quote(symbol, last, before, at)], at=at)


async def kept(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as db:
        return list(await db.execute(select(market_alerts).order_by(market_alerts.c.created_at)))


async def sends(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as db:
        rows = await db.execute(
            select(jobs.c.payload, jobs.c.dedupe_key).where(jobs.c.kind == TELEGRAM_SEND)
        )
        return [dict(r.payload, key=r.dedupe_key) for r in rows]


async def check(uow: UowFactory, when: str | datetime = MON_OPEN) -> int:
    now = ny(when) if isinstance(when, str) else when
    return await alert_cases.check(uow, open_at(now), now=now)


# --- the kinds ----------------------------------------------------------------------------


async def test_a_price_in_the_buy_zone_alerts_with_the_plans_own_words(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    made = await plan(uow, user)
    await price(uow, "NVDA", "2026-10-19 10:42", "124.50")
    assert await check(uow) == 1
    (alert,) = await kept(engine)
    assert (alert.symbol, alert.kind, alert.day, alert.urgent) == (
        "NVDA",
        "plan_entry",
        MONDAY,
        False,
    )
    assert alert.sent_at == MON_OPEN
    (send,) = await sends(engine)
    assert send["text"] == plan_cases.event_text(
        made,
        PlanEvent(EventKind.ENTRY, MONDAY, D("125")),
        Followed(PlanStatus.OPEN, None, None, None, None, None, []),
    )
    assert send["text"].startswith(
        "🟢 NVDA dipped into its buy zone (124.0000 to 125.0000) on 19 Oct"
    )
    assert send["buttons"] == [
        [{"label": "Stop alerts for this plan", "data": f"plan:mute:{made.id}"}]
    ]
    assert "urgent" not in send and "anytime" not in send


async def test_a_price_at_the_first_target_alerts_a_plan_already_entered(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await plan(uow, user, entered_on=date(2026, 10, 16))
    await price(uow, "NVDA", "2026-10-19 10:42", "130.40")
    assert await check(uow) == 1
    (send,) = await sends(engine)
    assert send["text"].startswith("🎯 NVDA reached its first target, 130.00, on 19 Oct.")
    assert [a.kind for a in await kept(engine)] == ["plan_target"]


async def test_a_stop_on_a_stock_the_user_holds_is_urgent(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await plan(uow, user, entered_on=date(2026, 10, 16))
    await hold(uow, user, "NVDA")
    await price(uow, "NVDA", "2026-10-19 10:42", "121.50", before="126")
    # Down 3.6%: not a big move, but a stop.
    assert await check(uow) == 1
    (send,) = await sends(engine)
    assert send["text"] == (
        "🛑 NVDA is at 121.50 as of 10:41pm, at or below its stop of 122.00. The plan says "
        "cut it: the reason to own it has broken."
    )
    assert send["urgent"] is True
    (alert,) = await kept(engine)
    assert alert.kind == "plan_stop" and alert.urgent is True


async def test_a_stop_on_a_plan_for_a_stock_not_held_is_not_urgent(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await plan(uow, user, entered_on=date(2026, 10, 16))  # bought, but not recorded as held
    await price(uow, "NVDA", "2026-10-19 10:42", "121.50")
    assert await check(uow) == 1
    (send,) = await sends(engine)
    assert "urgent" not in send


async def test_a_big_move_is_told_for_held_and_watched_stocks(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    await research_cases.watch(uow(), user.id, "AMD", now=MON_OPEN)
    await research_cases.watch(uow(), user.id, "TSLA", now=MON_OPEN)
    at = MON_OPEN - timedelta(minutes=1)
    await keep(
        uow,
        [
            quote("NVDA", "172.00", "182.40", at),  # down 5.7%
            quote("AMD", "157.50", "150.00", at),  # up 5.0%: exactly the threshold
            quote("TSLA", "249.00", "250.00", at),  # down 0.4%
        ],
        at=at,
    )
    assert await check(uow) == 2
    texts = {s["text"] for s in await sends(engine)}
    assert texts == {
        f"📉 NVDA {MINUS}5.7% today at 10:41pm, 172.00",
        "📈 AMD +5.0% today at 10:41pm, 157.50",
    }
    assert {a.kind for a in await kept(engine)} == {"big_move"}


async def test_each_user_has_their_own_threshold(uow: UowFactory, engine: AsyncEngine) -> None:
    calm, nervous = await person(uow), await person(uow, 4343)
    for user in (calm, nervous):
        await hold(uow, user, "NVDA")
    await notify_cases.set_market(uow(), nervous.id, now=MON_OPEN, move_alert_percent="3")
    await price(uow, "NVDA", "2026-10-19 10:42", "96.00", before="100")  # down 4%
    assert await check(uow) == 1
    (send,) = await sends(engine)
    assert send["user_id"] == str(nervous.id)


async def test_a_move_in_a_stock_nobody_follows_alerts_no_one(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    await price(uow, "TSLA", "2026-10-19 10:42", "50", before="100")
    assert await check(uow) == 0 and await sends(engine) == []


# --- once a day, and only while the market is open --------------------------------------


async def test_an_alert_is_made_once_per_stock_kind_and_day(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await plan(uow, user)
    await hold(uow, user, "NVDA")
    await price(uow, "NVDA", "2026-10-19 10:42", "124.50", before="140")  # entry, and down 11%
    assert await check(uow) == 2
    assert await check(uow, "2026-10-19 10:47") == 0
    assert await check(uow, "2026-10-19 15:30") == 0
    assert len(await sends(engine)) == 2 and len(await kept(engine)) == 2
    # The next day it may speak again.
    await price(uow, "NVDA", "2026-10-20 11:00", "124.50", before="140")
    assert await check(uow, "2026-10-20 11:00") == 2
    assert {a.day for a in await kept(engine)} == {MONDAY, date(2026, 10, 20)}


async def test_two_plans_for_one_stock_alert_once(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await person(uow)
    await plan(uow, user)
    await plan(uow, user, entry_high=D("126"))
    await price(uow, "NVDA", "2026-10-19 10:42", "124.50")
    assert await check(uow) == 1 and len(await sends(engine)) == 1


async def test_nothing_is_told_unless_the_regular_session_is_open(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await plan(uow, user)
    await hold(uow, user, "NVDA")
    await price(uow, "NVDA", "2026-10-19 10:42", "100", before="140")
    for status, when in [
        (SHUT, ny("2026-10-19 17:00")),
        (MarketStatus(False, "pre-market", None, MON_OPEN), ny("2026-10-19 08:00")),
        (MarketStatus(False, None, "Made-up Day", MON_OPEN), ny("2026-10-19 10:42")),
        (None, ny("2026-10-17 11:00")),  # a Saturday, by the usual hours
        (None, ny("2026-10-19 07:00")),
    ]:
        assert await alert_cases.check(uow, status, now=when) == 0, when
    assert await sends(engine) == [] and await kept(engine) == []
    # Without the exchange's word, the usual hours say it is open on a Monday morning.
    assert await alert_cases.check(uow, None, now=MON_OPEN) == 2


async def test_the_usual_hours_dont_alert_on_a_listed_holiday(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    thanksgiving = ny("2026-11-26 10:42")
    await keep(
        uow, [quote("NVDA", "50", "100", thanksgiving - timedelta(minutes=1))], at=thanksgiving
    )
    assert await alert_cases.check(uow, None, now=thanksgiving) == 0


async def test_a_stale_quote_from_an_earlier_day_says_nothing(uow: UowFactory) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    old = ny("2026-10-16 15:59")
    await keep(uow, [quote("NVDA", "50", "100", old)], at=old)
    assert await check(uow) == 0


async def test_plans_that_are_off_finished_or_out_of_date_stay_quiet(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await plan(uow, user, alerts=False)
    await plan(uow, user, status=PlanStatus.TARGET)
    await plan(uow, user, valid_until=date(2026, 10, 18))
    await plan(uow, user, verdict=Verdict.EXIT)  # not a call worth following
    await price(uow, "NVDA", "2026-10-19 10:42", "124.50")
    assert await check(uow) == 0 and await sends(engine) == []


async def test_one_users_plans_and_holdings_never_alert_another(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    mine, theirs = await person(uow), await person(uow, 4343)
    await plan(uow, mine)
    await hold(uow, mine, "NVDA")
    await price(uow, "NVDA", "2026-10-19 10:42", "100", before="140")
    assert await check(uow) == 2
    assert {s["user_id"] for s in await sends(engine)} == {str(mine.id)}
    assert {str(a.user_id) for a in await kept(engine)} == {str(mine.id)}
    assert theirs.id != mine.id


async def test_a_user_without_telegram_is_not_alerted(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await person(uow)
    async with engine.begin() as db:
        await db.execute(update(users).values(telegram_chat_id=None))
    await hold(uow, user, "NVDA")
    await price(uow, "NVDA", "2026-10-19 10:42", "100", before="140")
    assert await check(uow) == 0


# --- quiet hours --------------------------------------------------------------------------


async def test_in_quiet_hours_an_alert_waits_for_the_morning_summary(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await follow(uow, user)
    await plan(uow, user)
    await price(uow, "NVDA", "2026-10-19 11:30", "124.50")
    assert await check(uow, QUIET) == 1
    assert await sends(engine) == []  # nothing queued
    (alert,) = await kept(engine)
    assert alert.kind == "plan_entry" and alert.sent_at is None
    async with uow() as tx:
        held = await tx.investments.unsent_alerts(user.id, MONDAY)
    assert [a.id for a in held] == [alert.id]
    # Asked again, it is the same alert: still one, still held.
    assert await check(uow, ny("2026-10-19 11:40")) == 0


async def test_a_stop_on_a_held_stock_goes_through_quiet_hours(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await plan(uow, user, entered_on=date(2026, 10, 16))
    await hold(uow, user, "NVDA")
    await price(uow, "NVDA", "2026-10-19 11:30", "121.50")
    assert await check(uow, QUIET) == 1
    (send,) = await sends(engine)
    assert send["urgent"] is True
    # The sender lets an urgent message through at 23:30 and holds an ordinary one.
    telegram = FakeTelegram()
    handler = build_handlers(uow, telegram, FakeRates(), lambda: QUIET)[TELEGRAM_SEND]
    assert await handler(send) is None
    assert [s.chat_id for s in telegram.sent] == [4242]
    assert isinstance(await handler({"user_id": send["user_id"], "text": "ordinary"}), Defer)
    assert len(telegram.sent) == 1


async def test_with_the_morning_summary_off_a_quiet_alert_waits_for_quiet_hours_to_end(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await notify_cases.set_market(uow(), user.id, now=QUIET, market_summary=False)
    await plan(uow, user)
    await price(uow, "NVDA", "2026-10-19 11:30", "124.50")
    assert await check(uow, QUIET) == 1
    (send,) = await sends(engine)  # queued; the sender holds it until 08:00
    assert "urgent" not in send
    telegram = FakeTelegram()
    handler = build_handlers(uow, telegram, FakeRates(), lambda: QUIET)[TELEGRAM_SEND]
    later = await handler(send)
    assert isinstance(later, Defer) and later.until == datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    assert telegram.sent == []


async def test_a_plan_alone_gets_no_summary_so_its_alert_is_queued_not_held(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    """The morning summary needs a held or watched stock; with none, holding the alert for it
    would lose it."""
    user = await person(uow)
    await plan(uow, user)
    await price(uow, "NVDA", "2026-10-19 11:30", "124.50")
    assert await check(uow, QUIET) == 1
    (send,) = await sends(engine)  # queued; the sender holds it until 08:00
    assert send["text"].startswith("🟢 NVDA dipped")
    (alert,) = await kept(engine)
    assert alert.sent_at == QUIET


async def test_quiet_hours_are_the_users_own(uow: UowFactory, engine: AsyncEngine) -> None:
    early, night = await person(uow), await person(uow, 4343)
    # 22:42 in Singapore: quiet for one who stops at 22:00, not for the default.
    await notify_cases.set_market(
        uow(),
        early.id,
        now=MON_OPEN,
        quiet_start=ny("2026-10-19 10:00").timetz().replace(tzinfo=None),
    )
    for user in (early, night):
        await hold(uow, user, "NVDA")
    await price(uow, "NVDA", "2026-10-19 10:42", "100", before="140")
    assert await check(uow) == 2
    assert {s["user_id"] for s in await sends(engine)} == {str(night.id)}
    held = {str(a.user_id) for a in await kept(engine) if a.sent_at is None}
    assert held == {str(early.id)}


async def test_no_quiet_hours_means_every_alert_goes(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await person(uow)
    await notify_cases.set_market(uow(), user.id, now=QUIET, quiet_start=time(7), quiet_end=time(7))
    await hold(uow, user, "NVDA")
    await price(uow, "NVDA", "2026-10-19 11:30", "100", before="140")
    assert await check(uow, QUIET) == 1 and len(await sends(engine)) == 1


# --- the evening follow on daily bars -----------------------------------------------------


def bar(symbol: str, day: date, close: str, low: str, high: str) -> Bar:
    return Bar(symbol, day, D(close), D(high), D(low), D(close), D(close), 1)


async def save_bar(uow: UowFactory, made: Bar) -> None:
    async with uow() as tx:
        await tx.investments.save_bars(made.symbol, [made], known=True, at=MON_OPEN)
        await tx.commit()


async def test_the_evening_follow_doesnt_say_it_again_but_keeps_the_plans_state(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    made = await plan(uow, user)
    await price(uow, "NVDA", "2026-10-19 10:42", "124.50")
    assert await check(uow) == 1
    # The day's bar confirms it: low 124.20, closing 125.40.
    await save_bar(uow, bar("NVDA", MONDAY, "125.40", "124.20", "126.00"))
    evening = ny("2026-10-19 19:00")
    assert await plan_cases.follow_plans(uow, now=evening) == 0  # told already
    after = await plan_cases.get_plan(uow(), user.id, made.id)
    assert after.entered_on == MONDAY and after.checked_through == MONDAY
    assert len(await sends(engine)) == 1 and len(await kept(engine)) == 1


async def test_the_evening_follow_doesnt_repeat_an_alert_held_for_the_morning(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await follow(uow, user)
    await plan(uow, user)
    await price(uow, "NVDA", "2026-10-19 11:30", "124.50")
    assert await check(uow, QUIET) == 1
    await save_bar(uow, bar("NVDA", MONDAY, "125.40", "124.20", "126.00"))
    assert await plan_cases.follow_plans(uow, now=ny("2026-10-19 19:00")) == 0
    assert await sends(engine) == []
    assert [a.sent_at for a in await kept(engine)] == [None]


async def test_the_follow_tells_what_the_live_price_missed(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    """A dip between two quotes shows only in the day's low: the follow tells it, and
    records it, so a later check that day doesn't."""
    user = await person(uow)
    await follow(uow, user)
    made = await plan(uow, user)
    await save_bar(uow, bar("NVDA", MONDAY, "126.50", "123.90", "127.00"))
    # 19:00 in New York is 07:00 in Singapore: quiet, and the summary is on, so it is held.
    assert await plan_cases.follow_plans(uow, now=ny("2026-10-19 19:00")) == 1
    assert await sends(engine) == []
    (held,) = await kept(engine)
    assert (held.kind, held.day, held.sent_at) == ("plan_entry", MONDAY, None)
    assert held.text.startswith("🟢 NVDA dipped into its buy zone")
    assert (await plan_cases.get_plan(uow(), user.id, made.id)).entered_on == MONDAY


async def test_the_follow_sends_as_before_outside_quiet_hours_and_with_the_summary_off(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    other = await person(uow, 4343)
    await notify_cases.set_market(uow(), other.id, now=MON_OPEN, market_summary=False)
    await follow(uow, user)
    for who in (user, other):
        await plan(uow, who)
    await save_bar(uow, bar("NVDA", MONDAY, "126.50", "123.90", "127.00"))
    # 01:00 Tuesday in Singapore is quiet: held for the one with the summary, queued
    # (and held by the sender) for the one without it.
    assert await plan_cases.follow_plans(uow, now=ny("2026-10-19 13:00")) == 2
    queued = await sends(engine)
    assert [s["user_id"] for s in queued] == [str(other.id)]
    assert queued[0]["key"].startswith("plan:") and queued[0]["key"].endswith(":entry")
    # A user outside quiet hours is queued at once (18:00 in New York is 06:00 in Singapore;
    # a later hour of the day is used for the morning).
    third = await person(uow, 4545)
    await plan(uow, third)
    assert await plan_cases.follow_plans(uow, now=ny("2026-10-19 21:00")) == 1  # 09:00 SGT
    assert {s["user_id"] for s in await sends(engine)} == {str(other.id), str(third.id)}


async def test_a_plan_that_ran_out_is_told_as_before(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await person(uow)
    await plan(uow, user, valid_until=date(2026, 10, 12))
    assert await plan_cases.follow_plans(uow, now=ny("2026-10-19 21:00")) == 1
    (send,) = await sends(engine)
    assert send["text"].startswith("📅 Your NVDA plan ran out on 12 Oct")
    assert await kept(engine) == []  # not something a live price could have said


# --- the job ------------------------------------------------------------------------------


async def test_the_quote_refresh_job_makes_the_alerts_when_it_fetched(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    fake = FakeQuotes(
        {
            "NVDA": quote("NVDA", "94", "100", MON_OPEN - timedelta(minutes=1)),
            "SPY": quote("SPY", "100", "100", MON_OPEN - timedelta(minutes=1)),
        },
        status=OPEN,
    )
    now = [MON_OPEN.astimezone(UTC)]
    handlers = build_handlers(uow, FakeTelegram(), FakeRates(), lambda: now[0], quotes=Quotes(fake))
    refresh = handlers[quote_cases.REFRESH_JOB]
    await refresh({})
    (send,) = await sends(engine)
    assert send["text"].startswith(f"📉 NVDA {MINUS}6.0% today")
    # The next run fetches again: the day's alert is still only the one.
    now[0] += timedelta(minutes=5)
    await refresh({})
    assert len(await sends(engine)) == 1


async def test_a_failing_alert_check_never_fails_the_refresh(
    uow: UowFactory, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await person(uow)
    await hold(uow, user, "NVDA")
    fake = FakeQuotes({"NVDA": quote("NVDA", "94", "100", MON_OPEN)}, status=OPEN)

    async def broken(*_: Any, **__: Any) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(alert_cases, "check", broken)
    handlers = build_handlers(
        uow, FakeTelegram(), FakeRates(), lambda: MON_OPEN.astimezone(UTC), quotes=Quotes(fake)
    )
    await handlers[quote_cases.REFRESH_JOB]({})  # no exception
    async with uow() as tx:
        assert "NVDA" in await tx.investments.quotes(["NVDA"])  # the quotes were kept


async def test_the_table_accepts_every_kind(uow: UowFactory, engine: AsyncEngine) -> None:
    user = await person(uow)
    async with uow() as tx:
        for kind in AlertKind:
            alert = MarketAlert(uuid4(), user.id, "NVDA", kind, MONDAY, "text", False, MON_OPEN)
            assert await tx.investments.insert_alert(alert)
            assert not await tx.investments.insert_alert(replace(alert, id=uuid4()))
        await tx.commit()
    assert len(await kept(engine)) == len(AlertKind)


async def test_the_sender_uses_each_users_own_quiet_hours(uow: UowFactory) -> None:
    early, night = await person(uow), await person(uow, 4343)
    await notify_cases.set_market(
        uow(), early.id, now=MON_OPEN, quiet_start=time(22), quiet_end=time(7, 30)
    )
    telegram = FakeTelegram()
    send = build_handlers(uow, telegram, FakeRates(), lambda: MON_OPEN)[TELEGRAM_SEND]
    # 22:42 in Singapore.
    waits = await send({"user_id": str(early.id), "text": "hello"})
    assert isinstance(waits, Defer)
    assert waits.until == datetime(2026, 10, 20, 7, 30, tzinfo=ZoneInfo("Asia/Singapore"))
    assert await send({"user_id": str(night.id), "text": "hello"}) is None
    assert [s.chat_id for s in telegram.sent] == [4343]
    # The ones they timed themselves, and urgent ones, go whenever.
    assert await send({"user_id": str(early.id), "text": "a", "anytime": True}) is None
    assert await send({"user_id": str(early.id), "text": "b", "urgent": True}) is None
    assert [s.text for s in telegram.sent] == ["hello", "a", "b"]


async def test_migration_0050_keeps_existing_settings_and_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    user = await person(uow)
    await notify_cases.set_frequency(uow(), user.id, Frequency.HOURLY, now=MON_OPEN)
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0049")
    async with engine.connect() as db:
        tables: set[str] = set(
            (await db.execute(text("SELECT tablename FROM pg_tables"))).scalars()
        )
        columns: set[str] = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'notification_settings'"
                    )
                )
            ).scalars()
        )
    assert "market_alerts" not in tables and "quiet_start" not in columns
    await upgrade(empty_database_url)
    # The row that was there takes the defaults: 11pm to 8am, 5%, the summary on.
    settings = await notify_cases.get_settings(uow(), user.id)
    assert settings.frequency is Frequency.HOURLY
    assert (settings.quiet_start, settings.quiet_end) == (time(23), time(8))
    assert (settings.move_alert_percent, settings.market_summary) == (D("5.0"), True)
