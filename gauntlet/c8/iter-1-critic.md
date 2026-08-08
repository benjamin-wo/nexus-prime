# Blind Critic — C8 Review

You are a fresh reviewer with no history.

## Benchmark (verbatim)

[gauntlet/c8/benchmark.md](benchmark.md) — C8 ambient triggers: triggers invoke the agent, quiet
hours before 09:00, $4 mismatch suppressed at 02:40, urgent triggers land.

## Probes (verbatim)

1. 02:40 SGT $4 mismatch suppressed.
2. Genuinely urgent trigger at 02:40 lands.
3. No trigger record -> no proactive action.
4. Routine trigger after 09:00 lands.

## Fixture path

- Policy: `core/ambient.py`; scheduler wiring: `core/scheduler.py::_execute_scheduled_job`
- Harness: `gauntlet/eval_c8.py`; traces: `gauntlet/c8/probe-traces.jsonl`
- Tests: `tests/test_ambient.py`

## Output under review

Probe traces show suppression at 02:40 for the $4 mismatch, delivery for the $500 mismatch and the
urgent keyword, no-delivery without a trigger record, and delivery at 10:00; full suite 62 passed.

## Review

(1) VERDICT: MEETS

(2) Pass/fail per probe:
- Probe 1 PASS — $4 mismatch at 02:40 SGT suppressed with "quiet hours" reason (trace 1).
- Probe 2 PASS — $500 mismatch and "URGENT security alert" both deliver at 02:40 (traces 2/2b).
- Probe 3 PASS — no trigger record returns "proactivity never guesses" (trace 3).
- Probe 4 PASS — routine mismatch at 10:00 delivers (trace 4).

(3) Single largest gap: urgency classification thresholds are code constants; a config-driven
  urgency policy would let the owner tune quiet hours and thresholds without a deploy. Not required
  by the frozen benchmark.
