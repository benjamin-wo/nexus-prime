# C4 — Fast Path (FROZEN)

Frozen before iteration 1. Do not edit while C4 is open.

## Standard

Known, read-only, single-capability requests skip expensive stages and execute directly. The fast
path is an optimization gate over retrieval and planner output — not a second classification layer
and not a widening of the `goto` enum.

## Probes

1. "when's my next bus" completes with p50 < 3000 ms (measured locally, mocked outbound network),
   with the fast-path flag in the trace.
2. Skipped stages are enumerated and justified (in code and in the probe trace).
3. A request that must not take the fast path is excluded (unit probe: spend/insufficient request
   and multi-capability request both return not-fast-path).

## Fixtures

- Gate: `orchestrator/fastpath.py`; harness: `gauntlet/eval_c4.py`; traces: `gauntlet/c4/probe-traces.jsonl`.
- Tests: `tests/test_fastpath.py`.

## Success criteria

All three probes pass with evidence; existing tests pass unchanged.
