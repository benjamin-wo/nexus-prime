"""Research that knows today, and Keep fresh: a plan run reads the news and the quote
first and uses the live price, an open plan with the switch on is made again by itself when
it goes stale, and the new plan takes its place. Every ticker, price and headline here is
made up. NOW is Monday 28 September 2026, midnight in New York (UTC-4); the made-up user
lives in Singapore (UTC+8)."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import departments as department_cases
from nexus.application import plan_refresh as refresh_cases
from nexus.application import plans as plan_cases
from nexus.application import research as research_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.quotes import Quotes
from nexus.domain.departments import Run, RunStatus
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User
from nexus.domain.market import MarketStatus, PriceKind
from nexus.domain.plans import Followed, PlanStatus, SavedPlan, Verdict, plan
from nexus.evals.seed import open_plan
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import jobs, plans
from nexus.jobs.handlers import TelegramProgress, build_handlers
from nexus.jobs.runner import Defer
from tests.fakes import NOW, FakeNews, FakeQuotes, FakeRates, FakeTelegram, bar, quote
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import person
from tests.integration.test_plans import by_role, ready
from tests.integration.test_quotes import keep, ny
from tests.integration.test_research import history
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite
from tests.unit.test_plan_follow import saved

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

D = Decimal
SESSION = ny("2026-09-28 10:42")  # the market is open from 9:30
OPEN = MarketStatus(True, "regular", None, SESSION)
SHUT = MarketStatus(False, "post-market", None, NOW)


def registry_for(
    uow: UowFactory, *, news: FakeNews | None = None, quotes: FakeQuotes | None = None
) -> department_cases.Departments:
    kind = plan_cases.plan_kind(
        uow, by_role(set()), news=news, quotes=Quotes(quotes) if quotes else None
    )
    return department_cases.default_registry([kind])


async def finish_at(
    uow: UowFactory,
    registry: department_cases.Departments,
    user: User,
    run: Run,
    now: datetime,
) -> Run:
    """Take a run through its steps with ``now`` as the clock."""
    current: Run | None = run
    while current is not None and not current.finished:
        current = await department_cases.advance(uow, registry, _Silent(), user, run.id, now=now)
    assert current is not None
    return current


class _Silent:
    async def show(self, run: Run, user: User, text: str) -> tuple[int | None, int | None]:
        return None, None


async def make_plan(
    uow: UowFactory,
    user: User,
    *,
    at: datetime = NOW,
    news: FakeNews | None = None,
    quotes: FakeQuotes | None = None,
) -> SavedPlan:
    """A plan for AMD, made as the user would ask for one."""
    registry = registry_for(uow, news=news, quotes=quotes)
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=at)
    done = await finish_at(uow, registry, user, run, at)
    assert done.status is RunStatus.DONE, done.error
    return (await plan_cases.list_plans(uow(), user.id, symbol="AMD"))[0]


async def kept_fresh(uow: UowFactory, user: User) -> SavedPlan:
    made = await make_plan(uow, user)
    await plan_cases.set_keep_fresh(uow(), user.id, made.id, on=True)
    return (await plan_cases.list_plans(uow(), user.id, symbol="AMD"))[0]


async def refresh(
    uow: UowFactory, now: datetime, quotes: FakeQuotes | None = None
) -> tuple[int, department_cases.Departments]:
    registry = registry_for(uow)
    started = await refresh_cases.refresh_plans(
        uow, registry, Quotes(quotes) if quotes else None, now=now
    )
    return started, registry


async def active(uow: UowFactory, user: User) -> list[Run]:
    async with uow() as tx:
        return await tx.runs.active_runs(user.id, plan_cases.KIND)


async def plan_list(uow: UowFactory, user: User) -> list[SavedPlan]:
    return await plan_cases.list_plans(uow(), user.id, symbol="AMD")


async def add_stock(uow: UowFactory, symbol: str) -> None:
    async with uow() as tx:
        await tx.investments.save_bars(
            symbol, [bar(symbol, d, c) for d, c in history(80).items()], known=True, at=NOW
        )
        await tx.commit()


# --- research that knows today ---------------------------------------------------------------


async def test_a_plan_run_reads_the_news_and_the_quote_first_and_uses_the_live_price(
    uow: UowFactory,
) -> None:
    user = await ready(uow)  # prices to Friday 25 Sep; news fetched at midnight
    view = await research_cases.stock(uow(), user, "AMD", today=SESSION.date(), now=SESSION)
    assert view.levels is not None
    numbers = plan(view.levels, today=SESSION.date())
    assert numbers.entry_low is not None and numbers.entry_high is not None
    inside = ((numbers.entry_low + numbers.entry_high) / 2).quantize(D("0.01"))
    news = FakeNews(
        headlines={
            "AMD": [  # the first is the one `ready` stored; the second is new
                (NOW - timedelta(hours=3), "A rival opens a plant"),
                (SESSION - timedelta(minutes=20), "AMD wins a big order"),
            ]
        }
    )
    quotes = FakeQuotes(
        quotes={"AMD": quote("AMD", str(inside), "139.50", SESSION - timedelta(seconds=40))},
        status=OPEN,
    )
    registry = registry_for(uow, news=news, quotes=quotes)
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=SESSION)
    done = await finish_at(uow, registry, user, run, SESSION)
    assert done.status is RunStatus.DONE, done.error
    result = plan_cases.PlanResult.model_validate(done.result)
    # Both were asked for first: the news was hours old, and so was the (missing) quote.
    assert news.asked == ["AMD"] and quotes.asked == ["AMD"]
    assert "AMD wins a big order" in [s.headline for s in result.sources]
    # The price now is the live one, with when it was traded; the numbers are still the
    # ones worked out from the closes.
    traded = SESSION - timedelta(seconds=40)
    assert (result.price, result.price_kind, result.price_at) == (inside, PriceKind.LIVE, traded)
    assert result.close == D("139.50") and result.verdict is Verdict.WAIT
    assert (result.entry_low, result.entry_high) == (numbers.entry_low, numbers.entry_high)
    [note] = result.notes
    assert note.startswith(f"The price is already in the buy zone: {inside:,.2f} now")
    assert f"\n⚠️ {note}\n" in plan_cases.summary_line(result) + "\n"
    saved_plan = (await plan_cases.list_plans(uow(), user.id, symbol="AMD"))[0]
    assert (saved_plan.price, saved_plan.price_kind) == (inside, PriceKind.LIVE)
    assert saved_plan.price_at == traded and saved_plan.atr == result.atr and result.atr
    # In the chat's text, in the user's timezone: 10:41 in New York is 10:41pm in Singapore.
    chat = plan_cases.describe_plan(saved_plan.body, ZoneInfo(user.timezone))
    assert chat.startswith(f"Price {inside:,.2f} at 10:41pm (live)\nAMD: Wait for a dip to buy.")
    assert f"⚠️ {note}" in chat


async def test_the_analysts_are_given_the_price_now_and_the_note(uow: UowFactory) -> None:
    user = await ready(uow)
    quotes = FakeQuotes(
        quotes={"AMD": quote("AMD", "110.00", "139.50", SESSION - timedelta(seconds=5))},
        status=OPEN,
    )
    model = by_role(set())
    kind = plan_cases.plan_kind(uow, model, quotes=Quotes(quotes))
    registry = department_cases.default_registry([kind])
    run = await plan_cases.start_plan(uow, registry, user, "AMD", now=SESSION)
    done = await finish_at(uow, registry, user, run, SESSION)
    assert done.status is RunStatus.DONE, done.error
    brief = str(model.seen[0][-1].content)
    assert "Price 110.00 at 10:41pm (live)" in brief
    assert "Note: The price is already under the stop: 110.00 now, stop " in brief
    # The live price joins the figures the writers may quote.
    result = plan_cases.PlanResult.model_validate(done.result)
    assert result.price == D("110.00") and result.verdict is Verdict.WAIT


async def test_a_plan_run_falls_back_to_stored_data_when_the_sources_fail(
    uow: UowFactory,
) -> None:
    user = await ready(uow)
    news = FakeNews(failing={"AMD"})
    quotes = FakeQuotes(quotes={}, status=OPEN, failing={"AMD"})
    made = await make_plan(uow, user, at=SESSION, news=news, quotes=quotes)
    assert news.asked == ["AMD"] and quotes.asked == ["AMD"]  # both were tried
    result = plan_cases.PlanResult.model_validate(made.body)
    assert result.price_kind is PriceKind.CLOSE and result.price == result.close == D("139.50")
    assert result.price_at is None and result.notes == []
    assert [s.headline for s in result.sources] == ["A rival opens a plant"]  # the stored news
    assert (made.price, made.price_kind, made.price_at) == (D("139.50"), PriceKind.CLOSE, None)
    # Without a news or quote source at all it is the same.
    plain = await make_plan(uow, user, at=SESSION)
    assert plain.price_kind is PriceKind.CLOSE


async def test_news_is_not_read_again_within_15_minutes(uow: UowFactory) -> None:
    user = await ready(uow)  # the news was fetched at NOW
    news = FakeNews()
    await make_plan(uow, user, at=NOW + timedelta(minutes=14), news=news)
    assert news.asked == []
    await make_plan(uow, user, at=NOW + timedelta(minutes=16), news=news)
    assert news.asked == ["AMD"]


async def test_the_quote_is_asked_only_while_the_market_is_open_or_just_closed_and_stale(
    uow: UowFactory,
) -> None:
    user = await ready(uow)
    fresh = quote("AMD", "139.00", "139.50", SESSION - timedelta(seconds=30))
    quotes = FakeQuotes(quotes={"AMD": fresh}, status=OPEN)
    # A quote fetched 30 seconds ago is used as it is.
    await keep(uow, [fresh], at=SESSION - timedelta(seconds=30))
    result = plan_cases.PlanResult.model_validate(
        (await make_plan(uow, user, at=SESSION, quotes=quotes)).body
    )
    assert quotes.asked == [] and result.price_kind is PriceKind.LIVE
    # Two minutes on it is stale: asked again.
    later = SESSION + timedelta(minutes=2)
    await make_plan(uow, user, at=later, quotes=quotes)
    assert quotes.asked == ["AMD"]
    # In the 20 minutes after the close it is asked for the closing price; later it is not.
    quotes.asked.clear()
    quotes.status = MarketStatus(False, "post-market", None, ny("2026-09-28 16:10"))
    await make_plan(uow, user, at=ny("2026-09-28 16:10"), quotes=quotes)
    assert quotes.asked == ["AMD"]
    quotes.asked.clear()
    await make_plan(uow, user, at=ny("2026-09-28 16:30"), quotes=quotes)
    assert quotes.asked == []
    # Before the open there is nothing to ask for.
    await make_plan(uow, user, at=NOW, quotes=FakeQuotes(status=SHUT))


# --- what makes a kept plan go stale ---------------------------------------------------------


async def test_a_plan_is_left_alone_until_it_is_stale_or_if_keep_fresh_is_off(
    uow: UowFactory,
) -> None:
    user = await ready(uow)
    made = await make_plan(uow, user)
    assert not made.keep_fresh
    # A week old, but Keep fresh is off.
    assert (await refresh(uow, NOW + timedelta(days=8)))[0] == 0
    await plan_cases.set_keep_fresh(uow(), user.id, made.id, on=True)
    assert (await refresh(uow, NOW + timedelta(days=1)))[0] == 0
    assert await active(uow, user) == []


async def test_a_plan_a_week_old_is_made_again(uow: UowFactory) -> None:
    user = await ready(uow)
    await kept_fresh(uow, user)
    assert (await refresh(uow, NOW + timedelta(days=7) - timedelta(minutes=1)))[0] == 0
    started, _ = await refresh(uow, NOW + timedelta(days=7))
    assert started == 1
    [run] = await active(uow, user)
    assert run.task["symbol"] == "AMD" and run.task["refresh_why"] == "it was a week old"
    assert plan_cases.is_automatic(run)


async def test_a_plan_past_its_date_is_refreshed_instead_of_running_out(uow: UowFactory) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    assert old.valid_until == date(2026, 10, 12)
    later = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)  # 01:00 on the 13th in New York
    # The follow would have run it out; with Keep fresh on it leaves it open.
    assert await plan_cases.follow_plans(uow, now=later) == 0
    assert (await plan_list(uow, user))[0].status is PlanStatus.OPEN
    started, registry = await refresh(uow, later)
    assert started == 1
    [run] = await active(uow, user)
    assert run.task["refresh_why"] == "it had run out"
    await finish_at(uow, registry, user, run, later)
    new, replaced = await plan_list(uow, user)
    assert replaced.status is PlanStatus.REFRESHED and new.status is PlanStatus.OPEN
    # Turn it off and the follow runs it out as before.
    await plan_cases.set_keep_fresh(uow(), user.id, new.id, on=False)
    assert await plan_cases.follow_plans(uow, now=later + timedelta(days=15)) == 1
    assert (await plan_list(uow, user))[0].status is PlanStatus.EXPIRED


async def test_a_price_more_than_an_atr_from_the_plans_is_stale(uow: UowFactory) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    assert old.price == D("139.50") and old.atr is not None
    status = FakeQuotes(status=OPEN)
    near = (old.price + old.atr * D("0.9")).quantize(D("0.01"))
    await keep(uow, [quote("AMD", str(near), "139.50", SESSION - timedelta(minutes=1))], at=SESSION)
    assert (await refresh(uow, SESSION, status))[0] == 0
    far = (old.price - old.atr * D("2.5")).quantize(D("0.01"))
    await keep(uow, [quote("AMD", str(far), "139.50", SESSION - timedelta(minutes=1))], at=SESSION)
    assert (await refresh(uow, SESSION, status))[0] == 1
    [run] = await active(uow, user)
    assert run.task["refresh_why"].startswith("price moved ")
    assert run.task["refresh_why"].endswith(" ATR")


async def test_earnings_since_the_plan_was_made_make_it_stale(uow: UowFactory) -> None:
    user = await ready(uow)
    await kept_fresh(uow, user)
    reports = FakeNews(earnings_days={"AMD": [date(2026, 9, 30)]})
    await research_cases.refresh_news(uow, reports, now=NOW + timedelta(hours=7))
    # Not yet reported on the 30th: the day has to be past.
    assert (await refresh(uow, datetime(2026, 9, 30, 16, 0, tzinfo=UTC)))[0] == 0
    started, _ = await refresh(uow, datetime(2026, 10, 1, 6, 0, tzinfo=UTC))
    assert started == 1
    [run] = await active(uow, user)
    assert run.task["refresh_why"] == "earnings are out"


# --- the limits -----------------------------------------------------------------------------


async def test_at_most_one_automatic_run_per_plan_a_day(uow: UowFactory) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    week = NOW + timedelta(days=7)
    started, _ = await refresh(uow, week)
    assert started == 1
    [run] = await active(uow, user)
    await department_cases.cancel_run(uow(), user.id, run.id, now=week)  # it never finished
    stamped = (await plan_list(uow, user))[0]
    assert stamped.id == old.id and stamped.last_refresh_check == week
    # Still stale an hour on, but it was sent for a refresh a moment ago.
    assert (await refresh(uow, week + timedelta(hours=1)))[0] == 0
    assert (await refresh(uow, week + timedelta(hours=23, minutes=59)))[0] == 0
    assert (await refresh(uow, week + timedelta(hours=24)))[0] == 1


async def test_no_second_run_while_one_for_the_stock_is_going(uow: UowFactory) -> None:
    user = await ready(uow)
    await kept_fresh(uow, user)
    week = NOW + timedelta(days=7)
    assert (await refresh(uow, week))[0] == 1
    assert len(await active(uow, user)) == 1
    assert (await refresh(uow, week + timedelta(days=2)))[0] == 0  # still running


async def test_the_run_caps_are_respected_and_a_plan_that_couldnt_start_tries_again(
    uow: UowFactory,
) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    for symbol in ("BBB", "CCC"):
        await add_stock(uow, symbol)
    registry = registry_for(uow)
    busy = [
        await plan_cases.start_plan(uow, registry, user, s, now=NOW) for s in ("BBB", "CCC")
    ]  # two runs going: the most a user may have
    week = NOW + timedelta(days=7)
    assert (await refresh(uow, week))[0] == 0
    assert (await plan_list(uow, user))[0].last_refresh_check is None  # not used up
    await department_cases.cancel_run(uow(), user.id, busy[0].id, now=week)
    assert (await refresh(uow, week + timedelta(hours=1)))[0] == 1
    assert (await plan_list(uow, user))[0].id == old.id


async def test_at_most_ten_automatic_runs_per_user_a_day(uow: UowFactory) -> None:
    user = await person(uow)
    symbols = [f"S{i:02d}" for i in range(11)]
    for symbol in symbols:
        await add_stock(uow, symbol)
        made = saved(
            Verdict.WAIT, user_id=user.id, symbol=symbol, keep_fresh=True, created_at=NOW,
            as_of=date(2026, 9, 25), valid_until=date(2026, 10, 12), body={"atr": "1.00"},
        )  # fmt: skip
        async with uow() as tx:
            await tx.investments.insert_plan(made)
            await tx.commit()
    week = NOW + timedelta(days=7)
    total = 0
    for round_ in range(10):  # two runs at a time; cancel them to make room
        started, _ = await refresh(uow, week + timedelta(minutes=round_))
        total += started
        for run in await active(uow, user):
            await department_cases.cancel_run(uow(), user.id, run.id, now=week)
    assert total == 10
    async with uow() as tx:
        sent = [p for p in await tx.investments.plans_to_refresh() if p.last_refresh_check]
    assert len(sent) == 10
    # A day later the allowance is back.
    started, _ = await refresh(uow, week + timedelta(hours=24, minutes=1))
    assert started == 2  # the eleventh, and one more, up to the two runs a user may have


# --- the new plan takes over ------------------------------------------------------------------


async def test_a_refresh_replaces_the_old_plan_which_the_record_leaves_out(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    await plan_cases.set_alerts(uow(), user.id, old.id, on=False)
    week = NOW + timedelta(days=7)
    started, registry = await refresh(uow, week)
    assert started == 1
    [run] = await active(uow, user)
    done = await finish_at(uow, registry, user, run, week)
    assert done.status is RunStatus.DONE, done.error
    new, replaced = await plan_list(uow, user)
    assert new.refreshed_from == old.id and new.refreshed_from_at == old.created_at
    assert new.keep_fresh and not new.alerts  # as the user had them
    assert new.status is PlanStatus.OPEN and new.last_refresh_check is None
    assert replaced.id == old.id and replaced.status is PlanStatus.REFRESHED
    assert not replaced.keep_fresh
    async with engine.connect() as db:
        closed = (await db.execute(select(plans.c.closed_at).where(plans.c.id == old.id))).scalar()
    assert closed == week
    # Not scored, not counted as open, not followed.
    record, finished = await plan_cases.track_record(uow(), user.id)
    assert (record.finished, record.open, record.expired, finished) == (0, 1, 0, [])
    assert plan_cases.describe_record(record).startswith(
        "No plans have finished yet (1 still open)"
    )
    assert await plan_cases.follow_plans(uow, now=week + timedelta(days=30)) == 0
    after = await plan_list(uow, user)
    assert [p.status for p in after] == [PlanStatus.OPEN, PlanStatus.REFRESHED]
    # The new plan is not made again at once.
    assert (await refresh(uow, week + timedelta(hours=1)))[0] == 0


async def test_a_plan_that_finished_meanwhile_keeps_its_own_outcome(uow: UowFactory) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    week = NOW + timedelta(days=7)
    started, registry = await refresh(uow, week)
    assert started == 1
    [run] = await active(uow, user)
    stopped = old.stop
    assert stopped is not None
    async with uow() as tx:  # the follow ended it while the new plan was being written
        await tx.investments.save_followed(
            user.id,
            old.id,
            Followed(PlanStatus.STOPPED, None, week.date(), stopped, week.date(), None, []),
            at=week,
        )
        await tx.commit()
    await finish_at(uow, registry, user, run, week)
    new, earlier = await plan_list(uow, user)
    assert earlier.status is PlanStatus.STOPPED and new.refreshed_from == old.id


async def test_a_plan_the_user_stopped_refreshing_meanwhile_is_not_kept_fresh(
    uow: UowFactory,
) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    week = NOW + timedelta(days=7)
    started, registry = await refresh(uow, week)
    assert started == 1
    [run] = await active(uow, user)
    await plan_cases.set_keep_fresh(uow(), user.id, old.id, on=False)
    await finish_at(uow, registry, user, run, week)
    new, replaced = await plan_list(uow, user)
    assert not new.keep_fresh and replaced.status is PlanStatus.REFRESHED


async def telegram_texts(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as db:
        rows = await db.execute(
            select(jobs.c.dedupe_key, jobs.c.payload).where(jobs.c.kind == TELEGRAM_SEND)
        )
        return [dict(r.payload, key=r.dedupe_key) for r in rows]


async def test_a_refresh_that_changed_nothing_much_is_made_quietly(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await ready(uow)
    await kept_fresh(uow, user)
    week = NOW + timedelta(days=7)
    started, registry = await refresh(uow, week)
    [run] = await active(uow, user)
    await finish_at(uow, registry, user, run, week)
    assert started == 1 and len(await plan_list(uow, user)) == 2
    # No message about the plan, and none from the run either (it was silent).
    assert await telegram_texts(engine) == []


async def test_a_refresh_that_changed_the_verdict_is_told_through_the_normal_send(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user = await ready(uow)
    old = await kept_fresh(uow, user)
    assert old.verdict is Verdict.WAIT
    # Monday's close fell well below every average: no support below, so no trade.
    async with uow() as tx:
        await tx.investments.save_bars(
            "AMD", [bar("AMD", date(2026, 9, 28), "110.00")], known=True, at=NOW
        )
        await tx.commit()
    later = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)  # 14:00 in Singapore
    started, registry = await refresh(uow, later)
    assert started == 1
    [run] = await active(uow, user)
    await finish_at(uow, registry, user, run, later)
    new = (await plan_list(uow, user))[0]
    assert new.verdict is not Verdict.WAIT
    [message] = await telegram_texts(engine)
    assert message["key"] == f"plan-refresh:{new.id}" and message["buttons"] == []
    assert "urgent" not in message and "anytime" not in message
    assert message["text"].startswith("AMD plan refreshed (price moved ")
    assert " ATR): now " in message["text"] and ", was Wait. " in message["text"]
    assert "http" not in message["text"]
    # It goes through the normal send: straight away by day, held during quiet hours.
    telegram = FakeTelegram()
    payload = {k: v for k, v in message.items() if k != "key"}
    day = build_handlers(uow, telegram, FakeRates(), lambda: later)[TELEGRAM_SEND]
    assert await day(payload) is None and telegram.sent[0].text == message["text"]
    night_time = datetime(2026, 9, 29, 15, 30, tzinfo=UTC)  # 23:30 in Singapore
    night = build_handlers(uow, FakeTelegram(), FakeRates(), lambda: night_time)[TELEGRAM_SEND]
    assert isinstance(await night(payload), Defer)


async def test_an_automatic_run_shows_no_progress_but_the_users_own_run_does(
    uow: UowFactory,
) -> None:
    user = await ready(uow)
    await kept_fresh(uow, user)
    started, registry = await refresh(uow, NOW + timedelta(days=7))
    [auto] = await active(uow, user)
    telegram = FakeTelegram()
    progress = TelegramProgress(telegram)
    assert started == 1 and await progress.show(auto, user, "working") == (None, None)
    assert telegram.sent == []
    own = await plan_cases.start_plan(uow, registry, user, "AMD", now=NOW)
    chat_id, message_id = await progress.show(own, user, "working")
    assert chat_id is not None and message_id is not None and len(telegram.sent) == 1


# --- turning it on and off ---------------------------------------------------------------------


async def test_keep_fresh_is_for_the_users_own_open_plans(uow: UowFactory) -> None:
    user, other = await ready(uow), await person(uow, 5151)
    made = await make_plan(uow, user)
    with pytest.raises(NotFound):
        await plan_cases.set_keep_fresh(uow(), other.id, made.id, on=True)
    with pytest.raises(NotFound):
        await plan_cases.set_keep_fresh(uow(), user.id, uuid4(), on=True)
    assert (await plan_cases.set_keep_fresh(uow(), user.id, made.id, on=True)).keep_fresh
    assert (await plan_list(uow, user))[0].keep_fresh
    await plan_cases.set_keep_fresh(uow(), user.id, made.id, on=False)
    assert not (await plan_list(uow, user))[0].keep_fresh
    async with uow() as tx:  # a finished plan can't be kept fresh
        await tx.investments.close_refreshed(user.id, made.id, at=NOW)
        await tx.commit()
    with pytest.raises(InvalidInput, match="has finished"):
        await plan_cases.set_keep_fresh(uow(), user.id, made.id, on=True)


async def test_chat_keeps_a_plan_fresh_and_stops(uow: UowFactory) -> None:
    user = await ready(uow)
    quotes = FakeQuotes(
        quotes={"AMD": quote("AMD", "139.00", "139.50", SESSION - timedelta(seconds=5))},
        status=OPEN,
    )
    await make_plan(uow, user, at=SESSION, quotes=quotes)
    tools = build_tools(lambda _: "")
    rates = FakeRates()

    async def say(name: str, args: dict[str, Any]) -> str:
        return (await run_tool(tools[name], ToolContext(user, uow, SESSION, rates), args)).text

    assert "keep_plan_fresh" in tools and not tools["keep_plan_fresh"].confirm
    assert "has finished" not in await say("keep_plan_fresh", {"symbol": "amd"})
    assert (await plan_list(uow, user))[0].keep_fresh
    shown = await say("show_plan", {"symbol": "amd"})
    assert "Keep fresh is on" in shown
    assert "Price 139.00 at 10:41pm (live)\nAMD: Wait for a dip to buy." in shown
    off = await say("keep_plan_fresh", {"symbol": "AMD", "on": False})
    assert "won't be refreshed by itself any more" in off
    assert not (await plan_list(uow, user))[0].keep_fresh
    assert "Keep fresh is on" not in await say("show_plan", {"symbol": "amd"})
    none = await say("keep_plan_fresh", {"symbol": "TSLA"})
    assert none == "Error: there's no open plan for TSLA; ask for one first"


# --- the API ---------------------------------------------------------------------------------


async def test_the_web_api_turns_keep_fresh_on_for_the_owners_open_plans_only(
    world: World,
) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite)).status_code == 200
    web = world.app.state.web
    async with web.uow() as tx:
        me = await tx.ledger.get_user_by_telegram_id(OWNER)
    assert me is not None
    mine = open_plan(me, "AMD", "140.00", keep_fresh=False)
    done = open_plan(me, "NVDA", "130.00", keep_fresh=False)
    async with web.uow() as tx:
        await tx.investments.insert_plan(mine)
        await tx.investments.insert_plan(done)
        await tx.investments.close_refreshed(me.id, done.id, at=NOW)
        await tx.commit()
    url = f"/api/investments/plans/{mine.id}/keep-fresh"
    listed = {p["symbol"]: p for p in (await owner.get("/api/investments/plans")).json()}
    assert listed["AMD"]["keep_fresh"] is False and listed["AMD"]["refreshed_from"] is None
    assert listed["NVDA"]["status"] == "refreshed"
    assert (listed["AMD"]["price"], listed["AMD"]["price_at"], listed["AMD"]["price_kind"]) == (
        None, None, None,
    )  # fmt: skip
    # Another user's plan is not found, not forbidden; nor is something that isn't a plan.
    assert (await member.send("PUT", url, {"on": True})).status_code == 404
    assert (
        await owner.send("PUT", "/api/investments/plans/nope/keep-fresh", {"on": True})
    ).status_code == 404
    assert (
        await owner.send("PUT", f"/api/investments/plans/{uuid4()}/keep-fresh", {"on": True})
    ).status_code == 404
    assert (await owner.send("PUT", url, {"on": "maybe"})).status_code == 422
    assert (await owner.send("PUT", url, {"on": True})).status_code == 204
    brief = (await owner.get(f"/api/investments/plans/{mine.id}")).json()["brief"]
    assert brief["keep_fresh"] is True
    assert (await owner.send("PUT", url, {"on": False})).status_code == 204
    assert (await owner.get(f"/api/investments/plans/{mine.id}")).json()["brief"][
        "keep_fresh"
    ] is False
    # A plan that has finished can't be kept fresh.
    closed = await owner.send("PUT", f"/api/investments/plans/{done.id}/keep-fresh", {"on": True})
    assert closed.status_code == 422 and "has finished" in closed.json()["detail"]
    assert (await member.get(f"/api/investments/plans/{mine.id}")).status_code == 404


async def test_a_plan_carries_its_price_and_the_plan_it_replaced_through_the_api(
    world: World,
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    web = world.app.state.web
    async with web.uow() as tx:
        me = await tx.ledger.get_user_by_telegram_id(OWNER)
    assert me is not None
    first = open_plan(me, "AMD", "140.00", keep_fresh=True)
    traded = datetime(2026, 10, 5, 14, 41, tzinfo=UTC)
    second = replace(
        open_plan(me, "AMD", "140.00", keep_fresh=True),
        refreshed_from=first.id,
        created_at=first.created_at + timedelta(days=10),
        price=D("138.25"),
        price_at=traded,
        price_kind=PriceKind.LIVE,
    )
    async with web.uow() as tx:
        await tx.investments.insert_plan(first)
        await tx.investments.insert_plan(second)
        await tx.investments.close_refreshed(me.id, first.id, at=NOW)
        await tx.commit()
    listed = (await owner.get("/api/investments/plans")).json()
    assert [p["id"] for p in listed] == [str(second.id), str(first.id)]
    newest, replaced = listed
    assert (newest["price"], newest["price_kind"], newest["keep_fresh"]) == ("138.25", "live", True)
    assert datetime.fromisoformat(newest["price_at"]) == traded
    assert newest["refreshed_from"]["id"] == str(first.id)
    assert datetime.fromisoformat(newest["refreshed_from"]["created_at"]) == first.created_at
    assert replaced["status"] == "refreshed" and replaced["refreshed_from"] is None
    assert replaced["keep_fresh"] is False and replaced["followed"] is True
    detail = (await owner.get(f"/api/investments/plans/{second.id}")).json()
    assert detail["brief"]["refreshed_from"] == newest["refreshed_from"]
    assert detail["brief"]["price"] == "138.25"
    # The stock page's latest plan carries them too.
    page = (await owner.get("/api/investments/stocks/AMD")).json()
    assert page["plan"]["id"] == str(second.id) and page["plan"]["price_kind"] == "live"


# --- news every hour in the session -------------------------------------------------------------


async def test_news_is_due_hourly_in_the_session_and_every_six_hours_outside_it(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    for symbol in ("AMD", "NVDA"):
        await research_cases.watch(uow(), user.id, symbol, now=NOW)
    news = FakeNews()
    first = SESSION - timedelta(hours=7)
    await research_cases.refresh_news(uow, news, now=first)  # both fetched, 3:42 in New York
    assert sorted(news.asked) == ["AMD", "NVDA"]
    news.asked.clear()
    # In the session: an hour on, fetched again; half an hour on, not.
    opened = ny("2026-09-28 09:35")
    await research_cases.refresh_news(
        uow, news, now=opened, status=MarketStatus(True, "regular", None, opened)
    )
    assert sorted(news.asked) == ["AMD", "NVDA"]
    news.asked.clear()
    await research_cases.refresh_news(
        uow,
        news,
        now=opened + timedelta(minutes=30),
        status=MarketStatus(True, "regular", None, opened),
    )
    assert news.asked == []
    # The hourly job doesn't start on the same second: a minute short still counts.
    await research_cases.refresh_news(
        uow,
        news,
        now=opened + timedelta(minutes=59),
        status=MarketStatus(True, "regular", None, opened),
    )
    assert sorted(news.asked) == ["AMD", "NVDA"]
    news.asked.clear()
    # After the close it is six hours: an hour on is not enough, six is.
    after = ny("2026-09-28 16:30")
    shut = MarketStatus(False, "post-market", None, after)
    last = opened + timedelta(minutes=59)  # 10:34, the last fetch
    await research_cases.refresh_news(uow, news, now=last + timedelta(hours=2), status=shut)
    assert news.asked == []
    await research_cases.refresh_news(uow, news, now=last + timedelta(hours=6), status=shut)
    assert sorted(news.asked) == ["AMD", "NVDA"]


async def test_hourly_news_keeps_the_cap_and_the_longest_waiting_come_first(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await person(uow)
    for symbol in ("AMD", "NVDA", "TSLA"):
        await research_cases.watch(uow(), user.id, symbol, now=NOW)
    opened = ny("2026-09-28 10:00")
    status = MarketStatus(True, "regular", None, opened)
    async with uow() as tx:  # fetched 3, 2 and 1 hours ago (AMD, TSLA, NVDA); the cap is two
        for symbol, hours in (("AMD", 3), ("TSLA", 2), ("NVDA", 1)):
            await tx.investments.save_news(symbol, [], [], at=opened - timedelta(hours=hours))
        await tx.commit()
    monkeypatch.setattr(research_cases, "MAX_PER_REFRESH", 2)
    news = FakeNews()
    assert await research_cases.refresh_news(uow, news, now=opened, status=status) == 2
    assert news.asked == ["AMD", "TSLA"]  # not the first two by name

    # The 429 still stops the run.
    class Limited(FakeNews):
        async def news(self, symbol: str, start: date, end: date) -> Any:
            raise research_cases.NewsRateLimited("HTTP 429")

    assert (
        await research_cases.refresh_news(
            uow, Limited(), now=opened + timedelta(hours=1), status=status
        )
        == 0
    )


# --- the migration --------------------------------------------------------------------------------


async def test_the_database_keeps_a_link_to_the_same_users_plan(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    user, other = await person(uow), await person(uow, 5151)
    first = saved(Verdict.WAIT, user_id=user.id)
    async with uow() as tx:
        await tx.investments.insert_plan(first)
        await tx.commit()
    with pytest.raises(IntegrityError):  # another user's plan can't be what a plan replaced
        async with uow() as tx:
            await tx.investments.insert_plan(
                saved(Verdict.WAIT, user_id=other.id, refreshed_from=first.id)
            )
            await tx.commit()
    second = saved(Verdict.WAIT, user_id=user.id, refreshed_from=first.id)
    async with uow() as tx:
        await tx.investments.insert_plan(second)
        await tx.commit()
    async with engine.begin() as db:  # deleting the old plan only unlinks the new one
        await db.execute(delete(plans).where(plans.c.id == first.id))
    [left] = await plan_cases.list_plans(uow(), user.id)
    assert left.id == second.id and left.refreshed_from is None and left.user_id == user.id


async def test_migration_0051_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    user = await person(uow)
    kept = saved(Verdict.WAIT, user_id=user.id, keep_fresh=True, price=D("139.50"))
    replaced = saved(
        Verdict.WAIT, user_id=user.id, status=PlanStatus.REFRESHED, refreshed_from=kept.id
    )
    async with uow() as tx:
        await tx.investments.insert_plan(kept)
        await tx.investments.insert_plan(replaced)
        await tx.commit()
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0050")
    async with engine.connect() as db:
        columns: set[str] = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'plans'"
                    )
                )
            ).scalars()
        )
        left = (await db.execute(select(plans.c.id, plans.c.status))).all()
    assert columns.isdisjoint(
        {"keep_fresh", "refreshed_from", "last_refresh_check", "price", "price_at", "price_kind"}
    )
    # A plan its refresh replaced goes back to being one that ran out.
    assert {(r.id, r.status) for r in left} == {(kept.id, "open"), (replaced.id, "expired")}
    await upgrade(empty_database_url)
    async with engine.connect() as db:
        rows = (
            await db.execute(
                select(
                    plans.c.id,
                    plans.c.keep_fresh,
                    plans.c.refreshed_from,
                    plans.c.price,
                    plans.c.alerts,
                )
            )
        ).all()
    # What was there takes the defaults: not kept fresh, no link, no price, alerts as they were.
    assert {(r.keep_fresh, r.refreshed_from, r.price, r.alerts) for r in rows} == {
        (False, None, None, True)
    }
    async with uow() as tx:  # the new status is accepted again
        await tx.investments.close_refreshed(user.id, kept.id, at=NOW)
        await tx.commit()
    assert (await plan_cases.get_plan(uow(), user.id, kept.id)).status is PlanStatus.REFRESHED
