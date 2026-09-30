"""The job runner and budgets against a real Postgres."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import budgets as budget_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.categories import create_category, list_categories
from nexus.application.transactions import NewTransaction, log_transaction
from nexus.application.users import RegisterUser, register_user
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, User, UserId
from nexus.domain.money import Money
from nexus.infra.db.tables import budget_alerts, jobs
from nexus.jobs.handlers import BUDGETS_SWEEP, MEMORY_UPDATE, build_handlers
from nexus.jobs.runner import MAX_ATTEMPTS, Defer, JobRunner, Schedule
from tests.fakes import FakeRates, FakeTelegram
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

NOON_SGT = datetime(2026, 9, 28, 4, tzinfo=UTC)


@dataclass
class Clock:
    now: datetime = NOON_SGT

    def __call__(self) -> datetime:
        return self.now


async def enqueue(uow: UowFactory, kind: str, key: str, run_at: datetime, **payload: Any) -> bool:
    async with uow() as tx:
        added = await tx.jobs.enqueue(kind, payload, dedupe_key=key, run_at=run_at)
        await tx.commit()
    return added


async def job_rows(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as db:
        return list(await db.execute(select(jobs).order_by(jobs.c.id)))


# --- runner ---------------------------------------------------------------------------


async def test_two_runners_run_a_job_exactly_once(engine: AsyncEngine, uow: UowFactory) -> None:
    calls: list[dict[str, Any]] = []

    async def handler(payload: dict[str, Any]) -> None:
        calls.append(payload)
        await asyncio.sleep(0.05)  # hold the claim while the other runner looks

    clock = Clock()
    for n in range(5):
        assert await enqueue(uow, "work", f"work-{n}", clock.now, n=n)
    assert not await enqueue(uow, "work", "work-0", clock.now, n=99)  # dedupe key reused

    runners = [JobRunner(engine, {"work": handler}, clock=clock) for _ in range(2)]
    await asyncio.gather(*(r.tick() for r in runners))
    await asyncio.gather(*(r.tick() for r in runners))
    assert sorted(c["n"] for c in calls) == [0, 1, 2, 3, 4]
    assert {r.status for r in await job_rows(engine)} == {"done"}


async def test_a_private_jobs_payload_is_emptied_when_done(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    seen: list[dict[str, Any]] = []

    async def remember(payload: dict[str, Any]) -> None:
        seen.append(payload)

    async def other(payload: dict[str, Any]) -> None:
        return None

    clock = Clock()
    await enqueue(uow, MEMORY_UPDATE, "m-1", clock.now, messages=["ann is my sister"])
    await enqueue(uow, "work", "w-1", clock.now, n=1)
    await JobRunner(engine, {MEMORY_UPDATE: remember, "work": other}, clock=clock).tick()
    assert seen == [{"messages": ["ann is my sister"]}]  # the handler got the words
    rows = {r.kind: r for r in await job_rows(engine)}
    assert rows[MEMORY_UPDATE].status == "done" and rows[MEMORY_UPDATE].payload == {}
    assert rows["work"].payload == {"n": 1}  # other jobs keep theirs


async def test_two_runners_schedule_one_job_per_slot(engine: AsyncEngine) -> None:
    calls: list[datetime] = []
    clock = Clock(datetime(2026, 9, 28, 4, 3, tzinfo=UTC))

    async def sweep(_: dict[str, Any]) -> None:
        calls.append(clock.now)

    schedules = [Schedule("sweep", timedelta(minutes=10))]
    runners = [JobRunner(engine, {"sweep": sweep}, schedules=schedules, clock=clock) for _ in "ab"]
    await asyncio.gather(*(r.tick() for r in runners))
    clock.now += timedelta(minutes=5)  # same slot
    await asyncio.gather(*(r.tick() for r in runners))
    assert len(calls) == 1
    clock.now += timedelta(minutes=5)  # next slot
    await asyncio.gather(*(r.tick() for r in runners))
    assert len(calls) == 2
    assert [r.dedupe_key for r in await job_rows(engine)] == [
        "sweep@2026-09-28T04:00:00+00:00",
        "sweep@2026-09-28T04:10:00+00:00",
    ]


async def test_failures_retry_with_backoff_then_stop(engine: AsyncEngine, uow: UowFactory) -> None:
    attempts = 0

    async def flaky(_: dict[str, Any]) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("provider down")

    clock = Clock()
    runner = JobRunner(engine, {"flaky": flaky}, clock=clock)
    await enqueue(uow, "flaky", "flaky-1", clock.now)
    await runner.tick()
    (row,) = await job_rows(engine)
    assert row.status == "pending" and row.attempts == 1
    assert row.run_at == clock.now + timedelta(minutes=2)
    assert "provider down" in row.last_error
    await runner.tick()
    assert attempts == 1  # not due yet
    for _ in range(MAX_ATTEMPTS):
        clock.now += timedelta(hours=1)
        await runner.tick()
    (row,) = await job_rows(engine)
    assert attempts == MAX_ATTEMPTS and row.status == "failed"


async def test_deferral_is_not_a_failure(engine: AsyncEngine, uow: UowFactory) -> None:
    clock = Clock()
    later = clock.now + timedelta(hours=3)
    seen: list[datetime] = []

    async def wait_then_run(_: dict[str, Any]) -> Defer | None:
        seen.append(clock.now)
        return Defer(later) if clock.now < later else None

    runner = JobRunner(engine, {"w": wait_then_run}, clock=clock)
    await enqueue(uow, "w", "w-1", clock.now)
    await runner.tick()
    (row,) = await job_rows(engine)
    assert row.status == "pending" and row.attempts == 0 and row.run_at == later
    clock.now = later
    await runner.tick()
    (row,) = await job_rows(engine)
    assert row.status == "done" and len(seen) == 2


async def test_an_expired_lease_is_taken_over(engine: AsyncEngine, uow: UowFactory) -> None:
    clock = Clock()
    ran: list[str] = []
    stuck = asyncio.Event()

    async def hang(_: dict[str, Any]) -> None:
        await stuck.wait()

    async def finish(_: dict[str, Any]) -> None:
        ran.append("second runner")

    await enqueue(uow, "job", "job-1", clock.now)
    first = asyncio.create_task(JobRunner(engine, {"job": hang}, clock=clock).tick())
    await asyncio.sleep(0.1)  # first runner has claimed it and "died"
    second = JobRunner(engine, {"job": finish}, clock=clock)
    await second.tick()
    assert ran == []  # still leased
    clock.now += timedelta(minutes=6)
    await second.tick()
    assert ran == ["second runner"]
    stuck.set()
    await first  # its late finish must not overwrite the result
    (row,) = await job_rows(engine)
    assert row.status == "done"


async def test_unknown_kind_fails_without_retry(engine: AsyncEngine, uow: UowFactory) -> None:
    clock = Clock()
    await enqueue(uow, "mystery", "m-1", clock.now)
    await JobRunner(engine, {}, clock=clock).tick()
    (row,) = await job_rows(engine)
    assert row.status == "failed" and "no handler" in row.last_error


# --- budgets --------------------------------------------------------------------------


async def sgt_user(uow: UowFactory, telegram_id: int = 4242) -> User:
    registration = await register_user(
        uow(),
        RegisterUser(
            telegram_user_id=telegram_id,
            telegram_chat_id=telegram_id,
            home_currency="SGD",
            timezone="Asia/Singapore",
        ),
    )
    return registration.user


async def spend(uow: UowFactory, user: UserId, amount: str, at: datetime, **kw: Any) -> None:
    currency = kw.pop("currency", "SGD")
    await log_transaction(
        uow(), user, NewTransaction(Direction.OUT, Money.of(amount, currency), at, **kw)
    )


async def queued_texts(engine: AsyncEngine) -> list[str]:
    return [r.payload["text"] for r in await job_rows(engine) if r.kind == TELEGRAM_SEND]


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def test_alerts_fire_once_at_exact_thresholds(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await sgt_user(uow)
    rates = FakeRates()
    food = next(c for c in await list_categories(uow(), user.id) if c.name == "Dining Out")
    await budget_cases.set_budget(uow(), user, food.id, sgd("100"), now=NOON_SGT)

    async def check() -> int:
        return await budget_cases.check_budgets(uow, rates, user, now=NOON_SGT)

    await spend(uow, user.id, "49.99", NOON_SGT, category_id=food.id)
    assert await check() == 0
    await spend(uow, user.id, "0.01", NOON_SGT, category_id=food.id)  # exactly 50%
    assert await check() == 1
    assert await check() == 0  # not twice
    await spend(uow, user.id, "60", NOON_SGT, category_id=food.id)  # 110%: skips past 80
    assert await check() == 1
    texts = await queued_texts(engine)
    assert texts == [
        "You've used 50% of your Dining Out budget for September: 50.00 SGD of 100.00 SGD.",
        "You've reached your Dining Out budget for September: 110.00 SGD of 100.00 SGD (110%).",
    ]
    async with engine.connect() as db:
        recorded = [r.threshold for r in await db.execute(select(budget_alerts))]
    assert sorted(recorded) == [50, 80, 100]  # 80 recorded, never sent late


async def test_months_follow_the_users_timezone(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await sgt_user(uow)
    rates = FakeRates()
    await budget_cases.set_budget(uow(), user, None, sgd("100"), now=NOON_SGT)
    # 16:30 UTC on 30 Sep is 00:30 on 1 Oct in Singapore: October's spending.
    await spend(uow, user.id, "80", datetime(2026, 9, 30, 16, 30, tzinfo=UTC))
    september = datetime(2026, 9, 30, 15, 0, tzinfo=UTC)  # 23:00 SGT, still September
    (status,) = await budget_cases.budget_statuses(uow, rates, user, now=september)
    assert status.spent == sgd("0")
    october = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
    (status,) = await budget_cases.budget_statuses(uow, rates, user, now=october)
    assert status.spent == sgd("80") and status.percent == 80
    assert await budget_cases.check_budgets(uow, rates, user, now=october) == 1
    # A new month starts clean: alerts can fire again in November.
    await spend(uow, user.id, "60", datetime(2026, 11, 2, 4, tzinfo=UTC))
    november = datetime(2026, 11, 2, 5, tzinfo=UTC)
    assert await budget_cases.check_budgets(uow, rates, user, now=november) == 1
    assert (await queued_texts(engine))[-1].startswith(
        "You've used 50% of your overall budget for November"
    )


async def test_foreign_spending_counts_at_its_days_rate(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    rates = FakeRates({("USD", "SGD"): {datetime(2026, 9, 25).date(): "1.30"}})
    await budget_cases.set_budget(uow(), user, None, sgd("100"), now=NOON_SGT)
    await spend(uow, user.id, "50", NOON_SGT, currency="USD")  # 65.00 SGD
    await spend(uow, user.id, "10", NOON_SGT, currency="JPY")  # no rate: left out, not guessed
    (status,) = await budget_cases.budget_statuses(uow, rates, user, now=NOON_SGT)
    assert status.spent == sgd("65.00")
    assert status.unconverted == [Money.of("10", "JPY")]


async def test_setting_budgets(uow: UowFactory) -> None:
    user = await sgt_user(uow)
    other = await sgt_user(uow, 5151)
    theirs = await create_category(uow(), other.id, "Hobbies")
    with pytest.raises(NotFound):
        await budget_cases.set_budget(uow(), user, theirs.id, sgd("10"), now=NOON_SGT)
    with pytest.raises(InvalidInput, match="home currency"):
        await budget_cases.set_budget(uow(), user, None, Money.of("10", "USD"), now=NOON_SGT)
    first = await budget_cases.set_budget(uow(), user, None, sgd("500"), now=NOON_SGT)
    again = await budget_cases.set_budget(uow(), user, None, sgd("600"), now=NOON_SGT)
    assert again.id == first.id and again.limit == sgd("600")  # one overall budget
    with pytest.raises(NotFound):
        await budget_cases.remove_budget(uow(), other.id, first.id)  # not theirs
    await budget_cases.remove_budget(uow(), user.id, first.id)
    assert await budget_cases.budget_statuses(uow, FakeRates(), user, now=NOON_SGT) == []


# --- handlers ---------------------------------------------------------------------------


def handlers_for(uow: UowFactory, clock: Clock) -> tuple[FakeTelegram, Callable[..., Any]]:
    telegram = FakeTelegram()
    return telegram, lambda: build_handlers(uow, telegram, FakeRates(), clock)


async def test_sweep_sends_alerts_outside_quiet_hours(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await sgt_user(uow)
    await budget_cases.set_budget(uow(), user, None, sgd("100"), now=NOON_SGT)
    late = Clock(datetime(2026, 9, 28, 15, 0, tzinfo=UTC))  # 23:00 in Singapore
    await spend(uow, user.id, "85", late.now)
    telegram, handlers = handlers_for(uow, late)
    runner = JobRunner(
        engine, handlers(), schedules=[Schedule(BUDGETS_SWEEP, timedelta(minutes=10))], clock=late
    )
    await runner.tick()  # sweep queues the alert
    await runner.tick()  # send is due but it's quiet hours
    assert telegram.sent == []
    (send,) = [r for r in await job_rows(engine) if r.kind == TELEGRAM_SEND]
    assert send.run_at == datetime(2026, 9, 29, 0, 0, tzinfo=UTC)  # 08:00 SGT
    late.now = send.run_at
    await runner.tick()
    assert [(s.chat_id, s.text) for s in telegram.sent] == [
        (4242, "You've used 80% of your overall budget for September: 85.00 SGD of 100.00 SGD.")
    ]
