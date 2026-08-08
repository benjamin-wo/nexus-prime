# C5 — Insufficiency Path (FROZEN)

Frozen before iteration 1. Do not edit while C5 is open.

## Standard

"I can't" is a planner-level decision, reachable directly from the request — never a fallback
discovered after a tool call fails. *No integration exists* and *not without a human* produce
visibly different messages. Every refusal emits a gap record and never a fake confirmation.

## Probes

1. "I can't" reachable directly: a planner decision for an unsupported request is insufficient
   without any capability call; unit probe proves no plugin executes.
2. No-integration vs needs-human messages are visibly different (different wording, same refusal).
3. Refusals emit a gap record (CapabilityRequestLog row with request text and missing tags) and the
   reply contains no fake confirmation (no "done"/"saved" claim).

## Fixtures

- Module: `orchestrator/insufficiency.py`; harness: `gauntlet/eval_c5.py`; traces: `gauntlet/c5/probe-traces.jsonl`.
- Tests: `tests/test_insufficiency.py`.

## Success criteria

All three probes pass with evidence; existing tests pass unchanged.
