"""Ops events and the ops report: what's recorded, that nothing anyone said is, and how
events become problems with stable ids. Every name and figure is made up."""

import asyncio
import contextvars
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from nexus.agent.ops_timing import TurnTimer
from nexus.application import ops, ops_report
from nexus.infra.http import TimedTransport
from nexus.infra.logs import JsonLines, configure_logging

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def events() -> Any:
    seen: list[ops.Event] = []
    ops.set_sink(seen.append)
    yield seen
    ops.set_sink(None)


def test_nothing_is_recorded_without_a_sink() -> None:
    ops.set_sink(None)
    ops.emit("turn", "web")  # no error, no effect


def test_an_event_carries_its_scope_and_a_hashed_user(events: list[ops.Event]) -> None:
    user = uuid4()
    with ops.scope(trace="t-1", user=user, channel="telegram"):
        ops.emit("tool", "log_expense", ms=12.7, error=None, wrote=True)
    [event] = events
    assert (event.kind, event.name, event.ok, event.ms) == ("tool", "log_expense", True, 12)
    assert event.trace == "t-1" and event.channel == "telegram"
    assert event.user == ops.user_ref(user) and len(event.user) == 10
    assert str(user) not in json.dumps(event.detail) and event.user != str(user)
    assert event.detail == {"wrote": True}  # empty details are left out
    with ops.scope():
        ops.emit("turn", "web")
    assert events[-1].user is None and events[-1].trace not in (None, "t-1")


def test_the_user_hash_depends_on_the_server_secret() -> None:
    user = uuid4()
    ops.set_salt("one")
    first = ops.user_ref(user)
    ops.set_salt("two")
    assert ops.user_ref(user) != first
    assert ops.user_ref(user) == ops.user_ref(user)


def test_a_fresh_scope_forgets_the_last_requests_user(events: list[ops.Event]) -> None:
    def request() -> None:
        ops.set_user(uuid4())
        with ops.scope(fresh=True):
            ops.emit("request", "GET /api/me")

    contextvars.copy_context().run(request)
    assert events[-1].user is None


def test_a_broken_sink_never_breaks_the_work() -> None:
    def broken(event: ops.Event) -> None:
        raise RuntimeError("database down")

    ops.set_sink(broken)
    try:
        ops.emit("turn", "web")
    finally:
        ops.set_sink(None)


def test_warnings_become_events_without_what_was_said(events: list[ops.Event]) -> None:
    # Its own logger, so handlers the app's logging setup added elsewhere don't count.
    logger = logging.getLogger("madeup.module")
    logger.propagate = False
    handler = ops.EventsFromLogs()
    logger.addHandler(handler)
    try:
        logger.info("fine")  # below a warning: not recorded
        logger.warning("couldn't read %s's receipt from %s", "Jamie Tan", "Kopi Corner")
        try:
            raise ValueError("card 4111 1111 declined")
        except ValueError:
            logger.exception("charge failed")
        handler.handle(logging.makeLogRecord({"name": ops.LOGGER, "msg": "about ops itself"}))
    finally:
        logger.removeHandler(handler)
    first, second = events
    assert first.detail["template"] == "couldn't read %s's receipt from %s"
    assert "Jamie" not in json.dumps(first.detail) and "Kopi" not in json.dumps(first.detail)
    # Outside the app's own code, a location is just the file's name.
    assert first.detail["level"] == "warning"
    assert first.detail["where"].startswith("test_ops.py:")
    assert second.detail["error"] == "ValueError" and "4111" not in json.dumps(second.detail)
    assert second.detail["fp"] == ops.fingerprint("madeup.module", "charge failed", "ValueError")
    assert second.detail["where"].startswith("test_ops.py:")


def test_code_locations_are_repository_paths() -> None:
    assert ops.where("/app/src/nexus/agent/graph.py", 9) == "src/nexus/agent/graph.py:9"
    assert ops.where("/x/.venv/lib/python3.12/site-packages/nexus/a.py", 2) == "src/nexus/a.py:2"
    assert ops.where("/usr/lib/other/thing.py", 3) == "thing.py:3"


