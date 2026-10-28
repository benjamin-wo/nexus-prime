"""``--repeat``: pass rates, flaky and always-failing cases, the JSON file, and comparing two
result files. Fake results only; no model calls."""

import json
from pathlib import Path

from nexus.evals import compare
from nexus.evals.__main__ import _results_json
from nexus.evals.cases import Case, Turn
from nexus.evals.runner import CaseResult, Summary, TurnLog


def _result(case_id: str, passed: bool, round_no: int = 1, area: str = "log") -> CaseResult:
    case = Case(case_id, area, (Turn("hi"),))
    turn = TurnLog("hi", replies=["ok"], seconds=1.0, input_tokens=10, output_tokens=5)
    return CaseResult(case, [turn], [] if passed else ["nope"], round_no=round_no)


def _summary(grid: dict[str, list[bool]]) -> Summary:
    """``grid``: each case's outcome in round 1, 2, ..."""
    rounds = max(len(v) for v in grid.values())
    results = [
        _result(case_id, outcomes[n], n + 1)
        for n in range(rounds)
        for case_id, outcomes in grid.items()
    ]
    return Summary("m", results, None)


GRID = {
    "steady": [True, True, True, True],
    "flaky": [True, False, True, True],
    "broken": [False, False, False, False],
    "mostly-down": [False, True, False, False],
}


def test_pass_rates_flaky_and_always_failing() -> None:
    summary = _summary(GRID)
    assert summary.repeat == 4
    assert summary.per_case() == {
        "steady": (4, 4),
        "flaky": (3, 4),
        "broken": (0, 4),
        "mostly-down": (1, 4),
    }
    assert summary.flaky() == ["flaky", "mostly-down"]
    assert summary.always_failing() == ["broken"]
    assert summary.round_passes() == [2, 2, 2, 2]


def test_the_mean_min_and_max_pass_count_are_per_round() -> None:
    summary = _summary(
        {"a": [True, True, False], "b": [True, False, False], "c": [True, True, True]}
    )
    assert summary.round_passes() == [3, 2, 1]
    text = summary.markdown()
    assert "- Passed: **2.0/3** a round on average (67%), min 1, max 3, over 3 rounds" in text


def test_the_report_lists_flaky_and_always_failing_cases() -> None:
    text = _summary(GRID).markdown()
    flaky = text.split("Flaky (passed in some rounds, failed in others):")[1].split("Always")[0]
    assert "- `flaky`: 3/4" in flaky and "- `mostly-down`: 1/4" in flaky
    assert "steady" not in flaky and "broken" not in flaky
    always = text.split("Always failing (failed every round):")[1].split("| Case")[0]
    assert "- `broken`: 0/4" in always and "flaky" not in always
    assert "| steady | 4/4 |" in text and "| mostly-down | 1/4 |" in text
    assert "- `flaky` (round 2): nope" in text


def test_a_clean_repeat_says_none() -> None:
    text = _summary({"a": [True, True], "b": [True, True]}).markdown()
    assert text.count("None.") == 2


def test_timing_and_cost_cover_every_run() -> None:
    summary = _summary(GRID)
    assert len(summary.turn_seconds()) == 16
    assert "Passed: **8.0/4**" not in summary.markdown()  # 8 passes over 4 rounds is 2.0 a round
    assert "- Passed: **2.0/4** a round on average (50%), min 2, max 2, over 4 rounds" in (
        summary.markdown()
    )


def test_one_round_reads_exactly_as_before() -> None:
    summary = Summary("m", [_result("a", True), _result("b", False)], None)
    assert summary.repeat == 1
    text = summary.markdown()
    assert "- Passed: **1/2** (50%)" in text
    assert "Flaky" not in text and "Always failing" not in text and "| Case |" not in text
    assert "- `b`: nope" in text and "(round" not in text
    plain = json.loads(_results_json(summary))
    assert isinstance(plain, list) and [r["id"] for r in plain] == ["a", "b"]
    assert all("round" not in r for r in plain)


def test_the_json_with_repeats_has_rates_and_every_run() -> None:
    data = json.loads(_results_json(_summary(GRID)))
    assert data["repeat"] == 4 and data["passes_per_round"] == [2, 2, 2, 2]
    assert data["mean_passes"] == 2 and data["min_passes"] == 2 and data["max_passes"] == 2
    assert data["per_case"]["flaky"] == {"passed": 3, "runs": 4}
    assert data["flaky"] == ["flaky", "mostly-down"] and data["always_failing"] == ["broken"]
    assert len(data["runs"]) == 16
    assert {r["round"] for r in data["runs"]} == {1, 2, 3, 4}


def _write(tmp_path: Path, name: str, summary: Summary) -> Path:
    path = tmp_path / name
    path.write_text(_results_json(summary))
    return path


def test_compare_reads_both_file_shapes(tmp_path: Path) -> None:
    single = _write(tmp_path, "single.json", Summary("m", [_result("a", True)], None))
    repeated = _write(tmp_path, "repeated.json", _summary(GRID))
    assert compare.load_rates(single) == {"a": (1, 1)}
    assert compare.load_rates(repeated)["flaky"] == (3, 4)


def test_compare_flags_rates_two_or_more_apart() -> None:
    assert compare.differs((4, 4), (2, 4))
    assert not compare.differs((4, 4), (3, 4))
    assert not compare.differs((1, 1), (0, 1))  # one run each can't show a difference
    assert compare.differs((4, 4), (1, 2))  # 100% against 50%, out of 4: 2 apart
    assert not compare.differs((3, 4), (1, 2))


def test_compare_prints_rates_side_by_side(tmp_path: Path, capsys: object) -> None:
    main = _write(tmp_path, "main.json", _summary(GRID))
    other = _summary(
        {
            "steady": [True] * 4,
            "flaky": [True, False, True, True],
            "broken": [True, True, True, False],
            "mostly-down": [False, False, False, False],
            "new-case": [True] * 4,
        }
    )
    branch = _write(tmp_path, "branch.json", other)
    assert compare.main([str(main), str(branch)]) == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "main" in out and "branch" in out
    assert "broken" in out and "0/4" in out and "3/4" in out
    assert "- broken: 0/4 vs 3/4, better in branch" in out
    assert "Rates differing by 2 or more out of N: 1" in out
    assert "mostly-down" in out
    assert (
        "new-case         -     4/4" in out and "<-" not in out.split("new-case")[1].split("\n")[0]
    )
    assert "In only one file: new-case" in out
    assert "steady" not in out.split("(")[0]  # always passed in both: left out
    assert compare.main([str(main), str(branch), "--all"]) == 0
    assert "steady" in capsys.readouterr().out  # type: ignore[attr-defined]
