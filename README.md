# Nexus Prime — Expense & Finance Telegram Bot

A **finance-focused agentic assistant** deployed on **Railway**, living on **Telegram** and a
**web cockpit/dashboard**. One tool-chaining agent fulfils expense and finance requests using
**skills declared as markdown files with frontmatter** — adding a skill means dropping a folder,
no code changes.

## Architecture

### The agent (`orchestrator/agent_loop.py`)

A single agentic loop is the brain. It receives the full conversation history, a skill index,
and every tool declared by installed skills; it chains tools (bounded rounds) until the request
is fulfilled. Around it sits a **deterministic safety kernel** that never delegates to the LLM:

- termination/closing intents ("stop") end the turn;
- media turns attempt receipt-expense extraction first, then describe via the vision model;
- incoming-money statements are parsed and written deterministically (including IOU settlement
  on friend repayments) — money writes never depend on the model;
- unsupported transactional categories (bank transfers, bookings, ...) are refused
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
name: expenses
description: Track and categorize personal expenses.
tags: [expenses, finance]
side_effect: write       # read | write | spend | irreversible
tools:
  - add_expense          # resolved against the tool registry by name
  - list_expenses
---

# Expense tracking
Step-by-step guidance the agent loads on demand via the `load_skill` tool.
```

- `core/skill_registry.py` — parses frontmatter, discovers skills, resolves declared tools
  against the **tool registry** (the `@tool` callables across `capabilities/*/tools.py` and a
  skill's own optional `tools.py`), and exposes the skill index + progressive-disclosure loader.
- Installed skills: expenses, email, web-research.
- **Email sweep** (`capabilities/email/`): Periodically polls connected Gmail/Outlook mailboxes
  for receipts and bills. A **Jev classifier** (`typesafe/jev-1.13` via the OpenRouter Decisions
  API) pre-filters each email as transaction/non-transaction. Emails flagged as transactions
  are then extracted by the chat model, which produces a concise ≤50-word description stored
  in the transaction's `notes` field. The final `is_transaction` gate is the LLM itself — Jev
  is the cheap System One pre-filter. Configured via `JEV_MODEL` (default `typesafe/jev-1.13`);
  requires `OPENROUTER_API_KEY`.
- **Adding a skill = dropping `skills/<name>/SKILL.md`** (plus `tools.py` if it needs new
  executable actions). No registry edits, no redeploy.

### Layer 1 — Core (`core/`)

- `core/db.py` — AsyncSQLModel + `asyncpg` PostgreSQL engine with automatic SQLite fallback.
- `core/vault.py` — Symmetric authenticated encryption (`Fernet` / AES-256-GCM) for OAuth tokens.
- `core/scheduler.py` — In-process APScheduler engine with dynamic IANA timezone recalculation,
  `run_now` testing triggers, and ambient delivery gating.
- `core/ambient.py` — Trigger policy: proactive delivery only from trigger records; quiet hours
  suppress non-urgent delivery before 09:00 local; urgent triggers still land.
- `core/audit.py` — Capability-gap telemetry logging for unsupported feature requests.

### Surfaces (`app/`)

- **Telegram** (`app/ingress.py`) — webhook ingress, slash commands, media download, inline
  keyboard HITL confirmations, proactive push delivery.
- **Web cockpit** (`app/dashboard_api.py`, `showcase/`) — metrics cards, transaction ledger,
  and analytics dashboard wired to the same agent graph.

Multi-tenant from day one: every tool is user-scoped through the identity guard.

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

## Documentation

- Domain & architecture glossary: [CONTEXT.md](CONTEXT.md) and [map.md](map.md)