def test_log_lines_carry_the_trace_and_uvicorn_lines_are_printed_once() -> None:
    record = logging.LogRecord("nexus.x", logging.INFO, __file__, 1, "read %d", (3,), None)
    with ops.scope(trace="abc123"):
        line = json.loads(JsonLines().format(record))
    assert line == {"level": "info", "message": "nexus.x: read 3", "trace": "abc123"}
    configure_logging()
    assert logging.getLogger("uvicorn.error").propagate is False
    assert logging.getLogger("pypdf").level == logging.ERROR
    assert any(isinstance(h, ops.EventsFromLogs) for h in logging.getLogger().handlers)


def test_model_calls_are_timed_and_fallbacks_noticed(events: list[ops.Event]) -> None:
    timer = TurnTimer("deepseek/deepseek-v4.1-flash")
    first, second = uuid4(), uuid4()

    async def turn() -> None:
        await timer.on_chat_model_start(
            {}, [[]], run_id=first, invocation_params={"model": "deepseek/deepseek-v4.1-flash"}
        )
        await timer.on_llm_error(TimeoutError(), run_id=first)
        await timer.on_chat_model_start(
            {}, [[]], run_id=second, invocation_params={"model": "anthropic/claude-haiku-5.5"}
        )
        reply = LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="Logged S$4.20 at Kopi."))]],
            llm_output={"token_usage": {"prompt_tokens": 900, "completion_tokens": 12}},
        )
        await timer.on_llm_end(reply, run_id=second)

    asyncio.run(turn())
    assert timer.failures == 1 and timer.fell_back
    failed, answered = events
    assert (failed.name, failed.ok, failed.detail["error"]) == (
        "deepseek/deepseek-v4.1-flash",
        False,
        "TimeoutError",
    )
    assert answered.detail == {"fallback": True, "tokens_in": 900, "tokens_out": 12}
    assert "Kopi" not in json.dumps([e.detail for e in events])


def test_outside_calls_record_the_host_never_the_path(events: list[ops.Event]) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429 if "busy" in request.url.path else 200)

    async def calls() -> None:
        transport = TimedTransport(httpx.MockTransport(answer))
        async with httpx.AsyncClient(transport=transport) as http:
            await http.get("https://api.telegram.org/bot123:SECRET/sendMessage?chat_id=5")
            await http.get("https://api.example.com/busy")

    asyncio.run(calls())
    ok, limited = events
    assert (ok.kind, ok.name, ok.ok, ok.detail) == (
        "http",
        "api.telegram.org",
        True,
        {"status": 200},
    )
    assert "SECRET" not in repr(ok)
    assert (limited.ok, limited.detail["error"]) == (False, "HTTP 429")


# --- The report ------------------------------------------------------------------


def ev(
    kind: str, name: str, ok: bool = True, ms: int | None = 100, **detail: Any
) -> dict[str, Any]:
    minutes = detail.pop("minutes", 30)
    return {
        "at": NOW - timedelta(minutes=minutes),
        "kind": kind,
        "name": name,
        "ok": ok,
        "ms": ms,
        "trace": detail.pop("trace", None),
        "user_ref": detail.pop("user", None),
        "channel": "telegram",
        "detail": detail,
    }


def checks(**kw: Any) -> ops_report.Checks:
    return ops_report.Checks(now=NOW, since=NOW - timedelta(hours=24), **kw)


def by_area(report: ops_report.Report) -> dict[str, list[ops_report.Problem]]:
    found: dict[str, list[ops_report.Problem]] = {}
    for p in report.problems:
        found.setdefault(p.area, []).append(p)
    return found


