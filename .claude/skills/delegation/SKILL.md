---
name: delegation
description: How to hand work to sub-agents in this repo, choose the model and effort for each job, and escalate when a cheap run falls short. Use whenever you're about to delegate, plan a multi-step job, or the user asks to tune or calibrate sub-agents.
---

# Delegating work to sub-agents

The main session (the orchestrator) plans, judges and integrates. Sub-agents do the work. Every sub-agent job gets the cheapest configuration that does it well.

## The rungs

| Rung | Agent | Model, effort | Use for |
|---|---|---|---|
| 0 | `quick` | Haiku, low | Lookups, code searches, summarising a few files, mechanical edits |
| 1 | `worker` (default) | Sonnet, medium | Ordinary implementation and tests in one area, refactors, docs, fixing check failures |
| 2 | `worker-deep` | Sonnet, high | Multi-layer changes, non-obvious bugs, migrations, job-queue or concurrency work |
| 3 | `architect` | Opus, medium | Design, reviews of money/auth/tenant isolation/security, milestone plans, jobs both workers missed |

A sub-agent with no agent type picked runs on Sonnet (`CLAUDE_CODE_SUBAGENT_MODEL` in `.claude/settings.json`).

## Choosing a rung (the orchestrator is the judge)

1. Look up the job's type in **Calibrated defaults** below. If it's there, use that rung.
2. Otherwise, start from `worker` and adjust:
   - **Down to `quick`:** the answer is a fact to find or text to move, and checking it is trivial.
   - **Up to `worker-deep`:** it spans several layers, the cause is unknown, or a wrong answer is expensive to spot.
   - **Up to `architect`:** it's a decision rather than a task, or it touches money, auth, tenant isolation, secrets or prompt-injection defences.
3. Say in one line which rung you chose and why when you delegate.

Never delegate the final judgement. Check every sub-agent's work yourself (read the diff, rerun the checks) before reporting it as done.

## Escalation and calibration

When a job type has no calibrated default, or a default stops working well, calibrate it:

1. Run the job on the lowest rung that could plausibly do it.
2. Judge the result on quality (correct, complete, tests pass, matches conventions), speed and cost.
3. If it fell short, run the same job one rung up (or the same model at higher effort). Stop at the first rung whose result is good enough; go to the top only if needed.
4. Record every run in [`docs/AGENT_TUNING.md`](../../../docs/AGENT_TUNING.md): date, job type, rung, outcome, rough time and tokens, and what went wrong.
5. Pick the best compromise, usually the cheapest rung that passed, and add or update its row in **Calibrated defaults** below.

Calibrate a job type once, not on every job. Re-calibrate only when a default fails twice. Escalation costs more the first time and saves on every job after.

## Calibrated defaults

Job types measured with the steps above, and the rung that won. Keep this table short and current.

| Job type | Rung | Why (from the log) |
|---|---|---|
| _none yet_ | | |
