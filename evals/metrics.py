from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set

from evals.scenarios import ContextCheck, Scenario, TurnCheck


def missing_terms(text: str, terms: Sequence[str]) -> List[str]:
    lowered = (text or "").lower()
    return [term for term in terms if term.lower() not in lowered]


def forbidden_hits(text: str, terms: Sequence[str]) -> List[str]:
    lowered = (text or "").lower()
    return [term for term in terms if term.lower() in lowered]


def evaluate_turn_check(text: str, check: TurnCheck) -> Dict[str, Any]:
    missing = missing_terms(text, check.contains)
    forbidden = forbidden_hits(text, check.not_contains)
    return {
        "passed": not missing and not forbidden,
        "missing": missing,
        "forbidden": forbidden,
    }


def detect_tool_names(messages: Sequence[Any]) -> Set[str]:
    """Collect tool names from a turn's message list (AIMessage tool_calls + ToolMessages)."""
    names: Set[str] = set()
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            name = str(call.get("name") or call.get("id") or "")
            if name and name not in {"", "None"}:
                names.add(name)
        tool_name = getattr(message, "name", None)
        if tool_name:
            names.add(str(tool_name))
    return names


def compute_metrics(
    scenario: Scenario,
    bot_texts: Sequence[str],
    tools_per_turn: Sequence[Set[str]],
    latencies: Sequence[float],
) -> Dict[str, Any]:
    """Score a scripted run against the scenario's expected behavior."""
    turn_results = [
        evaluate_turn_check(text, check)
        for text, check in zip(bot_texts, scenario.checks)
    ]
    slot_passed = sum(1 for r in turn_results if r["passed"])
    slot_total = len(turn_results)

    context_results = []
    for context_check in scenario.context_checks:
        if context_check.turn < len(bot_texts):
            missing = missing_terms(bot_texts[context_check.turn], context_check.terms)
            context_results.append({"passed": not missing, "missing": missing, "turn": context_check.turn})
        else:
            context_results.append({"passed": False, "missing": list(context_check.terms), "turn": context_check.turn})
    context_passed = sum(1 for r in context_results if r["passed"])
    context_total = len(context_results)

    tools_used: Set[str] = set().union(*tools_per_turn) if tools_per_turn else set()
    tools_ok = not scenario.expected_tools or bool(tools_used & set(scenario.expected_tools))

    slot_ok = slot_total == 0 or slot_passed == slot_total
    context_ok = context_total == 0 or context_passed == context_total

    total_latency = sum(latencies)
    return {
        "turns": len(bot_texts),
        "slot_filling": {"passed": slot_passed, "total": slot_total},
        "context_retention": {"passed": context_passed, "total": context_total},
        "tools_used": sorted(tools_used),
        "expected_tools": list(scenario.expected_tools),
        "tools_ok": tools_ok,
        "latency_total_s": round(total_latency, 2),
        "latency_mean_s": round(total_latency / len(latencies), 2) if latencies else 0.0,
        "goal_completed": slot_ok and context_ok and tools_ok,
        "turn_results": turn_results,
        "context_results": context_results,
    }