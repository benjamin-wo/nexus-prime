# Builder Brief — C4: Fast Path

## Goal

Add a fast path for known, read-only, single-capability requests (e.g. next-bus ETA). It must skip
enumerable stages with justification, never swallow requests that need planning, HITL, or writes,
and must meet the measured p50 target.

## Locked inputs

- `gauntlet/c4/benchmark.md` (verbatim).
- C1-C3 artifacts (locked): manifests, retrieval, planner, plan execution.
- `gauntlet/replay-set.jsonl` (frozen).

## Task

Implement the gate, wire it into plan execution, measure p50 for "when's my next bus", enumerate
skipped stages, and prove exclusions. Existing tests pass unchanged.

## Output requirement

Artifacts + `gauntlet/c4/probe-traces.jsonl` (per probe: input, decision, stages skipped, timing,
final text). Prose without a trace is not an output.
