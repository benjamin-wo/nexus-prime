# Builder Brief — C5: Insufficiency Path

## Goal

Make insufficiency a first-class planner decision with distinct no-integration / needs-human
messages, automatic gap records, and a hard guarantee that it is never synthesized from a failed
tool call.

## Locked inputs

- `gauntlet/c5/benchmark.md` (verbatim).
- C1-C4 artifacts (locked).

## Task

Implement classification, message templates, and gap recording; wire refusals into plan execution;
prove direct reachability and no-fake-confirmation. Existing tests pass unchanged.

## Output requirement

Artifacts + `gauntlet/c5/probe-traces.jsonl` (per probe: input, decision, capability calls made
(must be none for pure refusal), final text, gap record id). Prose without a trace is not an output.
