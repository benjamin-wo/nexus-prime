from __future__ import annotations

from typing import Any, Dict, List

from evals.judge import CRITERIA
from evals.simulation import SimulationResult


def render_simulation_text(results: List[SimulationResult]) -> str:
    lines = ["=== Tier 3: Multi-Turn Simulation ==="]
    for result in results:
        m = result.metrics
        if result.status == "error":
            lines.append(f"[ERROR] {result.scenario_id}: {result.error}")
            continue
        slot = m["slot_filling"]
        context = m["context_retention"]
        tools = ", ".join(m["tools_used"]) or "-"
        lines.append(
            f"[{'PASS' if result.status == 'passed' else 'FAIL'}] {result.scenario_id} "
            f"({m['turns']} turns, {m['latency_total_s']}s) "
            f"goal_completed={m['goal_completed']} slot_filling={slot['passed']}/{slot['total']} "
            f"context_retention={context['passed']}/{context['total']} tools=[{tools}]"
        )
        for i, turn in enumerate(result.turns):
            lines.append(f"    turn {i}: U: {turn[0][:90]}")
            lines.append(f"           A: {turn[1][:200]}")
    passed = sum(1 for r in results if r.status == "passed")
    lines.append(f"Summary: {passed}/{len(results)} scenarios passed")
    return "\n".join(lines)


def render_judge_text(report: Dict[str, Any]) -> str:
    lines = ["=== Tier 4: LLM-as-Judge ==="]
    if report["count"] == 0:
        lines.append("No conversations judged.")
        return "\n".join(lines)
    lines.append(f"Conversations: {report['count']} judged: {report['judged']} failed: {report['failed_judgments']}")
    for name in CRITERIA:
        lines.append(f"  {name}: {report['criteria_means'][name]}")
    lines.append(f"  overall: {report['overall_mean']}")
    lines.append(f"Summary: {report['passed']}/{report['count']} passed "
                 f"(pass >= {report.get('pass_score')}, safety >= {report.get('fail_safety_below')})")
    return "\n".join(lines)


def render_combined(results: List[SimulationResult], judge_report: Dict[str, Any]) -> str:
    sections = []
    if results:
        sections.append(render_simulation_text(results))
    if judge_report and judge_report.get("count", 0) > 0:
        sections.append(render_judge_text(judge_report))
    return "\n\n".join(sections)


def build_json_report(
    sim_results: List[SimulationResult],
    judge_report: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "tier3_simulation": [
            {
                "scenario_id": r.scenario_id,
                "status": r.status,
                "metrics": r.metrics,
                "error": r.error,
            }
            for r in sim_results
        ],
        "tier4_judge": judge_report,
    }