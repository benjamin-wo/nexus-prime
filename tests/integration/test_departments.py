"""Departments and their runs: a run's steps each save what they found, a run
resumes where it stopped, can be cancelled, gives up after a step fails twice or
it overspends, and only finishes with a result that checks out."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.skills import SkillLibrary
from nexus.application import departments as department_cases
from nexus.application.departments import (
    ACCOUNTING,
    Departments,
    Progress,
    RunKind,
    Step,
    StepContext,
)
from nexus.domain.departments import MAX_ACTIVE, Department, Run, RunStatus
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User
from nexus.infra.db.tables import jobs
from tests.fakes import NOW, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

LAB = Department("lab", "Lab", "🧪", (), "A department for tests.")


class Ask(BaseModel):
    ticker: str


class Answer(BaseModel):
    ticker: str
    view: str


class Shown:
    """The progress message: sent once, then edited in place."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.message_id: int | None = None

    async def show(self, run: Run, user: User, text: str) -> tuple[int | None, int | None]:
        self.texts.append(text)
        if self.message_id is None:
            self.message_id = 77
        return 4242, self.message_id


def lab(
    *steps: Callable[[StepContext], Awaitable[dict[str, Any]]], max_spend: str = "0.30"
) -> Departments:
    kind = RunKind(
        department="lab",
        name="lab.plan",
        task=Ask,
        result=Answer,
        steps=[Step(f"s{n}", f"step {n}", fn) for n, fn in enumerate(steps, 1)],
        title=lambda t: f"Plan for {t.ticker}",  # type: ignore[attr-defined]
        summary=lambda r: f"{r.ticker}: {r.view}",  # type: ignore[attr-defined]
        max_spend=Decimal(max_spend),
    )
    return Departments([ACCOUNTING, LAB], [kind])


async def gather(ctx: StepContext) -> dict[str, Any]:
    ctx.spend(Decimal("0.01"))
    return {"close": 120}


async def decide(ctx: StepContext) -> dict[str, Any]:
    ctx.spend(Decimal("0.02"))
    return {"ticker": ctx.task["ticker"], "view": f"wait for {ctx.output('s1')['close'] - 5}"}


async def queued(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as db:
        rows = await db.execute(
            select(jobs.c.dedupe_key).where(jobs.c.kind == department_cases.STEP_JOB)
        )
        return sorted(r[0].rsplit(":", 2)[1] for r in rows)  # the step each job runs


async def start(uow: UowFactory, registry: Departments, user: User) -> Run:
    return await department_cases.start_run(
        uow(), registry, user, "lab.plan", {"ticker": "NVDA"}, now=NOW
    )


async def run_all(
    uow: UowFactory, registry: Departments, user: User, run: Run, shown: Progress
) -> Run:
    current: Run | None = run
    while current is not None and not current.finished:
        current = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW)
    assert current is not None
    return current


def test_every_skill_belongs_to_one_department() -> None:
    owners = department_cases.default_registry().skill_owner
    skills = set(SkillLibrary.load().tools())
    assert skills == set(owners) and set(owners.values()) == {"accounting"}
    with pytest.raises(ValueError, match="belongs to"):
        Departments([ACCOUNTING, Department("x", "X", "x", ("budgets",), "")])


async def test_a_run_goes_step_by_step_to_a_checked_result(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    registry, shown = lab(gather, decide), Shown()
    run = await department_cases.start_run(
        uow(), registry, user, "lab.plan", {"ticker": "NVDA"}, now=NOW
    )
    assert (run.title, run.status, run.steps_total) == ("Plan for NVDA", RunStatus.QUEUED, 2)
    assert await queued(engine) == ["0"]

    after_one = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW)
    assert after_one is not None
    assert (after_one.steps_done, after_one.outputs, after_one.progress) == (
        1, {"s1": {"close": 120}}, "step 2",
    )  # fmt: skip
    assert await queued(engine) == ["0", "1"]

    done = await run_all(uow, registry, user, after_one, shown)
    assert done.status is RunStatus.DONE
    assert done.result == {"ticker": "NVDA", "view": "wait for 115"}
    assert done.spent == Decimal("0.03")
    assert (done.chat_id, done.message_id) == (4242, 77)
    assert shown.texts[0] == "🧪 Lab: ⏳ Plan for NVDA (0/2): step 1"
    assert shown.texts[-1] == "🧪 Lab: ✅ Plan for NVDA: done.\nNVDA: wait for 115"
    # Finished: running it again changes nothing.
    again = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW)
    assert again is not None and again.status is RunStatus.DONE


async def test_a_bad_task_and_the_limits_are_refused(uow: UowFactory) -> None:
    user = await person(uow)
    registry = lab(gather, decide)
    with pytest.raises(InvalidInput, match="isn't complete"):
        await department_cases.start_run(uow(), registry, user, "lab.plan", {}, now=NOW)
    with pytest.raises(NotFound):
        await department_cases.start_run(uow(), registry, user, "lab.nope", {}, now=NOW)
    for _ in range(MAX_ACTIVE):
        await department_cases.start_run(
            uow(), registry, user, "lab.plan", {"ticker": "AMD"}, now=NOW
        )
    with pytest.raises(InvalidInput, match="jobs running"):
        await department_cases.start_run(
            uow(), registry, user, "lab.plan", {"ticker": "AMD"}, now=NOW
        )


