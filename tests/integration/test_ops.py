"""Ops events through the real app: a chat turn leaves anonymous events, the report
groups them, and only the owner or the ops token can read it. Every name, merchant and
figure is made up."""

import json
from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import ops
from nexus.application.clock import utcnow
from nexus.infra.db.tables import ops_events
from tests.fakes import call, say
from tests.integration import test_web_api
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too


async def rows(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as db:
        found = await db.execute(select(ops_events).order_by(ops_events.c.id))
        return [dict(r._mapping) for r in found]


async def test_a_chat_turn_leaves_events_and_nothing_that_was_said(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    world.model.script += [
        call("log_expense", amount="4.20", merchant="Kopi Corner Tampines"),
        say("Logged S$4.20 at Kopi Corner Tampines."),
    ]
    response = await owner.send("POST", "/api/chat", {"message": "kopi corner tampines 4.20"})
    assert response.status_code == 200
    trace = response.headers["x-trace-id"]
    await world.app.state.ops.flush()
    found = await rows(world.engine)
    assert "Kopi" not in json.dumps(found, default=str)
    assert "4.20" not in json.dumps(found, default=str)
    kinds = {(r["kind"], r["name"]) for r in found if r["trace"] == trace}
    assert {("turn", "web"), ("tool", "log_expense"), ("request", "POST /api/chat")} <= kinds
    turn = next(r for r in found if r["kind"] == "turn")
    tool = next(r for r in found if r["kind"] == "tool")
    assert turn["user_ref"] and turn["user_ref"] == tool["user_ref"]
    assert turn["detail"]["tools"] == {"log_expense": 1} and turn["detail"]["model_calls"] == 2
    assert tool["ok"] and tool["detail"] == {"wrote": True}
    assert any(r["kind"] == "model" for r in found)


async def test_only_the_owner_or_the_ops_token_reads_the_report(world: World) -> None:
    anyone = world.browser()
    assert (await anyone.get("/api/ops/report")).status_code == 404
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    await member.login(MEMBER, invite)
    assert (await member.get("/api/ops/report")).status_code == 404

    world.model.script += [say("Hi!")]
    await owner.send("POST", "/api/chat", {"message": "hello"})
    await world.app.state.ops.flush()
    report = (await owner.get("/api/ops/report?hours=1")).json()
    assert report["summary"]["turns"]["count"] == 1
    assert report["summary"]["database_mb"] > 0
    text = (await owner.get("/api/ops/report?format=md")).text
    assert text.startswith("# Nexus ops report")

    world.app.state.settings = world.app.state.settings.model_copy(
        update={"ops_token": SecretStr("made-up-ops-token")}
    )
    script = world.browser()
    wrong = await script.get("/api/ops/report", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 404
    right = await script.get(
        "/api/ops/report", headers={"Authorization": "Bearer made-up-ops-token"}
    )
    assert right.status_code == 200 and "problems" in right.json()


async def test_a_failing_job_shows_as_a_problem(world: World, engine: AsyncEngine) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    with ops.scope(trace="job-77"):
        ops.emit("job", "photos.find", ok=False, ms=50, error="KeyError", attempt=5, final=True)
    await world.app.state.ops.flush()
    problems = (await owner.get("/api/ops/report")).json()["problems"]
    [failed] = [p for p in problems if p["area"] == "jobs" and "photos.find" in p["title"]]
    assert failed["severity"] == "high" and failed["traces"] == ["job-77"]
    assert failed["id"] == ops.fingerprint("job-failed", "photos.find", "KeyError")


async def test_old_events_are_dropped(world: World, engine: AsyncEngine) -> None:
    async with engine.begin() as db:
        await db.execute(
            insert(ops_events),
            [
                {"at": utcnow() - timedelta(days=31), "kind": "turn", "name": "web", "ok": True},
                {"at": utcnow() - timedelta(days=2), "kind": "turn", "name": "web", "ok": True},
            ],
        )
    assert await world.app.state.ops.prune() == 1
    assert len([r for r in await rows(engine) if r["kind"] == "turn"]) == 1


async def test_tickets_sync_on_demand(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_ops_tickets import Tracker

    owner = world.browser()
    await owner.login(OWNER)
    assert (await owner.send("POST", "/api/ops/tickets")).status_code == 409  # not set up

    tracker = Tracker()
    monkeypatch.setattr("nexus.jobs.ops_tickets.GitHubIssues", lambda http, repo, token: tracker)
    world.app.state.settings = world.app.state.settings.model_copy(
        update={
            "ops_github_token": SecretStr("made-up-github-token"),
            "ops_github_repo": "made-up/nexus",
        }
    )
    with ops.scope(trace="job-88"):
        ops.emit("job", "photos.find", ok=False, ms=50, error="KeyError", attempt=5, final=True)
    await world.app.state.ops.flush()
    synced = (await owner.send("POST", "/api/ops/tickets")).json()
    assert len(synced["opened"]) >= 1
    titles = [c[1][0] for c in tracker.calls if c[0] == "open"]
    assert "[ops] Job photos.find fails with KeyError" in titles
    # Run again: the same problem keeps its ticket.
    again = (await owner.send("POST", "/api/ops/tickets")).json()
    assert again["opened"] == []