def test_a_quiet_day_has_no_problems() -> None:
    events = [ev("turn", "telegram", ms=3_000 + i * 100, user="u1") for i in range(12)]
    report = ops_report.build(
        events, [{"name": "GET /api/me", "calls": 40, "failures": 0}], [], checks()
    )
    assert report.problems == []
    assert report.summary["turns"]["count"] == 12 and report.summary["turns"]["users"] == 1
    assert "None." in ops_report.markdown(report)


def test_warnings_group_by_fingerprint_into_one_problem_each() -> None:
    fp = ops.fingerprint("nexus.infra.fx.frankfurter", "fx lookup %s->%s on %s failed: %s", "")
    events = [
        ev("log", "nexus.infra.fx.frankfurter", False, None, level="warning", fp=fp,
           template="fx lookup %s->%s on %s failed: %s",
           where="src/nexus/infra/fx/frankfurter.py:40",
           trace=f"job-{i}", minutes=60 - i)
        for i in range(5)
    ]  # fmt: skip
    [problem] = ops_report.build(events, [], [], checks()).problems
    assert problem.id == ops.fingerprint("log", fp)
    assert (problem.severity, problem.area, problem.count) == ("medium", "code", 5)
    assert problem.where == "src/nexus/infra/fx/frankfurter.py:40"
    assert problem.traces == ["job-4", "job-3", "job-2"]  # newest first
    again = ops_report.build(events[:2], [], [], checks()).problems[0]
    assert again.id == problem.id and again.severity == "low"  # same problem, fewer times


def test_an_error_logged_in_a_failed_tool_becomes_that_tools_problem() -> None:
    events = [
        ev("tool", "log_expense", False, 40, error="KeyError", crashed=True, trace="tg-9"),
        ev("log", "nexus.agent.graph", False, None, level="error", template="tool %s failed",
           error="KeyError", where="src/nexus/application/transactions.py:88", fp="x",
           trace="tg-9"),
    ]  # fmt: skip
    [problem] = ops_report.build(events, [], [], checks()).problems
    assert problem.title == "Tool log_expense crashed with KeyError"
    assert (
        problem.severity == "high" and problem.where == "src/nexus/application/transactions.py:88"
    )


def test_slow_turns_say_where_the_time_went() -> None:
    events = [
        ev("turn", "telegram", ms=264_000, model_ms=40_000, model_calls=2,
           tools={"log_expense": 28, "record_income": 3}, user="u1"),
        ev("turn", "telegram", ms=54_000, model_ms=53_000, model_calls=1, user="u2"),
        *[ev("turn", "web", ms=3_000) for _ in range(10)],
    ]  # fmt: skip
    found = by_area(ops_report.build(events, [], [], checks()))
    [slow] = [p for p in found["chat"] if p.id == ops.fingerprint("slow-turns")]
    assert slow.title == "2 chat replies took over 30s" and slow.users == 2
    assert slow.detail["slowest_ms"] == 264_000 and slow.detail["tools"]["log_expense"] == 28


def test_model_failures_and_fallbacks() -> None:
    events = [
        *[ev("model", "deepseek/deepseek-v4.1-flash", False, 30_000, error="TimeoutError")
          for _ in range(3)],
        *[ev("model", "deepseek/deepseek-v4.1-flash") for _ in range(7)],
        *[ev("turn", "telegram", ms=4_000, fallback=True) for _ in range(3)],
        *[ev("turn", "telegram", ms=4_000) for _ in range(7)],
    ]  # fmt: skip
    found = by_area(ops_report.build(events, [], [], checks()))
    titles = {p.title: p.severity for p in found["models"]}
    assert titles == {
        "deepseek/deepseek-v4.1-flash failed with TimeoutError": "high",
        "The fallback model answered 3 of 10 chat turns": "medium",
    }


def test_a_tool_the_model_keeps_misusing() -> None:
    events = [
        *[ev("tool", "update_trip", False, error="refused") for _ in range(5)],
        *[ev("tool", "update_trip") for _ in range(3)],
        ev("tool", "log_expense", False, error="refused"),  # once: normal
    ]
    [problem] = ops_report.build(events, [], [], checks()).problems
    assert problem.title == "Tool update_trip refused 5 of 8 calls" and problem.severity == "low"


