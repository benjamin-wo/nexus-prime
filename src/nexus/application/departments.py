"""The departments behind the front desk, and how their long work runs.

A department is declared once, in a registry: its name, the chat skills it owns,
and the kinds of run it can do. A run kind is a typed task, a list of steps and a
typed result. Each step runs as its own job (under the job runner's 90 seconds)
and saves its output before the next is queued, so a redeploy resumes a run
rather than restarting it. The user can cancel a run at any time; a step already
going finishes, but nothing after it starts.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from nexus.application.ports import UnitOfWork
from nexus.domain.departments import (
    STEP_TIMEOUT,
    Department,
    Run,
    RunStatus,
    check_can_start,
    progress_text,
)
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User, UserId

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

STEP_JOB = "department.step"
# A step that fails is tried this many times in all before the run gives up.
STEP_TRIES = 2
RETRY_AFTER = timedelta(minutes=1)
# How far back the runs list goes for finished runs.
RECENT = timedelta(days=7)


@dataclass(slots=True)
class StepContext:
    """What a step gets: the run so far and its user. A step reports what its model
    calls cost with ``spend``."""

    run: Run
    user: User
    now: datetime
    spent: Decimal = field(default=Decimal(0))

    @property
    def task(self) -> dict[str, Any]:
        return self.run.task

    def output(self, step: str) -> Any:
        return self.run.outputs.get(step)

    def spend(self, usd: Decimal) -> None:
        self.spent += usd


type StepFn = Callable[[StepContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    label: str  # shown while it runs: "reading the news"
    run: StepFn


@dataclass(frozen=True, slots=True)
class RunKind:
    """One kind of long work a department does. The last step's output is the
    result, and must match ``result``."""

    department: str
    name: str
    task: type[BaseModel]
    result: type[BaseModel]
    steps: Sequence[Step]
    title: Callable[[BaseModel], str]  # "Plan for NVDA"
    summary: Callable[[BaseModel], str]  # the line the user gets when it's done
    max_spend: Decimal = Decimal("0.30")


class Departments:
    """The registry. Adding a department touches nothing else."""

    def __init__(self, departments: Sequence[Department], kinds: Sequence[RunKind] = ()) -> None:
        self.departments = {d.name: d for d in departments}
        self.kinds = {k.name: k for k in kinds}
        for kind in kinds:
            if kind.department not in self.departments:
                raise ValueError(f"run kind {kind.name!r} names unknown department")
            if not kind.steps:
                raise ValueError(f"run kind {kind.name!r} has no steps")
        owners: dict[str, str] = {}
        for d in departments:
            for skill in d.skills:
                if skill in owners:
                    raise ValueError(f"skill {skill!r} belongs to {owners[skill]} and {d.name}")
                owners[skill] = d.name
        self.skill_owner: Mapping[str, str] = owners

    def kind(self, name: str) -> RunKind:
        found = self.kinds.get(name)
        if found is None:
            raise NotFound(f"no run kind called {name!r}")
        return found


ACCOUNTING = Department(
    name="accounting",
    label="Accounting",
    emoji="🧾",
    skills=(
        "expenses",
        "duplicates",
        "income",
        "bills",
        "budgets",
        "subscriptions",
        "cashflow",
        "salary",
        "automation",
        "updates",
    ),
    blurb="Spending, income, budgets, bills, subscriptions, email receipts and statements.",
)


INVESTMENT = Department(
    name="investment",
    label="Investment",
    emoji="📈",
    skills=("investments",),
    blurb="Your holdings, and research on when to buy and sell.",
)


def default_registry(kinds: Sequence[RunKind] = ()) -> Departments:
    return Departments([ACCOUNTING, INVESTMENT], kinds)


class Progress(Protocol):
    """Shows a run's progress to its user: sends one message, then edits it."""

    async def show(self, run: Run, user: User, text: str) -> tuple[int | None, int | None]:
        """Returns the (chat id, message id) the progress now lives in."""
        ...


# --- starting, cancelling, listing ---------------------------------------------------


