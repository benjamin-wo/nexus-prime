# C2 — Retrieval (FROZEN)

Frozen before iteration 1. Do not edit while C2 is open.

## Standard

Ordinary IR practice over the frozen manifest registry (`capabilities/manifests/*.yaml`,
`capabilities/registry.py`). No hard classification step; no new keywords list; retrieval reads
manifest content only.

## Metrics (definition frozen)

- `recall@5` = per-row |correct ∩ top5| / |correct|, averaged over the 56 replay rows whose correct
  capability set intersects the registry (the other 14 rows are pure-insufficiency or empty rows
  owned by C5). Target: >= 0.95.
- `precision@5` = per-row |top5 ∩ real manifests| / 5 (shortlist realness: the 60 synthetic manifests
  are padding that may crowd the shortlist; this measures how much of the top-5 is polluted by
  synthetics), averaged over the same 56 rows with the registry padded to 66 total. Target: >= 0.80.
  Secondary evidence: fraction of rows whose full correct set is inside top5 (reported, not gated).
- Shortlist token cost: mean tokens of the top-5 manifest retrieval texts, stated in the trace.

## Probes

1. Both metrics measured on the frozen replay set with the padded registry; traces per row.
2. A correct capability at true rank 9 with k=5 triggers recovery (expanded shortlist / re-plan),
   never silent execution of a wrong capability.

## Fixtures

- Harness: `gauntlet/eval_c2.py`; traces: `gauntlet/c2/retrieval-trace.jsonl`.
- Recovery probe: `tests/test_retrieval.py`.

## Success criteria

Both probes pass with evidence; recall and precision targets met; existing tests pass unchanged.
