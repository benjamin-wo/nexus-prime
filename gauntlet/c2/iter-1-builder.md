# Builder Brief — C2: Retrieval

## Goal

Build ordinary IR over manifests: a BM25 index over `retrieval_text`, top-k shortlists, stated token
cost, and a recovery path when the correct capability sits outside k. No hard classification step.

## Locked inputs

- `gauntlet/c2/benchmark.md` (verbatim, including the frozen metric definitions).
- `gauntlet/replay-set.jsonl` (frozen; read-only).
- C1 artifacts (`capabilities/manifests/`, `capabilities/registry.py`) — locked.

## Task

Implement the index and metrics harness, pad the registry with 60 deterministic synthetic manifests,
measure recall@5 and precision@5, state shortlist token cost, and prove the rank-9 recovery probe.
Do not modify existing tests. Do not touch `orchestrator/router.py` routing semantics or the graph.

## Output requirement

Artifacts + `gauntlet/c2/retrieval-trace.jsonl` (per-row scores, ranks, recovery flags).
Prose without a trace is not an output.
