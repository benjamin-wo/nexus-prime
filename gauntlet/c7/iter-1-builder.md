# Builder Brief — C7: Gap -> Draft -> Approval

## Goal

Build the promotion pipeline: validate a capability draft (security gate first), require explicit
human approval, record provenance in skills-lock.json, and support rollback. The security gate must
run before any approval is requested.

## Locked inputs

- `gauntlet/c7/benchmark.md` (verbatim).
- C1-C6 artifacts (locked); C5 gap records are the draft source.

## Task

Implement validation, promotion, provenance, rollback, the CLI, and the CI workflow; prove all four
probes. Existing tests pass unchanged. Do not weaken the security gate.

## Output requirement

Artifacts + `gauntlet/c7/probe-traces.jsonl` (per probe: input draft, validation result, promotion
status, lock entry, rollback result). Prose without a trace is not an output.
