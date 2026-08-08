# C8 — Ambient Triggers (FROZEN)

Frozen before iteration 1. Do not edit while C8 is open.

## Standard

Proactivity is triggers invoking the agent — never the agent guessing. Delivery obeys the owner's
quiet hours: nothing non-urgent before 09:00 in the owner's timezone (Asia/Singapore by default).
Urgent triggers still land.

## Probes

1. A 02:40 SGT trigger over a $4 mismatch is suppressed.
2. A genuinely urgent trigger at 02:40 SGT still lands (large mismatch or urgent keyword).
3. No trigger record -> no proactive action (proactivity never guesses).
4. Routine trigger after 09:00 lands.

## Fixture path

- Policy: `core/ambient.py`; scheduler wiring: `core/scheduler.py::_execute_scheduled_job`
- Harness: `gauntlet/eval_c8.py`; traces: `gauntlet/c8/probe-traces.jsonl`
- Tests: `tests/test_ambient.py`

## Measured configuration

Quiet hour: before 09:00 local. Urgent amount-mismatch threshold: SGD 100.00. Urgent keywords:
medical, security, fraud, urgent, critical, overdraft, emergency, breach.

## Success criteria

All four probes pass with evidence; existing tests pass unchanged.
