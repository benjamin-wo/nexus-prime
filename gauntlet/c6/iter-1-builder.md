# Builder Brief — C6: Sandboxed Code Execution

## Goal

Provide safe code execution with process isolation, import/egress guards, secret redaction, timeout,
and a hard boundary where inbox text is data. E2B provider wired for production; local provider
measured offline.

## Locked inputs

- `gauntlet/c6/benchmark.md` (verbatim).
- C1-C5 artifacts (locked).

## Task

Implement the sandbox, capability tool, manifest, and harness; prove all five probes; keep existing
tests green. Never let generated code cross the credential vault.

## Output requirement

Artifacts + `gauntlet/c6/probe-traces.jsonl` (per probe: input code, data, what ran, result).
Prose without a trace is not an output.
