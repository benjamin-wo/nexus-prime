"""C1 probe 2: blind routing using ONLY manifest content."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from capabilities.registry import load_registry

ROOT = Path(__file__).resolve().parent
REPLAY = ROOT / "replay-set.jsonl"

BLIND_15 = [
    "r001", "r003", "r005", "r006", "r022", "r023", "r024", "r025",
    "r026", "r047", "r049", "r053", "r057", "r063", "r007",
]

STOP = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "and", "or",
    "is", "are", "was", "were", "my", "me", "i", "it", "this", "that",
    "how", "what", "when", "who", "do", "does", "did", "from", "with",
}


def _tokens(text: str) -> Counter:
    return Counter(
        w
        for w in re.findall(r"[a-z0-9$']+", text.lower())
        if w not in STOP and len(w) > 1
    )


def route_by_manifest_only(message: str, registry: dict[str, object]) -> tuple[str, dict[str, float]]:
    """Score manifests by lexical overlap with the user message. No plugin keywords."""
    query = _tokens(message)
    if not query:
        return "", {}
    docs = {mid: _tokens(manifest.retrieval_text) for mid, manifest in registry.items()}
    n = max(1, len(docs))
    doc_freq: Counter = Counter()
    for tokens in docs.values():
        for token in set(tokens):
            doc_freq[token] += 1

    def token_weight(token: str) -> float:
        return 1.0 + math.log((n + 1) / (doc_freq.get(token, 0) + 1))

    scores: dict[str, float] = {}
    for mid, doc in docs.items():
        overlap = sum(token_weight(t) * min(doc[t], query[t]) for t in query)
        # Boost exact-id mention (email/gmail/inbox etc.) and shared tags.
        mid_tokens = _tokens(mid)
        overlap += 2.0 * sum(token_weight(t) * min(mid_tokens[t], query[t]) for t in query)
        tags = _tokens(" ".join(registry[mid].tags))
        overlap += 0.5 * sum(token_weight(t) * min(tags[t], query[t]) for t in query)
        scores[mid] = overlap
    best = max(scores, key=scores.get)
    return best, scores


def main() -> None:
    replay = [json.loads(line) for line in REPLAY.open(encoding="utf-8")]
    by_id = {r["id"]: r for r in replay}
    registry = load_registry()
    traces = []
    correct = 0
    for row_id in BLIND_15:
        row = by_id[row_id]
        expected = row["correct"][0] if row["correct"] else "(none)"
        chosen, scores = route_by_manifest_only(row["message"], registry)
        ok = chosen == expected
        correct += int(ok)
        traces.append(
            {
                "id": row_id,
                "message": row["message"],
                "expected": expected,
                "chosen": chosen,
                "ok": ok,
                "scores": dict(sorted(scores.items(), key=lambda kv: -kv[1])),
                "synthetic": row["synthetic"],
            }
        )
    out = ROOT / "c1" / "blind-route-trace.jsonl"
    out.write_text(
        "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces),
        encoding="utf-8",
    )
    print(f"blind-route: {correct}/15 correct")
    for t in traces:
        if not t["ok"]:
            print(f"  MISS {t['id']}: expected={t['expected']} chosen={t['chosen']}")


if __name__ == "__main__":
    main()
