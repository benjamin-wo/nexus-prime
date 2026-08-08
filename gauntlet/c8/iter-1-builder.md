# Builder Brief — C8: Ambient Triggers

## Goal

Add an ambient delivery policy: only trigger records invoke proactive action; quiet hours suppress
non-urgent delivery before 09:00 local; urgency classification lets genuinely urgent triggers
through. Wire it into the scheduler's delivery path.

## Locked inputs

- `gauntlet/c8/benchmark.md` (verbatim).
- C1-C7 artifacts (locked).

## Task

Implement the policy, wire delivery, prove the four probes, and keep existing tests green.

## Output requirement

Artifacts + `gauntlet/c8/probe-traces.jsonl` (per probe: trigger, local time, urgency decision,
delivery decision, reason). Prose without a trace is not an output.