def test_jobs_failing_stuck_and_not_running() -> None:
    events = [
        ev("job", "email.sweep", False, error="ReadTimeout", attempt=1),  # one retry: not yet
        ev("job", "photos.find", False, error="KeyError", attempt=5, final=True),
    ]
    report = ops_report.build(
        events,
        [],
        [],
        checks(
            schedules=[("budgets.sweep", timedelta(minutes=10)),
                       ("bills.sweep", timedelta(minutes=30))],
            last_done={"budgets.sweep": NOW - timedelta(minutes=5),
                       "bills.sweep": NOW - timedelta(hours=5)},
            stuck_jobs=[{"kind": "market.refresh", "attempts": 1}],
            overdue_jobs=[{"kind": "notify.sweep", "count": 4, "oldest": NOW - timedelta(hours=2)}],
        ),
    )  # fmt: skip
    titles = [p.title for p in report.problems]
    assert "Job photos.find gave up with KeyError" in titles
    assert not any("email.sweep" in t for t in titles)
    assert any(t.startswith("Scheduled job bills.sweep hasn't finished since") for t in titles)
    assert not any("budgets.sweep" in t for t in titles)
    assert "Job market.refresh is stuck running past its lease" in titles
    assert "4 notify.sweep job(s) waiting well past their time" in titles
    assert all(p.severity == "high" for p in report.problems)


def test_server_errors_outside_services_and_slow_checks() -> None:
    report = ops_report.build(
        [],
        [{"name": "POST /api/chat", "calls": 30, "failures": 2, "p90_ms": 4000}],
        [
            {"name": "api.frankfurter.app", "calls": 10, "failures": 6, "p90_ms": 9000,
             "errors": ["ReadTimeout", None]},
            {"name": "api.telegram.org", "calls": 400, "failures": 3, "p90_ms": 200, "errors": []},
        ],
        checks(
            webhook={"pending_update_count": 25, "last_error_date": int(NOW.timestamp()) - 60,
                     "last_error_message": "Wrong response from the webhook: 502 Bad Gateway"},
            openrouter={"limit_remaining": 0.4},
            broken_mailboxes=1,
            search_credits={"travel": 560, "investment": 250, "general": 120},
            search_monthly=1000,
            database_bytes=52_000_000,
        ),
    )  # fmt: skip
    found = {p.title: p for p in report.problems}
    assert found["POST /api/chat failed 2 of 30 times"].severity == "high"
    frankfurter = found["Calls to api.frankfurter.app failed 6 of 10 times"]
    assert frankfurter.severity == "high" and frankfurter.detail["errors"] == ["ReadTimeout"]
    assert not any("api.telegram.org" in t for t in found)  # under 10% failing
    assert found["25 Telegram updates are waiting to be delivered"].severity == "high"
    assert found["OpenRouter credit is low: $0.40 left"].severity == "high"
    assert "1 connected mailbox(es) stopped working" in found
    assert "Web search used 930 of 1000 credits this month" in found
    assert any(t.startswith("Telegram couldn't deliver an update") for t in found)
    text = ops_report.markdown(report)
    assert "🔴 POST /api/chat failed 2 of 30 times" in text and "Database: 52.0 MB" in text
    body = json.dumps(report.as_json())
    assert '"severity": "high"' in body


def test_problems_are_ordered_worst_first_and_ids_are_stable() -> None:
    events = [
        ev("log", "nexus.a", False, None, level="warning", template="minor", fp="f1"),
        ev("turn", "web", False, 10, error="KeyError"),
    ]
    first = ops_report.build(events, [], [], checks()).problems
    second = ops_report.build(list(reversed(events)), [], [], checks()).problems
    assert [p.severity for p in first] == ["high", "low"]
    assert [p.id for p in first] == [p.id for p in second]
