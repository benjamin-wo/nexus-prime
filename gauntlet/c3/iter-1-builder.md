# Builder Brief — C3: Decision Object + Planner

## Goal

Replace single-label routing with retrieve -> plan -> select a set. The planner reads the C2
shortlist plus thread state, emits a Decision (capability set, ordering, insufficiency, confidence),
and executes the plan with the existing plugins. Managers remain derived tags; no manager class,
no second classification layer, no `goto` enum widening.

## Locked inputs

- `gauntlet/c3/benchmark.md` (verbatim, including probes and success criteria).
- `gauntlet/replay-set.jsonl` (frozen).
- C1 manifests + registry; C2 retrieval (locked).
- Existing plugins and graph (`capabilities/*`, `orchestrator/router.py`, `orchestrator/graph.py`).

## Task

Build the decision object, deterministic planner, and plan execution adapter; wire the graph to the
planner while preserving legacy `route_intent` and existing test semantics; measure B_acc on the
frozen replay set; produce per-probe traces. Existing tests must pass unchanged.

## Output requirement

Artifacts + `gauntlet/c3/probe-traces.jsonl` with, per probe: input, retrieval scores, shortlist,
planner decision, capability calls, final Telegram text. Prose without a trace is not an output.
