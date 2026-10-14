"""Keeps one ticket (a GitHub issue labelled ``ops``) per problem in the ops report.

A problem's id is written into its ticket, hidden, so each run finds the ticket it
opened before:

- a new problem at or above the severity bar gets a ticket;
- a known one has its ticket brought up to date (counts, last seen, traces), quietly:
  editing a ticket notifies nobody;
- one that comes back after its ticket was closed as done reopens it, with a comment;
- an open ticket whose problem is gone from the whole window is closed, with a comment.

A ticket someone closed as "not planned" is left alone. Tickets hold only what the
report holds: names, counts, timings, error types and code locations, never user data.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from nexus.application.ops_report import RANK, Problem, Report, Severity

LABEL = "ops"
MARK = "<!-- ops-id: {} -->"
_MARK = re.compile(r"<!-- ops-id: ([0-9a-f]{6,40}) -->")


@dataclass(frozen=True, slots=True)
class Ticket:
    number: int
    title: str
    body: str
    open: bool
    not_planned: bool = False

    @property
    def problem_id(self) -> str | None:
        found = _MARK.search(self.body)
        return found.group(1) if found else None


class Tracker(Protocol):
    async def tickets(self) -> list[Ticket]: ...
    async def open_ticket(self, title: str, body: str, labels: Sequence[str]) -> int: ...
    async def edit(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        labels: Sequence[str] | None = None,
        state: str | None = None,
    ) -> None: ...
    async def comment(self, number: int, body: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Synced:
    opened: list[int]
    updated: list[int]
    reopened: list[int]
    closed: list[int]


def labels(problem: Problem) -> list[str]:
    return [LABEL, f"ops:{problem.severity}", f"area:{problem.area}"]


def title(problem: Problem) -> str:
    return f"[ops] {problem.subject}"[:200]


async def sync(
    tracker: Tracker,
    report: Report,
    repo: str,
    *,
    at_least: Severity = "medium",
) -> Synced:
    known = {t.problem_id: t for t in await tracker.tickets() if t.problem_id}
    seen = {p.id for p in report.problems}
    wanted = [p for p in report.problems if RANK[p.severity] <= RANK[at_least]]
    opened: list[int] = []
    updated: list[int] = []
    reopened: list[int] = []
    closed: list[int] = []
    for problem in wanted:
        body = render(problem, report, repo)
        ticket = known.get(problem.id)
        if ticket is None:
            opened.append(await tracker.open_ticket(title(problem), body, labels(problem)))
            continue
        if ticket.not_planned:
            continue
        if not ticket.open:
            await tracker.edit(
                ticket.number,
                title=title(problem),
                body=body,
                labels=labels(problem),
                state="open",
            )
            await tracker.comment(
                ticket.number,
                f"Back again: seen {problem.count} times in the last {_hours(report)} hours, "
                f"last at {_when(problem.last_seen)}.",
            )
            reopened.append(ticket.number)
        elif _without_times(ticket.body) != _without_times(body) or ticket.title != title(problem):
            await tracker.edit(
                ticket.number, title=title(problem), body=body, labels=labels(problem)
            )
            updated.append(ticket.number)
    for problem_id, ticket in known.items():
        if ticket.open and problem_id not in seen:
            await tracker.comment(
                ticket.number,
                f"Not seen in the last {_hours(report)} hours, so closing. It reopens if it "
                "comes back.",
            )
            await tracker.edit(ticket.number, state="closed")
            closed.append(ticket.number)
    return Synced(opened, updated, reopened, closed)


# The report's own window moves every run; a ticket isn't edited for that alone.
_WINDOW_LINE = re.compile(r"^_Report window: .*_$", re.M)


def _without_times(body: str) -> str:
    return _WINDOW_LINE.sub("", body)


def _hours(report: Report) -> int:
    return round((report.until - report.since).total_seconds() / 3600)


def _when(at: datetime | None) -> str:
    return "unknown" if at is None else f"{at:%d %b %Y %H:%M} UTC"


_CODE = re.compile(r"^(src/nexus/[\w/.-]+\.py):(\d+)$")


def code_link(where: str, repo: str) -> str:
    """A code location as a link to that line on GitHub, when it's in the app's code."""
    found = _CODE.match(where)
    if not found:
        return f"`{where}`"
    path, line = found.groups()
    return f"[`{where}`](https://github.com/{repo}/blob/main/{path}#L{line})"


def render(problem: Problem, report: Report, repo: str) -> str:
    lines = [
        f"**{problem.title}**",
        "",
        "| | |",
        "|---|---|",
        f"| Severity | {problem.severity} |",
        f"| Area | {problem.area} |",
        f"| Seen | {problem.count} times in the last {_hours(report)} hours |",
    ]
    if problem.users:
        lines.append(f"| Users affected | {problem.users} (counted by hash) |")
    if problem.first_seen:
        lines.append(f"| First seen | {_when(problem.first_seen)} |")
    if problem.last_seen:
        lines.append(f"| Last seen | {_when(problem.last_seen)} |")
    if problem.where:
        lines.append(f"| Where | {code_link(problem.where, repo)} |")
    for key, value in problem.detail.items():
        if value not in (None, {}, [], 0):
            lines.append(f"| {key.replace('_', ' ').capitalize()} | `{value}` |")
    if problem.hint:
        lines += ["", problem.hint]
    lines += ["", "### To fix", ""]
    step = 1
    if problem.where:
        lines.append(f"{step}. Start at {code_link(problem.where, repo)}.")
        step += 1
    if problem.traces:
        traces = ", ".join(f"`{t}`" for t in problem.traces)
        lines.append(
            f"{step}. Read the full log lines: Railway, nexus-app, Logs, searching for a "
            f"trace ({traces}). Every line of that update, request or job carries it."
        )
        step += 1
    lines += [
        f"{step}. Reproduce it in a test with made-up data, fix it, and open a PR that says "
        '"Fixes #<this issue>".',
        f"{step + 1}. The ops report (`GET /api/ops/report`) shows whether it has stopped; "
        "this ticket closes itself once it's gone for a whole report window.",
        "",
        f"_Report window: {_when(report.since)} to {_when(report.until)}_",
        "",
        "Opened and kept up to date by Nexus's ops job from anonymous ops events: no "
        "message text, amounts, names or other user data.",
        MARK.format(problem.id),
    ]
    return "\n".join(lines) + "\n"