async def start_run(
    uow: UnitOfWork,
    registry: Departments,
    user: User,
    kind_name: str,
    task: dict[str, Any],
    *,
    now: datetime,
) -> Run:
    """Check the task and the user's limits, save the run, and queue its first step."""
    kind = registry.kind(kind_name)
    try:
        checked = kind.task.model_validate(task)
    except ValidationError as exc:
        raise InvalidInput(f"that request isn't complete: {exc.errors()[0]['msg']}") from exc
    async with uow:
        check_can_start(await uow.runs.usage(user.id, now - timedelta(days=1)))
        run = Run(
            id=uuid4(),
            user_id=user.id,
            department=kind.department,
            kind=kind.name,
            title=kind.title(checked),
            status=RunStatus.QUEUED,
            task=checked.model_dump(mode="json"),
            outputs={},
            steps_done=0,
            steps_total=len(kind.steps),
            progress="starting",
            spent=Decimal(0),
            created_at=now,
            updated_at=now,
        )
        await uow.runs.insert_run(run)
        await _queue_step(uow, run, now)
        await uow.commit()
    return run


async def _queue_step(uow: UnitOfWork, run: Run, at: datetime, tries: int = 0) -> None:
    await uow.jobs.enqueue(
        STEP_JOB,
        {"user_id": str(run.user_id), "run_id": str(run.id), "tries": tries},
        dedupe_key=f"run:{run.id}:{run.steps_done}:{tries}",
        run_at=at,
    )


async def cancel_run(uow: UnitOfWork, user_id: UserId, run_id: UUID, *, now: datetime) -> Run:
    async with uow:
        run = await uow.runs.get_run(user_id, run_id, for_update=True)
        if run is None:
            raise NotFound("that job isn't in your list")
        if run.finished:
            return run
        run = replace(
            run, status=RunStatus.CANCELLED, progress="cancelled", updated_at=now, finished_at=now
        )
        await uow.runs.update_run(run)
        await uow.commit()
    return run


