"""The view figures (ADR 0005): precision, recall, exact set, silence, over-surfacing,
carry-over and the distractor run, and the cases they are read from."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from nexus.agent.views import ViewKind
from nexus.evals import compare, view_cases, view_metrics
from nexus.evals.view_metrics import TurnViews, by_round, score, spread

OUTLOOK = "finance.month_outlook"
BUDGETS = "finance.budgets"
TRIP = "travel.trip_budget"


def turn(
    expected: set[str] | None, actual: set[str], *, round_no: int = 1, **kw: bool
) -> TurnViews:
    return TurnViews(
        None if expected is None else frozenset(expected),
        frozenset(actual),
        round_no=round_no,
        **kw,
    )


def test_precision_recall_and_exact_set() -> None:
    scores = score(
        [
            turn({OUTLOOK}, {OUTLOOK}),
            turn({BUDGETS, TRIP}, {BUDGETS}),  # missed one
            turn({OUTLOOK}, {OUTLOOK, TRIP}),  # opened one too many
        ]
    )
    assert scores.precision == pytest.approx(3 / 4)
    assert scores.recall == pytest.approx(3 / 4)
    assert scores.f1 == pytest.approx(3 / 4)
    assert scores.exact == pytest.approx(1 / 3)
    assert scores.over == pytest.approx(1 / 3)
    assert scores.under == pytest.approx(1 / 3)
    assert scores.scored == 3


def test_macro_figures_average_over_the_kinds() -> None:
    scores = score([turn({OUTLOOK}, {OUTLOOK}), turn({BUDGETS}, {OUTLOOK})])
    # outlook: precision 1/2, recall 1; budgets: precision 0, recall 0.
    assert scores.macro_precision == pytest.approx(0.25)
    assert scores.macro_recall == pytest.approx(0.5)


def test_correct_silence_counts_only_turns_that_should_open_nothing() -> None:
    scores = score([turn(set(), set()), turn(set(), {OUTLOOK}), turn({OUTLOOK}, {OUTLOOK})])
    assert scores.silence == pytest.approx(0.5)
    assert scores.silent == 2


def test_an_unscored_turn_is_left_out() -> None:
    scores = score([turn(None, {OUTLOOK}), turn({OUTLOOK}, {OUTLOOK})])
    assert scores.scored == 1 and scores.precision == 1.0 and scores.over == 0.0
    assert not view_metrics.counted([turn(None, set())])


def test_a_figure_with_nothing_to_count_is_none() -> None:
    scores = score([turn({OUTLOOK}, {OUTLOOK})])
    assert scores.silence is None and scores.carry_over is None and scores.distractor is None
    assert view_metrics.show(None, 1) == "n/a"


def test_nothing_ever_opened_has_precision_none_and_recall_zero() -> None:
    scores = score([turn({OUTLOOK}, set())])
    assert scores.precision is None and scores.recall == 0.0 and scores.f1 == 0.0


def test_carry_over_is_the_exact_set_of_follow_up_turns() -> None:
    scores = score(
        [
            turn({OUTLOOK}, {OUTLOOK}),  # first turn: not a follow-up
            turn({OUTLOOK}, {OUTLOOK}, follow_up=True),
            turn({BUDGETS}, {OUTLOOK}, follow_up=True),
        ]
    )
    assert scores.carry_over == pytest.approx(0.5)


def test_the_distractor_run_scores_its_own_cases() -> None:
    scores = score(
        [
            turn({BUDGETS}, {BUDGETS}, distractor=True),
            turn(set(), {"health.today"}, distractor=True),
            turn({OUTLOOK}, {OUTLOOK}),
        ]
    )
    assert scores.distractor == pytest.approx(0.5)


def test_rounds_give_a_mean_and_a_spread() -> None:
    turns = [
        turn({OUTLOOK}, {OUTLOOK}, round_no=1),
        turn({OUTLOOK}, set(), round_no=2),
        turn({OUTLOOK}, {OUTLOOK}, round_no=3),
    ]
    rounds = by_round(turns)
    assert [r.recall for r in rounds] == [1.0, 0.0, 1.0]
    recall = spread(rounds)["recall"]
    assert recall is not None
    assert (recall.low, recall.high) == (0.0, 1.0) and recall.mean == pytest.approx(2 / 3)
    assert view_metrics.show(recall, 3) == "67% (0%-100%)"
    assert view_metrics.show(recall, 1) == "67%"


def test_the_report_section_and_json_round_trip() -> None:
    turns = [turn({OUTLOOK}, {OUTLOOK}, round_no=n) for n in (1, 2)]
    lines = view_metrics.section(turns)
    assert "over 2 rounds" in lines[1] and any("Exact-set match" in line for line in lines)
    assert view_metrics.section([turn(None, set())]) == []
    data = view_metrics.as_json(turns)
    assert len(data["rounds"]) == 2  # type: ignore[arg-type]
    row = {
        "views": [{"view": OUTLOOK}],
        "expected_views": [OUTLOOK],
        "follow_up": True,
        "distractor": False,
    }
    assert view_metrics.from_json(row, 2) == TurnViews(
        frozenset({OUTLOOK}), frozenset({OUTLOOK}), follow_up=True, round_no=2
    )
    assert view_metrics.from_json({"calls": []}, 1) is None  # written before views existed


def test_compare_reads_views_from_a_results_file(tmp_path: Path) -> None:
    turn_row = {"views": [{"view": OUTLOOK}], "expected_views": [OUTLOOK]}
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"runs": [{"round": 1, "id": "x", "turns": [turn_row]}]}))
    turns = compare.load_views(path)
    assert len(turns) == 1
    report = compare.views_report(turns, turns, ("a", "b"))
    assert "Exact-set match" in report and "100%" in report
    assert compare.views_report([], [], ("a", "b")) == ""


# --- the cases ------------------------------------------------------------------------------


def test_view_cases_have_unique_ids_and_the_views_area() -> None:
    ids = [c.id for c in view_cases.VIEW_CASES]
    assert len(ids) == len(set(ids)) >= 55
    assert all(c.area == "views" and c.id.startswith("views-") for c in view_cases.VIEW_CASES)


def test_expected_views_come_from_the_expected_tools_unless_a_case_says() -> None:
    by_id = view_cases.LABELS
    assert view_cases.expected_views(by_id["views-outlook-month"]) == [frozenset({OUTLOOK})]
    assert view_cases.expected_views(by_id["views-health-food-log"]) == [
        frozenset({"health.today"})
    ]
    assert view_cases.expected_views(by_id["views-health-bench-pr"]) == [
        frozenset({"health.records"})
    ]
    assert view_cases.expected_views(by_id["views-silence-thanks"]) == [frozenset()]
    assert view_cases.expected_views(by_id["views-followup-switch"]) == [
        frozenset({BUDGETS}),
        frozenset({OUTLOOK}),
    ]


def test_the_cases_cover_the_health_views_silence_and_a_cross_domain_turn() -> None:
    wanted = {
        n: view_cases.expected_views(vc)[-1] for n, vc in view_cases.LABELS.items() if vc.turns
    }
    opened = {v for views in wanted.values() if views for v in views}
    for kind in (
        ViewKind.TODAY,
        ViewKind.WEIGHT_TREND,
        ViewKind.WORKOUT,
        ViewKind.RECORDS,
        ViewKind.PORTFOLIO,
        ViewKind.SPENDING,
    ):
        assert kind.value in opened
    assert sum(1 for v in wanted.values() if v == frozenset()) >= 10
    assert any(
        v and len(v) > 1 and any(k.startswith("health.") for k in v) for v in wanted.values()
    )
    assert any(vc.distractor for vc in view_cases.VIEW_SETS)


def test_calls_open_a_view_once_and_failed_calls_open_none() -> None:
    def call(n: int, name: str, **args: object) -> AIMessage:
        return AIMessage("", tool_calls=[{"id": f"c{n}", "name": name, "args": args}])

    messages = [
        call(1, "month_outlook"),
        ToolMessage("ok", tool_call_id="c1"),
        call(2, "month_outlook", month="2026-08"),
        call(3, "show", view="health.records"),
        call(4, "list_budgets"),
        ToolMessage("Error: no budgets", tool_call_id="c4"),
        call(5, "log_expense"),
    ]
    assert view_cases.opened_in(messages, skip="kernel") == [
        {"view": OUTLOOK},
        {"view": "health.records"},
    ]
    assert view_cases.opened_in([call(1, "calculate")], skip="kernel") == []
