# Builder Brief — C1: Manifest Schema + 4 Migrations

## Goal

Turn the capability registry into a manifest-first, data-driven registry: every capability declares a
retrieval-facing manifest; managers exist only as tags derived from manifests; routing can be done by a
stranger who has never seen the code, using only the manifests.

## Locked inputs

- `gauntlet/c1/benchmark.md` (verbatim, including all probes).
- `gauntlet/replay-set.jsonl` (frozen instrument; read-only).
- Current repository code under `capabilities/`, `orchestrator/`, `core/`, `tests/`.

## Task

Build the manifest schema, loader, and migration artifacts described by the benchmark. Demonstrate every
probe end to end and write a per-probe trace. Do not modify existing tests. Do not touch `core/vault.py`,
`orchestrator/router.py` routing semantics, or the LangGraph graph. Do not add any hard classification step.

## Output requirement

Artifacts + `gauntlet/c1/probe-traces.jsonl` (one trace per probe: input, what ran, output/measurement).
Prose without a trace is not an output.
