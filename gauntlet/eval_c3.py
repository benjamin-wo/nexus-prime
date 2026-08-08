"""C3 success criterion: B_acc of the deterministic planner on the frozen replay set."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from capabilities.registry import load_registry
from capabilities.retrieval import BM25Index
from orchestrator.planner import decision_to_dict, deterministic_plan

ROOT = Path(__file__).resolve().parent
REPLAY = ROOT / "replay-set.jsonl"
BASELINE_B_ACC = 0.629


def state_for(row: dict) -> dict:
    state: dict = {"active_domain": None, "last_decision": None, "messages": []}
    context = row.get("thread_context") or ""
    for domain in ("expenses", "recipes", "routes", "reminders", "email", "general"):
        if domain in context:
            state["active_domain"] = domain
            state["last_decision"] = {"capabilities": [{"id": domain, "confidence": 0.9}]}
    state["messages"] = [HumanMessage(content=row["message"])]
    return state


def main() -> None:
    replay = [json.loads(line) for line in REPLAY.open(encoding="utf-8")]
    registry = load_registry()
    index = BM25Index(list(registry.values()))
    traces = []
    correct = 0

    for row in replay:
        result = index.retrieve_with_recovery(row["message"], k=5)
        decision = deterministic_plan(row["message"], state_for(row), result)
        planned = decision.planned_set
        correct_set = set(row["correct"])
        if correct_set:
            ok = planned == correct_set
        else:
            ok = decision.question is not None
        correct += int(ok)
        traces.append(
            {
                "id": row["id"],
                "message": row["message"],
                "thread_context": row.get("thread_context"),
                "top5": [{"id": h.id, "score": round(h.score, 4)} for h in result.top],
                "recovered": result.recovered,
                "decision": decision_to_dict(decision),
                "planned_set": sorted(planned),
                "correct_set": sorted(correct_set),
                "ok": ok,
                "synthetic": row["synthetic"],
            }
        )

    out = ROOT / "c3" / "planner-trace.jsonl"
    out.write_text(
        "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces),
        encoding="utf-8",
    )
    b_acc = correct / len(replay)
    print(f"B_acc (planner) = {b_acc:.4f} ({correct}/{len(replay)})")
    print(f"stated margin vs baseline {BASELINE_B_ACC:.3f}: +{b_acc - BASELINE_B_ACC:.4f}")
    for t in traces:
        if not t["ok"]:
            print(f"  MISS {t['id']}: planned={t['planned_set']} correct={t['correct_set']}")


if __name__ == "__main__":
    main()
