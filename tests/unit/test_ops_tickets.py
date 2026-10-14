"""Ops tickets: one GitHub issue per problem, opened, kept up to date, reopened when a
problem comes back and closed when it's gone. Every name and figure is made up."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from nexus.application import ops_tickets
from nexus.application.ops_report import Problem, Report
from nexus.application.ops_tickets import Ticket
from nexus.infra.github_issues import GitHubIssues

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
REPO = "made-up/nexus"


def problem(pid: str, severity: str = "high", **kw: Any) -> Problem:
    base: dict[str, Any] = {
        "id": pid,
        "severity": severity,
        "area": "tools",
        "title": f"Tool update_trip crashed with KeyError ({pid})",
        "topic": f"Tool update_trip crashes with KeyError ({pid})",
        "count": 3,
        "first_seen": NOW - timedelta(hours=5),
        "last_seen": NOW - timedelta(hours=1),
        "where": "src/nexus/application/trips.py:212",
        "users": 2,
        "traces": ["tg-41", "tg-40"],
        "hint": "The traces find the error.",
    }
    base.update(kw)
    return Problem(**base)


def report(*problems: Problem, now: datetime = NOW) -> Report:
    return Report(now - timedelta(hours=72), now, {}, list(problems))


@dataclass
class Tracker:
    known: list[Ticket] = field(default_factory=list)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    async def tickets(self) -> list[Ticket]:
        return list(self.known)

    async def open_ticket(self, title: str, body: str, labels: Sequence[str]) -> int:
        number = 100 + len(self.calls)
        self.calls.append(("open", (title, labels)))
        self.known.append(Ticket(number, title, body, True))
        return number

    async def edit(self, number: int, **change: Any) -> None:
        self.calls.append(("edit", (number, sorted(k for k, v in change.items() if v))))

    async def comment(self, number: int, body: str) -> None:
        self.calls.append(("comment", (number, body)))


def run(tracker: Tracker, built: Report, **kw: Any) -> ops_tickets.Synced:
    return asyncio.run(ops_tickets.sync(tracker, built, REPO, **kw))


def test_new_problems_open_tickets_at_or_above_the_bar() -> None:
    tracker = Tracker()
    synced = run(tracker, report(problem("aaaaaa1"), problem("bbbbbb2", "medium"),
                                 problem("cccccc3", "low")))  # fmt: skip
    assert len(synced.opened) == 2
    [first, _] = [c for c in tracker.calls if c[0] == "open"]
    assert first[1] == (
        "[ops] Tool update_trip crashes with KeyError (aaaaaa1)",
        ["ops", "ops:high", "area:tools"],
    )
    assert run(Tracker(), report(problem("cccccc3", "low")), at_least="low").opened


def test_a_ticket_says_where_to_look_and_carries_its_problems_id() -> None:
    body = ops_tickets.render(problem("aaaaaa1"), report(), REPO)
    assert (
        "[`src/nexus/application/trips.py:212`]"
        "(https://github.com/made-up/nexus/blob/main/src/nexus/application/trips.py#L212)"
    ) in body
    assert "`tg-41`, `tg-40`" in body and "Fixes #<this issue>" in body
    assert "<!-- ops-id: aaaaaa1 -->" in body
    assert Ticket(1, "t", body, True).problem_id == "aaaaaa1"
    assert ops_tickets.code_link("thing.py:3", REPO) == "`thing.py:3`"


def test_a_known_problem_is_updated_only_when_something_changed() -> None:
    p = problem("aaaaaa1")
    body = ops_tickets.render(p, report(), REPO)
    tracker = Tracker([Ticket(7, ops_tickets.title(p), body, True)])
    # The window moved on, nothing else did: no edit.
    assert run(tracker, report(p, now=NOW + timedelta(hours=6))).updated == []
    synced = run(tracker, report(replace(p, count=9), now=NOW + timedelta(hours=6)))
    assert synced.updated == [7] and synced.opened == []
    assert tracker.calls == [("edit", (7, ["body", "labels", "title"]))]


def test_a_problem_that_comes_back_reopens_its_ticket() -> None:
    p = problem("aaaaaa1")
    old = Ticket(7, ops_tickets.title(p), ops_tickets.render(p, report(), REPO), False)
    tracker = Tracker([old])
    assert run(tracker, report(p)).reopened == [7]
    assert ("edit", (7, ["body", "labels", "state", "title"])) in tracker.calls
    [(_, (number, text))] = [c for c in tracker.calls if c[0] == "comment"]
    assert number == 7 and text.startswith("Back again: seen 3 times in the last 72 hours")


def test_a_ticket_closed_as_not_planned_stays_closed() -> None:
    p = problem("aaaaaa1")
    body = ops_tickets.render(p, report(), REPO)
    tracker = Tracker([Ticket(7, "t", body, False, not_planned=True)])
    synced = run(tracker, report(p))
    assert synced == ops_tickets.Synced([], [], [], []) and tracker.calls == []


def test_a_problem_gone_from_the_window_closes_its_ticket() -> None:
    gone = problem("aaaaaa1")
    low_now = problem("bbbbbb2", "low")  # still seen, below the bar: stays open
    tracker = Tracker(
        [
            Ticket(7, "t", ops_tickets.render(gone, report(), REPO), True),
            Ticket(8, "t", ops_tickets.render(low_now, report(), REPO), True),
            Ticket(9, "someone's own ops note", "no marker", True),
        ]
    )
    synced = run(tracker, report(low_now))
    assert synced.closed == [7]
    assert ("edit", (7, ["state"])) in tracker.calls
    assert any(c[0] == "comment" and c[1][1].startswith("Not seen in the last 72 hours")
               for c in tracker.calls)  # fmt: skip


def test_the_github_client_reads_and_writes_issues() -> None:
    seen: list[httpx.Request] = []

    def github(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            page = int(request.url.params["page"])
            items = [
                {"number": n, "title": f"#{n}", "body": f"<!-- ops-id: {n:06x}a -->",
                 "state": "open", "state_reason": None}
                for n in range(1, 101)
            ] if page == 1 else [
                {"number": 200, "title": "pr", "body": "", "state": "open", "pull_request": {}},
                {"number": 201, "title": "done", "body": "", "state": "closed",
                 "state_reason": "not_planned"},
            ]  # fmt: skip
            return httpx.Response(200, json=items)
        if request.url.path.endswith("/issues"):
            return httpx.Response(201, json={"number": 300})
        return httpx.Response(200, json={})

    async def calls() -> tuple[list[Ticket], int]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(github)) as http:
            issues = GitHubIssues(http, REPO, "made-up-token")
            found = await issues.tickets()
            number = await issues.open_ticket("[ops] x", "body", ["ops", "ops:high"])
            await issues.edit(number, state="closed")
            await issues.comment(number, "gone")
            return found, number

    found, number = asyncio.run(calls())
    assert len(found) == 101 and found[-1].not_planned and number == 300
    assert all(t.number != 200 for t in found)  # pull requests aren't tickets
    assert seen[0].headers["authorization"] == "Bearer made-up-token"
    assert seen[0].url.params["labels"] == "ops" and seen[0].url.params["state"] == "all"
    opened, closed, commented = seen[2:]
    assert json.loads(opened.content)["labels"] == ["ops", "ops:high"]
    assert json.loads(closed.content) == {"state": "closed", "state_reason": "completed"}
    assert commented.url.path == "/repos/made-up/nexus/issues/300/comments"
