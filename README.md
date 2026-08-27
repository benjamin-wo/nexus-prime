# Nexus Prime — Personal Assistant Telegram Bot

A **general-purpose agentic assistant** deployed on **Railway**, living on **Telegram** and a
**web cockpit/dashboard**. One tool-chaining agent fulfils user requests using **skills declared
as markdown files with frontmatter** — adding a skill means dropping a folder, no code changes.

## Architecture

### The agent (`orchestrator/agent_node.py`)

A single agentic loop is the brain. It receives the full conversation history, a skill index,
and every tool declared by installed skills; it chains tools (bounded rounds) until the request
is fulfilled. Around it sits a **deterministic safety kernel** that never delegates to the LLM:

- termination/closing intents ("stop") end the turn;
- media turns attempt receipt-expense extraction first, then describe via the vision model;
- incoming-money statements are parsed and written deterministically (including IOU settlement
  on friend repayments) — money writes never depend on the model;
- pending bus-stop disambiguation answers stay inside the live bus-arrival handler;
- unsupported transactional categories (bank transfers, bookings, smart home, ...) are refused
  honestly and logged as capability-gap telemetry;
- self-diagnosis questions ("why did you...", "is this broken?") are answered from the bot's own
  integration health, not routed into a random skill's flow;
- the identity guard overrides any model-supplied `user_id` with the authenticated one.

Human-in-the-loop is preserved via LangGraph `interrupt()` / `Command(resume=...)` for ambiguous
expenses and other consequential writes.

### Skills (`skills/<name>/SKILL.md`)

Skills are the authoring surface — **markdown with YAML frontmatter** (Claude-style):

```markdown
---
name: transit
description: Live Singapore bus timings and transit journeys.
tags: [transit, bus]
side_effect: read        # read | write | spend | irreversible
tools:
  - get_bus_timings      # resolved against the tool registry by name
  - transit_journey
---

# Bus timings & routes
Step-by-step guidance the agent loads on demand via the `load_skill` tool.
```

- `core/skill_registry.py` — parses frontmatter, discovers skills, resolves declared tools
  against the **tool registry** (the `@tool` callables across `capabilities/*/tools.py` and a
  skill's own optional `tools.py`), and exposes the skill index + progressive-disclosure loader.
- Installed skills: web-research, expenses, transit, email, reminders, recipes-groceries,
  memory (points/miles), bug-logging, daily-briefing, whiteboard-planning, composed-recipes,
  code-exec (kernel-gated to admins).
- **Adding a skill = dropping `skills/<name>/SKILL.md`** (plus `tools.py` if it needs new
  executable actions). No registry edits, no redeploy.

### Layer 1 — Core (`core/`)

- `core/db.py` — AsyncSQLModel + `asyncpg` PostgreSQL engine with automatic SQLite fallback.
- `core/vault.py` — Symmetric authenticated encryption (`Fernet` / AES-256-GCM) for OAuth tokens.
- `core/scheduler.py` — In-process APScheduler engine with dynamic IANA timezone recalculation,
  `run_now` testing triggers, and ambient delivery gating.
- `core/ambient.py` — Trigger policy: proactive delivery only from trigger records; quiet hours
  suppress non-urgent delivery before 09:00 local; urgent triggers still land.
- `core/audit.py` — LLM-as-a-Judge quality observability and capability-gap telemetry. Whole
  conversations are reviewed by Gemini 3.1 Pro every few user messages (`ConversationAuditLog`);
  `GEMINI_JUDGE_MODEL` overrides the default.
- `core/code_sandbox.py` — Isolated code execution: import allowlist, egress allowlist, secret
  redaction, hard timeout, credential vault unreachable. E2B provider for production; a
  process-isolated local provider for offline runs and tests.

### Surfaces (`app/`)

- **Telegram** (`app/ingress.py`) — webhook ingress, slash commands, media download, inline
  keyboard HITL confirmations, proactive push delivery.
- **Web cockpit** (`app/dashboard_api.py`, `showcase/`) — metrics cards, transaction ledger,
  whiteboard canvas, and a Copilot drawer wired to the same agent graph.

Multi-tenant from day one: every tool is user-scoped through the identity guard, and
`admin_only_capabilities` (config) gates sensitive skills such as `code-exec`.

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
