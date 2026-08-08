# Nexus Prime — Personal Assistant Telegram Bot

A high-performance, single-user **Personal Assistant Telegram Bot** deployed on **Railway** with
built-in multi-user extensibility from day one. Nexus Prime orchestrates email, expenses, routes,
recipes, reminders, general questions, and sandboxed code through a **manifest-first capability
registry** and a **retrieve → plan → select-a-set** router powered by LangGraph.

## Architecture

### Layer 1 — Core (`core/`)

- `core/db.py` — AsyncSQLModel + `asyncpg` PostgreSQL engine with automatic SQLite fallback.
- `core/vault.py` — Symmetric authenticated encryption (`Fernet` / AES-256-GCM) for OAuth tokens.
- `core/scheduler.py` — In-process APScheduler engine with dynamic IANA timezone recalculation,
  `run_now` testing triggers, and ambient delivery gating.
- `core/ambient.py` — Trigger policy: proactive delivery only from trigger records; quiet hours
  suppress non-urgent delivery before 09:00 local; urgent triggers still land.
- `core/audit.py` — LLM-as-a-Judge quality observability and capability-gap telemetry. Whole
  conversations are reviewed by Gemini 3.1 Pro every 5 user messages (`ConversationAuditLog`),
  with a special focus on route/maps/bus correctness; `GEMINI_JUDGE_MODEL` overrides the default.
- `core/code_sandbox.py` — Isolated code execution: import allowlist, egress allowlist, secret
  redaction, hard timeout, credential vault unreachable. E2B provider for production; a
  process-isolated local provider for offline runs and tests.
- `core/shared_tools/` — Date/time parsing, coordinate resolution, email presets.

### Layer 2 — Capabilities (`capabilities/`)

Capabilities are declared as **manifests** in `capabilities/manifests/*.yaml` and loaded by
`capabilities/registry.py`. Each manifest declares an id, a retrieval-facing description in the
user's phrasing, typed input/output schemas, a side-effect class (`read`/`write`/`spend`/
`irreversible`), free-form multi-valued tags, preconditions, and a cost hint. Manager tags are
**derived** from manifests — there is no manager enum, class, or routing hop.

- Plugins: email, expenses, routes (live LTA bus arrivals when `LTA_ACCOUNT_KEY` is configured,
  Google Maps + LTA composed into full journey answers with live next departures and a map link),
  recipes, reminders, general, code_exec.
- Retrieval: `capabilities/retrieval.py` — BM25 index over manifest content with top-k shortlists
  and a recovery path when the correct capability sits outside `k`.
- Advisory tag policy: `config/tag-policy.yaml` (unknown tags warn at load).

### Layer 3 — Orchestration (`orchestrator/`)

Routing is **retrieve → plan → select a set**, not a single-label `goto`:

- `orchestrator/planner.py` — Decision object: capability set, ordering, explicit
  `insufficient_capability` with reasons, confidence, and optional disambiguation question. An LLM
  planner runs when API keys are configured, with the deterministic planner as the measured
  offline fallback. Planning is backend-only: the plan and its internal rationale are stored in
  state and logs, never shown to the user. The LLM planner receives recent conversation context,
  and `orchestrator/verify.py` runs a bounded verify/re-plan check after tool execution.
- `orchestrator/plan_router.py` — Executes a Decision through the plugin registry and returns
  `Command(goto=END)` updates.
- `orchestrator/fastpath.py` — Skips planner/insufficiency/composition stages for known, read-only,
  single-capability requests (e.g. next-bus ETA).
- `orchestrator/insufficiency.py` — First-class "I can't": distinct no-integration / needs-human
  messages, gap records, never a fallback from a failed tool call.
- `orchestrator/promotion.py` — Gap → draft → approval pipeline: security validation gates the
  draft **before** any human approval is requested, provenance is recorded in `skills-lock.json`,
  and rollback restores previous manifests.

Human-in-the-loop is preserved via LangGraph `interrupt()` / `Command(resume=...)` for ambiguous
expenses and other consequential writes. The legacy `CapabilityRouter` remains for direct unit
testing.

### CI/CD capability promotion

`.github/workflows/promote-capability.yml` runs validation, then requires a manual approval
environment before `python -m orchestrator.promotion promote <draft>` writes the manifest and
records provenance in `skills-lock.json`.

## Gauntlet loop (frozen benchmarks)

The repository carries a full evaluation loop under `gauntlet/`:

- **Replay set** — `gauntlet/replay-set.jsonl`, 70 trace-backed messages, frozen. Baselines:
  `B_acc` 0.629, `B_cross` 0.214, webhook → first Telegram byte p50 7.3 ms / p95 12.6 ms (local,
  mocked outbound network).
- **Component benchmarks** — `gauntlet/c1/` through `gauntlet/c8/`, each with a frozen benchmark,
  Builder brief, Blind Critic review, probe traces, and a lock file in `gauntlet/locks/`.
- **Current planner result** — B_acc 0.986 (69/70), stated margin +0.357 over the 0.629 baseline;
  fast path p50 ~8 ms; retrieval recall@5 ≥ 0.99 and precision@5 = 1.00 on the padded registry.

## Running Tests

```bash
pytest tests/ -v
```

## Running Locally

Set up environment variables by copying `.env.example`:

```bash
cp .env.example .env
```

Run the FastAPI Uvicorn server locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Documentation & Architecture Specs

- v1.0 Core Architecture RFC: [spec.md](spec.md)
- v2.0 Capability-Gap Handling & Telemetry RFC: [spec-capability-gaps.md](spec-capability-gaps.md)
- Domain & architecture glossary: [CONTEXT.md](CONTEXT.md) and [map.md](map.md)
- Capability orchestration recipes: [capabilities/RECIPES.md](capabilities/RECIPES.md)
- Gauntlet loop status and lock files: [gauntlet/loop-status.md](gauntlet/loop-status.md)
