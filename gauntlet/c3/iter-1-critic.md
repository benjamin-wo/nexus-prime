# Blind Critic — C3 Review

You are a fresh reviewer with no history.

## Benchmark (verbatim)

[gauntlet/c3/benchmark.md](benchmark.md) — C3 decision object + planner: express multiple
capabilities, ordering, explicit insufficiency, confidence; beat B_acc 0.629 by a stated margin
(target >= 0.80); four probes.

## Probes (verbatim)

1. "how much did I spend on food last month, and does that put my Japan trip budget at risk?" ->
   expenses + names the missing budget capability, answers the answerable half, fabricates nothing.
2. "remind me about this on Friday" in expenses, recipes and routes threads -> one capability serves
   all three.
3. "and what about next month?" -> resolves referent without full re-retrieval.
4. "how am I doing?" -> one disambiguating question or a stated default; silent guessing fails.

## Fixture path

- Planner: `orchestrator/planner.py`; execution: `orchestrator/plan_router.py`
- Eval: `gauntlet/eval_c3.py` (B_acc), `gauntlet/eval_c3_probes.py` (probes)
- Traces: `gauntlet/c3/planner-trace.jsonl`, `gauntlet/c3/probe-traces.jsonl`
- Tests: `tests/test_planner.py`

## Output under review

B_acc = 0.9857 (69/70) vs baseline 0.629 (stated margin +0.357, target >= 0.80 met); all four probes
pass with traces; full suite 41 passed.

## Review

(1) VERDICT: MEETS

(2) Pass/fail per probe:
- Probe 1 PASS — planner selects expenses, names #budget as missing, executes the expenses
  capability which answers the seeded $18.50 food spend, and appends an insufficiency line that
  explicitly refuses to invent a budget number (probe trace 1).
- Probe 2 PASS — identical Decision (capabilities=[reminders], ordering=[reminders]) in expenses,
  recipes, and routes threads; one flat capability serves all three (probe trace 2).
- Probe 3 PASS — "and what about next month?" reuses the previous expenses decision with
  retrieval_used=false (probe trace 3).
- Probe 4 PASS — "how am I doing?" returns one disambiguating question and no capability selection
  (probe trace 4).

(3) Single largest gap: the only B_acc miss (r069) is a frozen-corpus label disagreement — the
  planner selects reminders+routes+general for "plan my route to work and remind me to leave early
  if it rains", while the frozen label omitted reminders. The planner's set is the more complete
  reading; the benchmark is kept as-is rather than re-labelled, so the miss is conservative.
