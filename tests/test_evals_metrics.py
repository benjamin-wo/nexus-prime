from langchain_core.messages import AIMessage, ToolMessage

from evals.metrics import (
    compute_metrics,
    detect_tool_names,
    evaluate_turn_check,
    forbidden_hits,
    missing_terms,
)
from evals.scenarios import ContextCheck, Scenario, TurnCheck


def test_missing_terms():
    assert missing_terms("Spent 15.50 on lunch", ["15.50"]) == []
    assert missing_terms("Spent 15 on lunch", ["15.50"]) == ["15.50"]


def test_forbidden_hits():
    assert forbidden_hits("sorry, I cannot", ["sorry"]) == ["sorry"]
    assert forbidden_hits("all good", ["sorry"]) == []


def test_evaluate_turn_check():
    check = TurnCheck(contains=["25"], not_contains=["error"])
    assert evaluate_turn_check("Logged 25 for you", check)["passed"] is True
    assert evaluate_turn_check("error: failed", check)["passed"] is False


def test_detect_tool_names():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "process_extracted_expense", "id": "call_1", "args": {}}]),
        ToolMessage(content="ok", tool_call_id="call_1", name="process_extracted_expense"),
    ]
    assert detect_tool_names(messages) == {"process_extracted_expense"}
    assert detect_tool_names([]) == set()


def test_compute_metrics_goal_completed():
    scenario = Scenario(
        id="t",
        name="t",
        user_turns=["a"],
        checks=[TurnCheck(contains=["25"])],
        expected_tools=["tool_a"],
    )
    metrics = compute_metrics(scenario, ["Logged 25"], [{"tool_a"}], [1.0])
    assert metrics["goal_completed"] is True
    assert metrics["slot_filling"] == {"passed": 1, "total": 1}


def test_compute_metrics_fails_on_missing_slot():
    scenario = Scenario(id="t", name="t", user_turns=["a"], checks=[TurnCheck(contains=["25"])])
    metrics = compute_metrics(scenario, ["Logged 20"], [set()], [1.0])
    assert metrics["goal_completed"] is False
    assert metrics["turn_results"][0]["missing"] == ["25"]


def test_compute_metrics_no_checks_is_ok():
    scenario = Scenario(id="t", name="t", user_turns=["a"])
    metrics = compute_metrics(scenario, ["hello"], [set()], [0.5])
    assert metrics["goal_completed"] is True


def test_compute_metrics_context_retention():
    scenario = Scenario(
        id="t",
        name="t",
        user_turns=["a", "b"],
        checks=[TurnCheck(), TurnCheck()],
        context_checks=[ContextCheck(turn=1, terms=["Sakura"])],
    )
    metrics = compute_metrics(scenario, ["ok", "done at Sakura"], [set(), set()], [0.5, 0.5])
    assert metrics["context_retention"] == {"passed": 1, "total": 1}
    assert metrics["goal_completed"] is True


def test_compute_metrics_fails_when_expected_tool_missing():
    scenario = Scenario(
        id="t",
        name="t",
        user_turns=["a"],
        checks=[TurnCheck(contains=["25"])],
        expected_tools=["tool_a"],
    )
    metrics = compute_metrics(scenario, ["Logged 25"], [set()], [1.0])
    assert metrics["goal_completed"] is False
    assert metrics["tools_ok"] is False


def test_compute_metrics_fails_when_forbidden_tool_used():
    scenario = Scenario(
        id="t",
        name="t",
        user_turns=["hi"],
        forbidden_tools=["search_web"],
    )
    metrics = compute_metrics(scenario, ["hey"], [{"search_web"}], [0.5])
    assert metrics["goal_completed"] is False
    assert metrics["forbidden_tools_hit"] == ["search_web"]
    assert metrics["forbidden_tools_ok"] is False


def test_compute_metrics_passes_without_forbidden_tools():
    scenario = Scenario(
        id="t",
        name="t",
        user_turns=["hi"],
        forbidden_tools=["search_web"],
    )
    metrics = compute_metrics(scenario, ["hey"], [set()], [0.5])
    assert metrics["goal_completed"] is True
    assert metrics["forbidden_tools_ok"] is True