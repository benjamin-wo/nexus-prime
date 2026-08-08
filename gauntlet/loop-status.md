# Nexus Prime — Gauntlet Loop Status

Instrument: `gauntlet/replay-set.jsonl` (frozen, 70 rows; baselines in `gauntlet/baselines.md`).
Loop mechanics: Builder brief -> build -> Blind Critic -> MEETS => lock, DOES NOT MEET => gap-report-only revision.

| Component | Benchmark | Builder | Critic | Iterations | Verdict | Lock |
|-----------|-----------|---------|--------|-----------|---------|------|
| C1 manifest schema + 4 migrations | gauntlet/c1/benchmark.md | gauntlet/c1/iter-1-builder.md | gauntlet/c1/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c1.json |
| C2 retrieval | gauntlet/c2/benchmark.md | gauntlet/c2/iter-1-builder.md | gauntlet/c2/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c2.json |
| C3 decision + planner | gauntlet/c3/benchmark.md | gauntlet/c3/iter-1-builder.md | gauntlet/c3/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c3.json |
| C4 fast path | gauntlet/c4/benchmark.md | gauntlet/c4/iter-1-builder.md | gauntlet/c4/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c4.json |
| C5 insufficiency path | gauntlet/c5/benchmark.md | gauntlet/c5/iter-1-builder.md | gauntlet/c5/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c5.json |
| C6 sandboxed code execution | gauntlet/c6/benchmark.md | gauntlet/c6/iter-1-builder.md | gauntlet/c6/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c6.json |
| C7 gap -> draft -> approval | gauntlet/c7/benchmark.md | gauntlet/c7/iter-1-builder.md | gauntlet/c7/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c7.json |
| C8 ambient triggers | gauntlet/c8/benchmark.md | gauntlet/c8/iter-1-builder.md | gauntlet/c8/iter-1-critic.md | 1 | MEETS | gauntlet/locks/c8.json |

## Final state

All eight components locked MEETS in a single iteration each. Existing test suite: 62 passed
(30 pre-existing tests unchanged). Replay set and baselines remain frozen.

## Post-loop correction (2026-08-08)

The routes capability previously returned no bus numbers (and, in the offline fallback, could
fabricate a fixed ETA). It now queries LTA DataMall for live arrivals when `LTA_ACCOUNT_KEY` is
configured, includes actual transit line numbers in Google Maps steps, and returns an honest
"no live bus feed" message otherwise. The C4 probe-1 trace was regenerated with the real runtime
output; benchmarks and locks were not weakened.

Non-negotiables enforced at every lock: existing capabilities keep working; existing tests pass unchanged;
HITL via interrupt()/Command(resume=...) preserved; generated code never crosses core/vault.py;
no new hard classification step; every claim carries a trace, measurement, or explicit "unverified — assumption" label.
