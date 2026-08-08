"""C2 probes 1: recall@5 / precision@5 on the frozen replay set, padded registry."""

from __future__ import annotations

import json
from pathlib import Path

from capabilities.registry import load_registry
from capabilities.retrieval import BM25Index, shortlist_token_cost
from capabilities.synthetic_registry import build_synthetic_manifests

ROOT = Path(__file__).resolve().parent
REPLAY = ROOT / "replay-set.jsonl"


def main() -> None:
    replay = [json.loads(line) for line in REPLAY.open(encoding="utf-8")]
    registry = load_registry()
    index = BM25Index(list(registry.values()) + build_synthetic_manifests())

    traces = []
    recall_sum = precision_sum = rows = 0
    token_costs = []
    recovery_events = 0
    skipped = []

    for row in replay:
        relevant = set(row["correct"]) & set(registry)
        if not relevant:
            skipped.append(row["id"])
            continue
        result = index.retrieve_with_recovery(row["message"], k=5)
        top_ids = [h.id for h in result.top]
        hit = len(relevant & set(top_ids))
        recall = hit / len(relevant)
        top5_real = [mid for mid in top_ids if mid in registry]
        precision = len(top5_real) / 5
        correct_subset = 1.0 if relevant <= set(top_ids) else 0.0
        recall_sum += recall
        precision_sum += precision
        rows += 1
        token_costs.append(shortlist_token_cost(result))
        if result.recovered:
            recovery_events += 1
        traces.append(
            {
                "id": row["id"],
                "message": row["message"],
                "relevant": sorted(relevant),
                "top5": top_ids,
                "recall@5": round(recall, 4),
                "precision@5": round(precision, 4),
                "top5_real": top5_real,
                "correct_subset_in_top5": bool(correct_subset),
                "recovered": result.recovered,
                "expanded_ids": [h.id for h in result.expanded],
                "top5_score_range": (
                    round(min(h.score for h in result.top), 4),
                    round(max(h.score for h in result.top), 4),
                ),
            }
        )

    out = ROOT / "c2" / "retrieval-trace.jsonl"
    out.write_text(
        "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces),
        encoding="utf-8",
    )
    recall = recall_sum / rows
    precision = precision_sum / rows
    avg_cost = sum(token_costs) / len(token_costs)
    print(f"rows_with_relevant_capability={rows} skipped_insufficiency={len(skipped)} ({skipped})")
    print(f"recall@5={recall:.4f}")
    subset = sum(t["correct_subset_in_top5"] for t in traces) / rows
    print(f"precision@5={precision:.4f} (shortlist realness)")
    print(f"correct_subset_in_top5={subset:.4f}")
    print(f"shortlist_token_cost_mean={avg_cost:.1f} tokens (top-5 retrieval_text)")
    print(f"recovery_triggered={recovery_events}/{rows}")
    return recall, precision


if __name__ == "__main__":
    main()