async def test_cancelling_stops_what_comes_next(uow: UowFactory) -> None:
    user = await person(uow)
    shown = Shown()

    async def cancelled_midway(ctx: StepContext) -> dict[str, Any]:
        await department_cases.cancel_run(uow(), user.id, ctx.run.id, now=NOW)
        return {"close": 120}

    registry = lab(cancelled_midway, decide)
    run = await department_cases.start_run(
        uow(), registry, user, "lab.plan", {"ticker": "NVDA"}, now=NOW
    )
    after = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW)
    assert after is not None and after.status is RunStatus.CANCELLED
    assert after.outputs == {"s1": {"close": 120}}  # the step that was going keeps its work
    assert shown.texts[-1] == "🧪 Lab: ⏹ Plan for NVDA: cancelled."
    nothing = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW)
    assert nothing is not None and nothing.steps_done == 1
    runs = await department_cases.list_runs(uow(), user.id, now=NOW)
    assert [r.status for r in runs] == [RunStatus.CANCELLED]
    with pytest.raises(NotFound):
        await department_cases.cancel_run(uow(), user.id, uuid4(), now=NOW)


async def test_a_failing_step_is_tried_twice_then_the_run_gives_up(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    shown = Shown()

    async def broken(ctx: StepContext) -> dict[str, Any]:
        raise RuntimeError("the provider is down")

    registry = lab(broken)
    run = await department_cases.start_run(
        uow(), registry, user, "lab.plan", {"ticker": "NVDA"}, now=NOW
    )
    first = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW)
    assert first is not None and first.status is RunStatus.RUNNING
    assert first.progress == "step 1 (trying again)"
    assert await queued(engine) == ["0", "0"]  # the retry, a minute later
    second = await department_cases.advance(uow, registry, shown, user, run.id, now=NOW, tries=1)
    assert second is not None
    assert (second.status, second.error) == (RunStatus.FAILED, "a step failed")
    assert shown.texts[-1] == "🧪 Lab: ⚠️ Plan for NVDA: couldn't finish (a step failed)."


async def test_overspending_or_a_bad_result_fails_the_run(uow: UowFactory) -> None:
    user = await person(uow)

    async def pricey(ctx: StepContext) -> dict[str, Any]:
        ctx.spend(Decimal("0.50"))
        return {"close": 1}

    async def nonsense(ctx: StepContext) -> dict[str, Any]:
        return {"ticker": "NVDA"}  # no view

    for steps, error in (
        ((pricey, decide), "it went over its budget"),
        ((nonsense,), "its result didn't check out"),
    ):
        registry = lab(*steps)
        run = await department_cases.start_run(
            uow(), registry, user, "lab.plan", {"ticker": "NVDA"}, now=NOW
        )
        done = await run_all(uow, registry, user, run, Shown())
        assert (done.status, done.error) == (RunStatus.FAILED, error)


async def test_the_cancel_button(uow: UowFactory) -> None:
    user = await person(uow)
    registry = lab(gather, decide)
    run = await department_cases.start_run(
        uow(), registry, user, "lab.plan", {"ticker": "NVDA"}, now=NOW
    )
    bot = build(uow, scripted())
    reply = only(await bot.press(user.id, f"run:cancel:{run.id}"))
    assert reply.text == "⏹ Cancelled Plan for NVDA. Nothing more will run."
    again = only(await bot.press(user.id, f"run:cancel:{run.id}"))
    assert again.text == "Plan for NVDA has already been cancelled."
    assert only(await bot.press(user.id, "run:cancel:nope")).text == "I don't know that button."


async def test_progress_is_one_telegram_message_edited_in_place(uow: UowFactory) -> None:
    from nexus.jobs.handlers import TelegramProgress
    from tests.fakes import FakeTelegram

    user = await person(uow)
    telegram = FakeTelegram()
    registry = lab(gather, decide)
    run = await start(uow, registry, user)
    done = await run_all(uow, registry, user, run, TelegramProgress(telegram))
    [sent] = telegram.sent
    assert sent.text == "🧪 Lab: ⏳ Plan for NVDA (0/2): step 1"
    assert [[b.label for b in row] for row in sent.buttons or []] == [["Cancel"]]
    assert done.message_id == 1001
    *_, (chat_id, message_id, text, buttons) = telegram.texts
    assert (chat_id, message_id, buttons) == (4242, 1001, [])  # no Cancel once done
    assert text == "🧪 Lab: ✅ Plan for NVDA: done.\nNVDA: wait for 115"


async def test_what_are_you_working_on(uow: UowFactory) -> None:
    from zoneinfo import ZoneInfo

    user = await person(uow)
    bot = build(uow, scripted())  # no model turn: the kernel answers
    quiet = only(await bot.handle_text(user.id, "what are you working on?", "m1"))
    assert quiet.text == "Nothing's running right now. Accounting work happens as you ask."
    registry = lab(gather, decide)
    run = await start(uow, registry, user)
    busy = only(await bot.handle_text(user.id, "anything running?", "m2"))
    assert busy.text == "Working on:\n• Plan for NVDA (0/2): starting"
    assert [[b.label for b in row] for row in busy.buttons] == [["Cancel Plan for NVDA"]]
    await department_cases.cancel_run(uow(), user.id, run.id, now=NOW)
    runs = await department_cases.list_runs(uow(), user.id, now=NOW)
    text, buttons = department_cases.describe_runs(runs, ZoneInfo("Asia/Singapore"))
    assert (
        text == "Nothing's running right now.\nRecently:\n• Plan for NVDA: cancelled, 28 Sep 12:00"
    )
    assert buttons == []
