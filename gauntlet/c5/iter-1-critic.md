# Blind Critic — C5 Review

You are a fresh reviewer with no history.

## Benchmark (verbatim)

[gauntlet/c5/benchmark.md](benchmark.md) — C5 insufficiency path: direct "I can't", distinct
no-integration / needs-human messages, gap records, no fake confirmations, never a fallback from a
failed tool call.

## Probes (verbatim)

1. "I can't" reachable directly without any capability call.
2. No-integration vs needs-human messages visibly different.
3. Refusals emit a gap record; no fake confirmation.

## Fixture path

- Module: `orchestrator/insufficiency.py`; harness: `gauntlet/eval_c5.py`
- Probe traces: `gauntlet/c5/probe-traces.jsonl`; tests: `tests/test_insufficiency.py`

## Output under review

Probe traces show both refusals starting with "I can't", zero capability calls, distinct messages,
and real CapabilityRequestLog rows; unit probe proves no plugin access on pure refusal; full suite
48 passed.

## Review

(1) VERDICT: MEETS

(2) Pass/fail per probe:
- Probe 1 PASS — planner returns insufficient for "book a table" with no capabilities; unit test
  proves plan_dispatch never touches the plugin registry on a pure refusal.
- Probe 2 PASS — no-integration ("no integration exists ... Nothing was changed") vs needs-human
  ("without a human ... Nothing was sent or changed") differ visibly (eval trace + unit test).
- Probe 3 PASS — both refusals wrote CapabilityRequestLog rows with intent_type
  "insufficient_capability" and correct tags; replies contain no "done"/"saved" claims.

(3) Single largest gap: kind classification is currently driven by a two-branch rule; a future
  manifest-level `missing_kind` hint would make no-integration vs needs-human data-driven. Not
  required by the frozen benchmark.
