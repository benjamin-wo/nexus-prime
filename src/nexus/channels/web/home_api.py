"""Web API: departments, Home, setup and runs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter

from nexus.application import departments as department_cases
from nexus.application import home as home_cases
from nexus.application import setup as setup_cases
from nexus.channels.web.security import (
    Auth,
    Runtime,
)
from nexus.channels.web.shapes import Model
from nexus.domain.departments import Run

router = APIRouter(prefix="/api")

# --- departments and their runs --------------------------------------------------------


class DepartmentOut(Model):
    name: str
    label: str
    emoji: str
    blurb: str


@router.get("/departments")
async def list_departments(auth: Auth, web: Runtime) -> list[DepartmentOut]:
    """The teams behind the front desk, for the web app's switcher."""
    return [
        DepartmentOut(name=d.name, label=d.label, emoji=d.emoji, blurb=d.blurb)
        for d in web.departments.departments.values()
    ]


class FeedActionOut(Model):
    key: str
    label: str
    method: str
    path: str  # relative to /api
    body: dict[str, Any] | None = None  # the JSON to send with it, when the endpoint takes one


class FeedItemOut(Model):
    department: str
    kind: str
    text: str
    link: str
    urgent: bool
    # How soon it needs the user, and the list's order: "now" (urgent), "today" (about
    # something today) or "soon" (the rest). The list comes sorted by it.
    when: str
    actions: list[FeedActionOut]  # buttons that settle the item; usually none


@router.get("/home")
async def home(auth: Auth, web: Runtime) -> list[FeedItemOut]:
    """The front desk's "needs you" list across departments."""
    items = await home_cases.needs_you(web.uow, web.rates, auth.user, now=web.clock())
    return [
        FeedItemOut(
            department=i.department,
            kind=i.kind,
            text=i.text,
            link=i.link,
            urgent=i.urgent,
            when=i.when,
            actions=[
                FeedActionOut(key=a.key, label=a.label, method=a.method, path=a.path, body=a.body)
                for a in i.actions
            ],
        )
        for i in items
    ]


class SetupItemOut(Model):
    key: str
    label: str
    done: bool
    link: str  # the web page where it is done
    ask: str  # a sentence the web can send to the chat to do it there


class SetupOut(Model):
    dismissed: bool
    items: list[SetupItemOut]


@router.get("/setup")
async def setup(auth: Auth, web: Runtime) -> SetupOut:
    """Home's setup checklist: what is already set up and what isn't."""
    found = await setup_cases.checklist(web.uow(), auth.user)
    return SetupOut(
        dismissed=found.dismissed,
        items=[
            SetupItemOut(key=i.key, label=i.label, done=i.done, link=i.link, ask=i.ask)
            for i in found.items
        ],
    )


@router.post("/setup/dismiss", status_code=204)
async def dismiss_setup(auth: Auth, web: Runtime) -> None:
    """Put the checklist away. Safe to repeat."""
    await setup_cases.dismiss(web.uow(), auth.user, now=web.clock())


class RunOut(Model):
    id: UUID
    department: str
    kind: str
    title: str
    status: str
    progress: str
    steps_done: int
    steps_total: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


def _run_out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        department=run.department,
        kind=run.kind,
        title=run.title,
        status=run.status.value,
        progress=run.progress,
        steps_done=run.steps_done,
        steps_total=run.steps_total,
        result=run.result,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


@router.get("/runs")
async def list_runs(auth: Auth, web: Runtime) -> list[RunOut]:
    """Department jobs going now, then the last week's finished ones."""
    runs = await department_cases.list_runs(web.uow(), auth.user.id, now=web.clock())
    return [_run_out(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, auth: Auth, web: Runtime) -> RunOut:
    return _run_out(await department_cases.get_run(web.uow(), auth.user.id, run_id))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: UUID, auth: Auth, web: Runtime) -> RunOut:
    run = await department_cases.cancel_run(web.uow(), auth.user.id, run_id, now=web.clock())
    return _run_out(run)