async def list_runs(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> list[Run]:
    """Runs going now, then the last week's finished ones, newest first."""
    async with uow:
        return await uow.runs.list_runs(user_id, since=now - RECENT, limit=20)


async def get_run(uow: UnitOfWork, user_id: UserId, run_id: UUID) -> Run:
    async with uow:
        run = await uow.runs.get_run(user_id, run_id)
    if run is None:
        raise NotFound("that job isn't in your list")
    return run


# --- running a step ---------------------------------------------------------------


async def advance(
    uow: UowFactory,
    registry: Departments,
    progress: Progress,
    user: User,
    run_id: UUID,
    *,
    now: datetime,
    tries: int = 0,
) -> Run | None:
    """Run the next step of a run, save what it found, and queue the one after.
    Does nothing for a run that's finished or cancelled."""
    async with uow() as tx:
        run = await tx.runs.get_run(user.id, run_id, for_update=True)
        if run is None or run.finished:
            return run
        kind = registry.kind(run.kind)
        step = kind.steps[run.steps_done]
        run = replace(run, status=RunStatus.RUNNING, progress=step.label, updated_at=now)
        await tx.runs.update_run(run)
        await tx.commit()
    run = await announce(uow, registry, progress, run, user)

    ctx = StepContext(run=run, user=user, now=now)
    try:
        output = await asyncio.wait_for(step.run(ctx), STEP_TIMEOUT.total_seconds())
    except Exception as exc:
        reason = "it took too long" if isinstance(exc, TimeoutError) else "a step failed"
        log.warning("department step %s/%s failed", run.kind, step.name, exc_info=True)
        return await _step_failed(uow, registry, progress, run, user, reason, ctx.spent, now, tries)

    async with uow() as tx:
        current = await tx.runs.get_run(user.id, run_id, for_update=True)
        if current is None:  # pragma: no cover - runs are never deleted
            return None
        spent = current.spent + ctx.spent
        done = current.steps_done + 1
        outputs = {**current.outputs, step.name: output}
        if current.finished:  # cancelled while the step ran: keep its work, go no further
            current = replace(current, outputs=outputs, spent=spent, steps_done=done)
            await tx.runs.update_run(current)
            await tx.commit()
            return await announce(uow, registry, progress, current, user)
        if spent > kind.max_spend:
            current = _finish(current, RunStatus.FAILED, now, error="it went over its budget")
            current = replace(current, outputs=outputs, spent=spent, steps_done=done)
        elif done < len(kind.steps):
            current = replace(
                current,
                outputs=outputs,
                spent=spent,
                steps_done=done,
                progress=kind.steps[done].label,
                updated_at=now,
            )
            await _queue_step(tx, current, now)
        else:
            current = replace(current, outputs=outputs, spent=spent, steps_done=done)
            try:
                result = kind.result.model_validate(output)
            except ValidationError:
                log.warning("department run %s gave a result that doesn't fit", run.kind)
                current = _finish(
                    current, RunStatus.FAILED, now, error="its result didn't check out"
                )
            else:
                current = replace(
                    _finish(current, RunStatus.DONE, now),
                    result=result.model_dump(mode="json"),
                )
        await tx.runs.update_run(current)
        await tx.commit()
    return await announce(uow, registry, progress, current, user)


def _finish(run: Run, status: RunStatus, now: datetime, error: str | None = None) -> Run:
    return replace(
        run, status=status, error=error, progress=status.value, updated_at=now, finished_at=now
    )


async def _step_failed(
    uow: UowFactory,
    registry: Departments,
    progress: Progress,
    run: Run,
    user: User,
    reason: str,
    spent: Decimal,
    now: datetime,
    tries: int,
) -> Run | None:
    async with uow() as tx:
        current = await tx.runs.get_run(user.id, run.id, for_update=True)
        if current is None or current.finished:
            return current
        current = replace(current, spent=current.spent + spent, updated_at=now)
        if tries + 1 < STEP_TRIES:
            current = replace(current, progress=f"{current.progress} (trying again)")
            await _queue_step(tx, current, now + RETRY_AFTER, tries + 1)
        else:
            current = _finish(current, RunStatus.FAILED, now, error=reason)
        await tx.runs.update_run(current)
        await tx.commit()
    return await announce(uow, registry, progress, current, user)


async def announce(
    uow: UowFactory, registry: Departments, progress: Progress, run: Run, user: User
) -> Run:
    """Send or edit the run's progress message, remembering where it is. A message
    that can't be shown never stops the run. A finished run's message carries its
    one-line result."""
    text = progress_text(run)
    department = registry.departments.get(run.department)
    if department is not None and department.name != ACCOUNTING.name:
        text = f"{department.emoji} {department.label}: {text}"
    if run.status is RunStatus.DONE and run.result is not None and run.kind in registry.kinds:
        kind = registry.kinds[run.kind]
        text = f"{text}\n{kind.summary(kind.result.model_validate(run.result))}"
    try:
        chat_id, message_id = await progress.show(run, user, text)
    except Exception:
        log.warning("could not show a run's progress", exc_info=True)
        return run
    if (chat_id, message_id) == (run.chat_id, run.message_id):
        return run
    async with uow() as tx:
        current = await tx.runs.get_run(user.id, run.id, for_update=True)
        if current is None:  # pragma: no cover
            return run
        current = replace(current, chat_id=chat_id, message_id=message_id)
        await tx.runs.update_run(current)
        await tx.commit()
    return replace(run, chat_id=chat_id, message_id=message_id)


def describe_runs(runs: Sequence[Run], tz: ZoneInfo) -> tuple[str, list[list[tuple[str, str]]]]:
    """ "What are you working on?": jobs going now, then the last few finished, with a
    Cancel button for each one going."""
    going = [r for r in runs if not r.finished]
    done = [r for r in runs if r.finished][:3]
    if not going and not done:
        return "Nothing's running right now. Accounting work happens as you ask.", []
    lines = []
    if going:
        lines.append("Working on:")
        lines += [f"• {r.title} ({r.steps_done}/{r.steps_total}): {r.progress}" for r in going]
    else:
        lines.append("Nothing's running right now.")
    if done:
        lines.append("Recently:")
        for r in done:
            when = (r.finished_at or r.updated_at).astimezone(tz)
            lines.append(f"• {r.title}: {r.status.value}, {when:%-d %b %H:%M}")
    cancels = [[(f"Cancel {r.title}", f"run:cancel:{r.id}")] for r in going]
    return "\n".join(lines), cancels
