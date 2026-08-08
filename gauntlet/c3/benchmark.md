# C3 — Decision Object + Planner (FROZEN)

Frozen before iteration 1. Do not edit while C3 is open.

## Standard

Anthropic parallel tool use, LangGraph `Command`. The supervisor decision expresses **multiple
capabilities**, an **ordering**, an explicit `insufficient_capability` with reasons, and **confidence**.
Routing is retrieve -> plan -> select a set. Managers are derived tags and never routing hops.

## Success criteria

- Beats baseline B_acc = 0.629 by a stated margin: target B_acc >= 0.80 on the frozen replay set,
  measured by an evaluation harness that runs the planner (deterministic offline fallback) and
  compares the planned capability set with the labelled correct set.
- All four probes pass with traces.
- Existing capabilities keep working; existing tests pass unchanged; HITL via
  `interrupt()`/`Command(resume=...)` preserved.

## Probes (verbatim)

1. "how much did I spend on food last month, and does that put my Japan trip budget at risk?" ->
   expenses + names the missing budget capability, answers the answerable half, fabricates nothing.
2. "remind me about this on Friday" in expenses, recipes and routes threads -> one capability serves
   all three.
3. "and what about next month?" -> resolves referent without full re-retrieval.
4. "how am I doing?" -> one disambiguating question or a stated default; silent guessing fails.

## Fixtures

- Planner: `orchestrator/planner.py`; execution adapter: `orchestrator/plan_router.py`.
- Eval harness: `gauntlet/eval_c3.py`; per-probe traces: `gauntlet/c3/probe-traces.jsonl`.
- Probe fixtures: `gauntlet/c3/probe-state.jsonl` (thread contexts for probes 2-4).

## Notes

The decision object is a dataclass/Pydantic model (id, capabilities with reasons/confidence,
ordering, insufficient_capability, question). The deterministic offline planner is the measured
artifact; an LLM prompt for the same decision shape is included for production and marked
"unverified — assumption" (no API keys in this environment).
