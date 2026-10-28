"""Agent mistake signals: the correction check, the safe names and error classes, the
weekly "Agent mistakes this week" problem and its one ticket. Every name is made up."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nexus.application import mistakes, ops, ops_report, ops_tickets
from nexus.domain import errors
from nexus.evals.cases import CASES
from tests.unit.test_ops_tickets import REPO, Tracker

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "no I meant 20",
        "No, it was 15",
        "No.",
        "nope",
        "actually it was 15",
        "Actually, make that lunch",
        "that's not right",
        "That’s not right",
        "thats not what I said",
        "that is not it",
        "not that one",
        "not what I asked",
        "I meant the other card",
        "wrong date",
        "  ...no wait",
    ],
)
def test_a_message_that_starts_like_a_correction_matches(text: str) -> None:
    assert mistakes.looks_like_correction(text)


@pytest.mark.parametrize(
    "text",
    [
        "now log lunch",
        "nothing else",
        "note: lunch was 12",
        "nobody paid",
        "no thanks",
        "No need, thanks",
        "log lunch, no I meant dinner",  # only the start counts
        "I think it's wrong",
        "that was great",
        "actual cost 12",
        "",
    ],
)
def test_other_messages_do_not(text: str) -> None:
    assert not mistakes.looks_like_correction(text)


def test_a_made_up_tool_name_is_kept_only_when_it_is_plain() -> None:
    assert mistakes.safe_name("Log_Expense_Placeholder") == "log_expense_placeholder"
    assert mistakes.safe_name("x" * 60) == "x" * 40
    assert mistakes.safe_name("log expense for Jamie Tan") == "other"
    assert mistakes.safe_name("log-expense") == "other"
    assert mistakes.safe_name("") == "other"


def test_only_real_tools_are_listed_and_only_a_few() -> None:
    known = {"a", "b", "c", "d", "e", "f", "g"}
    assert mistakes.tool_list(["b", "zzz", "a", "b"], known) == ["a", "b"]
    assert mistakes.tool_list(list(known), known) == ["a", "b", "c", "d", "e"]


def test_errors_are_a_class_never_a_message() -> None:
    assert mistakes.error_kind(errors.InvalidInput("amount 4,200 for Jamie")) == "InvalidInput"
    assert mistakes.error_kind(errors.NotFound("no")) == "NotFound"
    assert mistakes.error_kind(errors.DuplicateSource("email", "x", None)) == "Conflict"
    assert mistakes.error_kind(errors.Forbidden("no")) == "Forbidden"
    assert mistakes.error_kind(errors.NothingToUndo("no")) == "NothingToUndo"
    assert mistakes.error_kind(errors.NexusError("no")) == "NexusError"
    assert mistakes.error_kind(KeyError("secret")) == "KeyError"


def test_an_undo_says_how_soon_after_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[ops.Event] = []
    ops.set_sink(seen.append)
    monkeypatch.setattr(mistakes, "utcnow", lambda: NOW)
    try:
        mistakes.undo(["split_bill"], NOW - timedelta(seconds=90))
        mistakes.undo(["log_expense"], NOW - timedelta(minutes=10))
        mistakes.undo(["log_expense"], NOW + timedelta(seconds=5))  # a clock a little behind
    finally:
        ops.set_sink(None)
    soon, late, odd = seen
    assert (soon.kind, soon.name) == ("agent", "undo")
    assert soon.detail == {"tools": ["split_bill"], "seconds": 90, "quick": True}
    assert late.detail["seconds"] == 600 and late.detail["quick"] is False
    assert odd.detail["seconds"] == 0


# --- The weekly problem -----------------------------------------------------------


def sign(name: str, minutes: int = 60, user: str | None = "u1", **detail: Any) -> dict[str, Any]:
    return {
        "at": NOW - timedelta(minutes=minutes),
        "name": name,
        "ok": False,
        "trace": "t-1",
        "user_ref": user,
        "channel": "telegram",
        "detail": detail,
    }


def week() -> list[dict[str, Any]]:
    return [
        *[sign("undo", tools=["split_bill"], seconds=30, quick=True) for _ in range(6)],
        sign("undo", tools=["log_expense"], seconds=900, quick=False, user="u2"),
        *[
            sign("tool_error", tool="change_itinerary_entry", error="InvalidInput", user="u2")
            for _ in range(4)
        ],
        *[sign("correction", tools=["log_expense"]) for _ in range(3)],
        sign("unknown_tool", made_up="log_expense_stub", tool="log_expense"),
        sign("empty_reply", recovered=True),
        sign("step_limit", wrote=True, tools=["find_transactions", "log_expense"]),
    ]


def build_with(rows: list[dict[str, Any]]) -> ops_report.Report:
    checks = ops_report.Checks(now=NOW, since=NOW - timedelta(hours=72), mistakes=rows)
    return ops_report.build([], [], [], checks)


def test_signals_are_counted_per_signal_per_tool_and_per_pair() -> None:
    found = ops_report.tally(week())
    assert found.total == 17
    assert found.signals == {
        "undo": 7,
        "tool_error": 4,
        "correction": 3,
        "unknown_tool": 1,
        "empty_reply": 1,
        "step_limit": 1,
    }
    assert found.tools["split_bill"] == 6
    assert found.tools["log_expense"] == 6  # 1 undo, 3 corrections, 1 unknown, 1 step limit
    assert found.tools["change_itinerary_entry"] == 4
    assert found.quick_undos == 6
    assert found.pairs == [
        ("undo after split_bill", 6),
        ("tool_error InvalidInput on change_itinerary_entry", 4),
        ("correction after log_expense", 3),
        ("step_limit while using find_transactions", 1),
        ("step_limit while using log_expense", 1),
    ]


def test_the_top_five_pairs_break_ties_by_name() -> None:
    rows = [sign("undo", tools=[f"tool_{c}"]) for c in "dcbaef"]
    assert [p for p, _ in ops_report.tally(rows).pairs] == [
        "undo after tool_a",
        "undo after tool_b",
        "undo after tool_c",
        "undo after tool_d",
        "undo after tool_e",
    ]


def test_a_week_with_few_signals_has_nothing_to_show() -> None:
    assert build_with(week()[:4]).problems == []
    assert build_with([]).problems == []


def test_it_is_one_problem_with_a_stable_id_and_the_top_pairs() -> None:
    [problem] = build_with(week()).problems
    assert problem.id == ops_report.MISTAKES_ID == ops.fingerprint("agent-mistakes-week")
    assert (problem.severity, problem.area, problem.count) == ("medium", "agent", 17)
    assert problem.subject == "Agent mistakes this week"
    assert problem.title == "Agent mistakes this week: 17 signals"
    assert problem.users == 2 and problem.traces == [] and problem.window_hours == 168
    assert problem.detail["signals"]["undo"] == 7
    assert problem.detail["undos_within_2_minutes"] == 6
    text = "\n".join(problem.lines)
    assert "- undo after split_bill: 6" in text
    assert "- tool_error InvalidInput on change_itinerary_entry: 4" in text
    assert "- correction after log_expense: 3" in text
    # The problem's id doesn't depend on the counts.
    assert build_with(week()[:-1]).problems[0].id == problem.id


def test_it_suggests_eval_areas_from_the_top_pairs() -> None:
    [problem] = build_with(week()).problems
    text = "\n".join(problem.lines)
    assert "**Suggested eval areas**" in text
    assert "- `edit`: undo after split_bill (6)" in text
    assert (
        "- `log`: tool_error InvalidInput on change_itinerary_entry (4), correction after" in text
    )
    # A pair whose tool has no obvious area adds no suggestion.
    rows = [sign("undo", tools=["load_skill"]) for _ in range(5)]
    [other] = build_with(rows).problems
    assert "Suggested eval areas" not in "\n".join(other.lines)
    assert "- undo after load_skill: 5" in other.lines


def test_only_the_last_seven_days_count() -> None:
    old = [sign("undo", minutes=8 * 24 * 60, tools=["split_bill"]) for _ in range(10)]
    assert build_with(old).problems == []
    edge = [sign("undo", minutes=6 * 24 * 60, tools=["split_bill"]) for _ in range(5)]
    assert build_with(edge).problems[0].count == 5


def test_every_suggested_area_is_an_area_of_the_eval_set() -> None:
    areas = {case.area for case in CASES}
    assert set(ops_report.TOOL_EVAL_AREAS.values()) <= areas


def test_nothing_but_names_and_counts_reaches_the_report_or_the_ticket() -> None:
    rows = week()
    # What no signal ever holds, in case a detail grew a stray field.
    rows.append(sign("undo", tools=["split_bill"], note="Jamie Tan paid 45.50", extra="x"))
    report = build_with(rows)
    body = ops_tickets.render(report.problems[0], report, REPO)
    shown = body + ops_report.markdown(report) + json.dumps(report.as_json())
    assert "Jamie" not in shown and "45.50" not in shown
    assert "No message text, amounts or names is stored or shown here" in body
    assert "no message text, amounts, names or other user data" in body


def test_the_ticket_says_a_week_and_what_to_do() -> None:
    report = build_with(week())
    body = ops_tickets.render(report.problems[0], report, REPO)
    assert "| Seen | 17 times in the last 7 days |" in body
    assert "- undo after split_bill: 6" in body
    assert "1. Take the top pair and write a made-up eval case" in body
    assert 'says "Refs #<this issue>"' in body
    assert "Reproduce it in a test" not in body  # the usual steps are replaced
    assert f"<!-- ops-id: {ops_report.MISTAKES_ID} -->" in body
    assert "_Report window: 07 Oct 2026 12:00 UTC to 14 Oct 2026 12:00 UTC_" in body
    assert "### Agent" not in ops_report.markdown(report)
    assert "- undo after split_bill: 6" in ops_report.markdown(report)


def sync(tracker: Tracker, report: ops_report.Report) -> ops_tickets.Synced:
    return asyncio.run(ops_tickets.sync(tracker, report, REPO))


def test_the_ticket_job_opens_one_ticket_and_keeps_it_up_to_date() -> None:
    tracker = Tracker()
    first = sync(tracker, build_with(week()))
    assert len(first.opened) == 1
    [(_, (title, labels))] = tracker.calls
    assert title == "[ops] Agent mistakes this week"
    assert list(labels) == ["ops", "ops:medium", "area:agent"]

    # Nothing changed: left alone.
    tracker.calls.clear()
    assert sync(tracker, build_with(week())) == ops_tickets.Synced([], [], [], [])
    assert tracker.calls == []

    # More mistakes: the same ticket is edited, not a second one opened.
    more = [*week(), *[sign("undo", tools=["split_bill"], seconds=20, quick=True)] * 3]
    again = sync(tracker, build_with(more))
    assert again.opened == [] and len(again.updated) == 1
    assert [c[0] for c in tracker.calls] == ["edit"]
    assert len(tracker.known) == 1


def test_the_ticket_closes_when_a_week_is_quiet_and_reopens_when_it_is_not() -> None:
    tracker = Tracker()
    sync(tracker, build_with(week()))
    [ticket] = tracker.known
    tracker.calls.clear()
    closed = sync(tracker, build_with(week()[:3]))
    assert closed.closed == [ticket.number]
    comment = next(c[1][1] for c in tracker.calls if c[0] == "comment")
    assert comment.startswith("Fewer than 5 signals in the last 7 days, so closing.")

    tracker.known[0] = ops_tickets.Ticket(ticket.number, ticket.title, ticket.body, False)
    tracker.calls.clear()
    back = sync(tracker, build_with(week()))
    assert back.reopened == [ticket.number]
    comment = next(c[1][1] for c in tracker.calls if c[0] == "comment")
    assert "seen 17 times in the last 7 days" in comment
