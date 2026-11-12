"""Departments and their runs. Pure rules, no I/O.

Nexus is a front desk (the chat agent) with departments behind it: Accounting
today, Investment and Travel next. A department whose work takes minutes runs it
as a *run*: a list of steps, each saved as it finishes, so a redeploy resumes
rather than restarts, and the user can cancel it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId

# A user can have this many runs going at once,
MAX_ACTIVE = 2
# start this many a day,
MAX_PER_DAY = 20
# and spend this much on model calls a day across their runs (US dollars).
DAILY_SPEND = Decimal("1.00")
# One step gets this long; a job has 90 seconds, so there's room to save.
STEP_TIMEOUT = timedelta(seconds=70)


@dataclass(frozen=True, slots=True)
class Department:
    """One team behind the front desk."""

    name: str  # "accounting"
    label: str  # "Accounting"
    emoji: str
    skills: tuple[str, ...]  # the chat skills it owns
    blurb: str  # one line for the web app's switcher and intro


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED = frozenset({RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED})


@dataclass(frozen=True, slots=True)
class Run:
    id: UUID
    user_id: UserId
    department: str
    kind: str
    title: str  # "Plan for NVDA"
    status: RunStatus
    task: dict[str, Any]  # what was asked, as validated by the run kind
    outputs: dict[str, Any]  # each finished step's output, by step name
    steps_done: int
    steps_total: int
    progress: str  # what it's doing now, for the user
    spent: Decimal  # model calls so far, US dollars
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None = None  # the validated result, once done
    error: str | None = None
    chat_id: int | None = None  # where the progress message is
    message_id: int | None = None
    finished_at: datetime | None = None

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


@dataclass(frozen=True, slots=True)
class Usage:
    """What a user's runs have used today."""

    active: int
    started_today: int
    spent_today: Decimal = field(default=Decimal(0))


def check_can_start(usage: Usage) -> None:
    if usage.active >= MAX_ACTIVE:
        raise InvalidInput(
            f"you already have {usage.active} jobs running; wait for one or cancel it"
        )
    if usage.started_today >= MAX_PER_DAY:
        raise InvalidInput("that's the most jobs for today; try again tomorrow")
    if usage.spent_today >= DAILY_SPEND:
        raise InvalidInput("today's research budget is used up; try again tomorrow")


def progress_text(run: Run) -> str:
    """The progress message, edited in place as the run goes."""
    if run.status is RunStatus.DONE:
        return f"✅ {run.title}: done."
    if run.status is RunStatus.CANCELLED:
        return f"⏹ {run.title}: cancelled."
    if run.status is RunStatus.FAILED:
        return f"⚠️ {run.title}: couldn't finish ({run.error or 'something went wrong'})."
    bar = f"{run.steps_done}/{run.steps_total}"
    return f"⏳ {run.title} ({bar}): {run.progress}"
