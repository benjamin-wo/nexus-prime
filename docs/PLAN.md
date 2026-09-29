# Nexus Prime — Clean-Start Build Plan

## Summary

Nexus Prime is a personal finance assistant with two surfaces over one agent:

- **Telegram** is used on the phone for quick capture: text and photo expenses, splitting bills, quick questions about spending.
- **Web cockpit** is used to manage and review money: ledger, analytics, bulk edits, import, export and chat.

This is a rewrite in an empty repo. The old plan (`expense-agent-rebuild`) had to work around legacy code, a messy checkout and a live schema it could not change. Most of that plan was about protecting what already existed: checkpoint gates, legacy Alembic baselines, clone-backed cutover.

A clean start removes almost all of that. The plan therefore keeps the old **product decisions** and **safety rules** but drops the **legacy-compatibility work**. It also ships in thin, usable, deployable slices instead of one big cutover.

---

## 1. Core capabilities (carried over from the old project)

### Capture
- Log expenses from free text ("coffee 5.50 at Starbucks").
- Extract expenses from a receipt photo using a vision model, with confirmation for ambiguous cases.
- Scan connected Gmail/Outlook inboxes for receipts. A cheap classifier (Jev via OpenRouter) filters emails first, then the LLM extracts the expense. Deleted emails must never be re-imported.
- Record income (salary, repayments, reimbursements) through a deterministic parser rather than LLM guesswork.
- Split bills with friends and track IOUs. A friend's repayment settles their IOU.

### Manage
- Query, edit, delete and restore transactions, with undo for the last write.
- Unified ledger of money in and money out, with filters, search and sorting.
- Bulk operations on the web, with a confirmation step and undo.
- Metrics, dashboard and insights.

### Agent
- One tool-chaining agent with a bounded number of steps, shared by both surfaces.
- Skills are `skills/<name>/SKILL.md` files with frontmatter, loaded on demand. Adding a skill means dropping in a folder.
- A **safety kernel** of deterministic checks that never go through the LLM:
  - identity guard (the model can never choose which user it is acting for)
  - stop/cancel intents
  - media-first receipt handling
  - deterministic income writes
  - refusal of unsupported transactions (payments, transfers) plus logging of capability gaps
  - self-diagnosis
- Human-in-the-loop confirmation for consequential writes, using LangGraph `interrupt()` and resume. Telegram shows buttons; the web shows a dialog.

### New features (owner-approved)
- Monthly budgets, overall and per category, with 50/80/100% alerts and no rollover.
- Editable categories plus explainable suggestion rules. A correction never silently rewrites a rule.
- Recurrence detection: suggest a recurring rule after 3 similar transactions. Once approved, a rule creates forecasts and reminders only, never actual expenses.
- Subscriptions: renewal date, annualised cost, reminders 7/3/1 days before, and a flag when the price changes. Never cancelled automatically.
- Bills: due date, optional amount and recurrence, reminders 7/3/1 days before, snooze and mark-paid. Payments are never initiated.
- Salary is reported by the user in chat, never inferred. Pay schedule is flexible; weekend paydays shift to Friday. One cheerful check-in on payday. The user confirms before the baseline amount changes.
- Multi-currency: per-user home currency and dated Frankfurter rates. Show when each rate took effect; never substitute a later rate.
- Bank statement import, files only (CSV, then PDF with OCR): preview, dedupe, explicit confirmation before saving. Salary is never inferred from a statement.
- Receipt archive in private object storage, soft-deleted along with its transaction and purged after 30 days. Downloads only through short-lived authorised links.
- CSV export of the current filtered view, with no file links and protection against formula injection.
- Cash-flow calendar showing expected money in and out and the net movement. Never a predicted balance.
- Invite-only multi-user web access: Telegram login, single-use invites that expire after 24 hours, strictly private data per user.
- Quick actions: Log expense, Import statement, Add bill, View budgets, Open chat.

### Explicitly out
- Live bank sync or aggregators.
- Making payments.
- Automatically cancelling subscriptions.
- Shared household ledgers.
- Public sign-up.
- Export formats other than CSV.
- Features from the old general assistant: transit, web research, whiteboards, points/miles, generic to-dos.

---

## 2. What changes because this is a clean start

| Old plan | New plan | Why |
|---|---|---|
| Wave 0: checkpoint the dirty checkout | **Dropped** | There is no existing code. |
| Legacy Alembic baseline matched to the prod schema | **Alembic from the first commit** | We own the schema now. |
| Keep the old tables (`ExpenseTransaction`, `IncomeTransaction`, tombstones, undo snapshots) | **New, cleaner model** (§4) | The old model had float money, separate in/out tables, Telegram ID as primary key, and JSON splits. |
| Keep LangGraph checkpoints and encrypted OAuth tokens across the rebuild | **Start fresh**. Users reconnect email once. | Avoids tying ourselves to the old key and checkpointer versions. |
| Big-bang cutover with clone rehearsal | **One-time read-only import from the old DB, then move the webhook** | Far less risk and effort. |
| 21 todos in 5 waves before anything ships | **Milestones, each deployable and usable** | Get feedback early. |

**Decided (2026-09-28):** use a **new Railway Postgres** for the new service, and bring history across with a one-time script that only *reads* the old database (§6, M3). The old database stays untouched as an archive and as the rollback path.

---

## 3. Architecture

### Stack
- **Backend:** Python 3.12, `uv`, FastAPI, SQLAlchemy 2.0 async with `asyncpg`, Pydantic v2, Alembic.
- **Agent:** LangGraph plus `langgraph-checkpoint-postgres`, with exact versions pinned. The model provider sits behind a single `llm/` adapter.
- **Telegram:** `python-telegram-bot`, webhook mode.
- **Jobs:** a Postgres-backed `jobs` table. A worker claims jobs with `FOR UPDATE SKIP LOCKED` and holds an advisory-lock leader lease. No in-memory APScheduler, so nothing fires twice.
- **Web:** React, TypeScript, Vite, TanStack Query, Vitest and Playwright, in `web/`, built to static files and served by FastAPI or as a separate Railway service.
- **Storage:** a Railway S3-compatible private bucket for receipts and statement files.
- **CI:** GitHub Actions running ruff, mypy, pytest against a Postgres service container, the web build, Vitest and Playwright.

### Layout

```
nexus-prime/
  src/nexus/
    domain/          # pure: entities, value objects (Money), policies. No I/O.
    application/     # use cases: log_expense, split_bill, set_budget, import_statement...
    infra/
      db/            # SQLAlchemy models, repositories, Alembic env
      storage/       # S3 adapter
      fx/            # Frankfurter client + rate cache
      email/         # Gmail/Outlook + Jev classifier
      llm/           # model adapter
    agent/           # LangGraph graph, safety kernel, tool wrappers over use cases
    skills/          # SKILL.md folders
    channels/
      telegram/      # webhook, normalisation, callbacks, keyboards
      web/           # FastAPI routers, auth, sessions
    jobs/            # job runner + handlers (reminders, email sweep, purge)
  migrations/        # Alembic
  web/               # React app
  tests/
    unit/ integration/ agent/ e2e/
  docs/  DESIGN.md  CONTEXT.md
```

**Dependency rule:** `domain` ← `application` ← (`agent`, `channels`, `jobs`) → `infra`. Tools and routes only ever call use cases. The tenant always comes from the authenticated principal, never from request or model arguments.

---

## 4. Data model (v1)

- **Money** is `NUMERIC(19,4)` plus an ISO currency code. Never float.
- **Every row** has a `user_id`, and every query is scoped to it. Child rows reference their parent by `(id, user_id)`, so the database itself rejects cross-tenant links.

| Table | Key fields |
|---|---|
| `users` | id (uuid), telegram_user_id (unique), telegram_chat_id, timezone, home_currency, role (owner/member), created_at |
| `transactions` | id, user_id, direction (in/out), amount, currency, occurred_at, merchant/counterparty, category_id, notes, status (confirmed/pending), source (text/photo/email/import/manual), deleted_at |
| `transaction_sources` | user_id, source, external_id (unique per user+source), transaction_id nullable. Kept after a delete, so it also acts as the "don't re-import" tombstone. |
| `transaction_revisions` | transaction_id, kind (create/edit/delete/restore/split), before (jsonb), created_at, undone_at. Powers undo (newest open revision first) and history. |
| `splits` | transaction_id, participant_name, share_amount. What is still owed is computed from settlements, never stored, so deleting or undoing a repayment reopens the IOU. |
| `settlements` | split_id, income_transaction_id, amount. Settlements on a deleted income transaction don't count. |
| `categories` / `category_rules` | name, active; rule pattern, priority, explanation |
| `budgets` / `budget_alerts` | month-scoped limits; one alert row per (budget, period, threshold), which makes alerts idempotent |
| `recurrence_rules` | pattern, cadence, status (proposed/accepted/rejected), variable_amount |
| `subscriptions`, `bills`, `bill_occurrences` | schedule, expected amount, reminder offsets, snoozed_until, paid_at |
| `salary_schedules` | cadence spec, baseline amount, timezone |
| `fx_rates` | base, quote, effective_date, rate, provider, fetched_at |
| `receipts` | transaction_id, object_key, content_type, deleted_at, purge_after |
| `statement_imports` / `statement_rows` | file, mapping, parsed rows, fingerprint, row status, confirmed_at |
| `email_connections` | provider, encrypted tokens (key required; the app refuses to start without it) |
| `invites`, `sessions` | token_hash, expires_at, redeemed_at; session id, expires_at, revoked_at |
| `jobs` | kind, run_at, payload, dedupe_key (unique), status, attempts |
| `capability_gaps` | request, intent, tags, channel |

---

## 5. Non-negotiable rules

These are enforced by tests, not by convention.

1. **Tenant isolation.** The identity guard overwrites any `user_id` the model supplies. Every route derives the user from the session. Cross-tenant tests exist for every read, write and download route.
2. **No write without a clear intent.** Consequential or ambiguous writes go through HITL confirmation. Income is parsed deterministically.
3. **Forecasts never touch the ledger.** Recurrence rules, bills, subscriptions and salary schedules only create reminders and projections.
4. **No money movement.** The agent never pays, transfers or cancels anything, and refuses honestly when asked.
5. **Idempotent side effects.** Telegram updates, email messages, reminders and imports are each keyed by a dedupe key.
6. **Schema changes only through Alembic.** The app refuses to start on an unmigrated database. There is no `create_all` at startup.
7. **Secrets fail closed.** A missing encryption key or OIDC config stops startup. Nothing falls back to a random key. The repo is **public**, so secrets never go in the repo, logs or test fixtures.
8. **No fabricated values.** A missing FX rate means "conversion unavailable". Unclear statement rows are flagged, not guessed.

---

## 6. Milestones

Every milestone ends deployed to Railway and usable. Development is test-first: write a failing test, make it pass, move on.

### M0 — Skeleton (about 1–2 days)
- `pyproject` using `uv`, ruff, mypy, pytest; the `src/` layout; `web/` built with Vite.
- Alembic set up with an empty first revision. The app fails at startup if migrations are pending.
- Settings validated by Pydantic, failing closed.
- GitHub Actions CI; `docker-compose` for local Postgres.
- Railway: a new service and a new Postgres; `/healthz`.
- Carry over `DESIGN.md` (the charcoal/ember design system) and write a new `CONTEXT.md` glossary.
- **Done when:** CI is green and the Railway deployment passes its health check.

### M1 — Ledger core (domain + use cases)
- `Money`, `users`, `transactions`, `transaction_sources`, `transaction_revisions`, `categories`, `splits`, `settlements`.
- Use cases: log / edit / delete / restore / undo, log income, split bill, settle IOU, list and filter ledger, summaries.
- **Tests:** unit tests for the domain; integration tests against a throwaway Postgres; tenant-isolation tests.
- **Done when:** every use case passes its tests, including the negative cross-tenant and duplicate-source cases.

### M2 — Agent + Telegram (the MVP)
- A LangGraph agent with tools that call M1 use cases; the skill loader; the safety kernel; HITL.
- Telegram webhook: text, photos (receipt extraction, with the image not stored yet), callbacks, and quick-action buttons.
- **Tests:** agent trajectory tests with a scripted fake LLM; a malicious `user_id` test; replayed Telegram updates; HITL resume.
- **Done when:** you can log, fix and split expenses from Telegram on a test bot.

### M3 — Migrate history + go live on Telegram
- `scripts/import_legacy.py` connects to the old database **read-only** and maps the old tables into the new ones:
  - `UserProfile` → `users`
  - `ExpenseTransaction` and `IncomeTransaction` → `transactions`
  - `split_data` → `splits`
  - IOU tasks → `splits`
  - tombstones → `transaction_sources`
- It is dry-run by default, reports row counts and checksums, and can be run again safely.
- Cutover:
  1. Run the import against a local copy.
  2. Run it for real.
  3. Point the Telegram webhook at the new service.
  4. Stop the old service. It stays deployable for rollback, since its database is untouched.
- **Done when:** counts and totals match the old database for every user, and the bot is live.

### M4 — Web cockpit v1 + auth
- Telegram OIDC login, owner-issued invites (single-use, 24-hour expiry, stored hashed), sessions with expiry and revocation, CSRF and origin checks.
- Pages: dashboard with metrics, the unified ledger (filter/sort/search, bulk delete with undo), a transaction entry sheet, the chat drawer with HITL, and quick actions. Follows `DESIGN.md`.
- CSV export of the filtered view, with neutralised formulas and no links.
- **Tests:** auth negative tests (bad signature, wrong issuer or audience, expired token, reused invite, cross-tenant access); Playwright journeys.

### M5 — Jobs runtime + planning features
- The job runner (leader lease, `SKIP LOCKED`, dedupe keys, quiet hours).
- Budgets and alerts, bills and 7/3/1 reminders, the salary schedule plus payday check-in, category rules.
- **Tests:** exact threshold boundaries, timezone and month rollover, two runners firing exactly once, snooze/paid then next occurrence.
- Shipped in parts: **M5a** the job runner plus budgets and alerts. Atomic claims and per-slot dedupe keys make a leader lease unnecessary. **M5b** bills and reminders, with Budgets and Bills together on one Plan page. **M5c** the salary schedule and payday check-in, on the same Plan page. **M5d** category rules: a rule files new expenses by merchant or notes, every rule stores why it exists, each transaction records which rule filed it, and a correction only offers a rule change (buttons in Telegram, a prompt on the web) that is saved if the user accepts.

### M6 — Email ingestion + receipt archive
- Gmail/Outlook OAuth connections (encrypted), a sweep job, the Jev pre-filter, LLM extraction, and dedupe through `transaction_sources`.
- Private bucket; receipts attached to photo and email expenses; short-lived download URLs; soft delete, restore, and purge after 30 days.
- **Tests:** a fake S3; a wrong-tenant key; a purge attempted before 30 days; re-sweeping a deleted email does not re-import it.

### M7 — Multi-currency, recurrence, subscriptions, cash flow
- Frankfurter client and cache: use the latest rate on or before the transaction date, and show the effective date. Wire it into metrics, budgets, export and cash flow.
  - Pulled forward after M4: the client (in-memory cache for past days), dashboard totals and category bars in the home currency, per-row home amounts with the dated rate, and export columns. Still to do here: the agent's spending summary, budgets and cash flow, and a persistent rate cache if lookups become a cost.
- Recurrence proposals (3 matches), subscription tracking with price-change flags, and the cash-flow calendar showing net movement only.

### M8 — Statement import
- CSV first, with saved column mappings per bank. Then PDF with OCR.
- Flow: upload → parse → preview (flagged duplicates and unclear rows) → confirm → save. Nothing is saved without confirmation, and income from a statement is never auto-classified as salary.

### M9 — Hardening
- Security review, load checks on the job runner, a backup and restore drill for the new database, and runbook docs.

**Suggested order:** M0–M3 first. That replaces the old bot with better foundations and your history intact. M4–M8 then add features one by one, each shipped as it lands.

---

## 7. Testing strategy

- **Unit:** domain policies such as money arithmetic, budget thresholds, schedule calculation and recurrence matching. Pure and fast.
- **Integration:** use cases and repositories against a real Postgres (a CI service container, or `testcontainers` locally), with the schema built by `alembic upgrade head`.
- **Agent:** a scripted fake LLM for deterministic trajectory tests. A small separate eval set (`evals/`) runs against the real model and is not part of CI.
- **E2E:** Playwright for the web; a Telegram test harness that posts fake updates to the webhook.
- **Negative cases in every milestone:** cross-tenant access, replayed or duplicate events, bad input, provider outages.

## 8. Open questions

1. ~~New database plus import, or keep the old Railway database?~~ **Decided:** new Railway Postgres plus a one-time read-only import. See §2.
2. **Web hosting:** serve `web/` from FastAPI (one service, simpler) or as a separate static service? The default is FastAPI.
3. **LLM provider:** keep the old setup (Gemini, plus OpenRouter for Jev) or standardise on one? The default is to keep it, behind the adapter.
4. ~~Repo visibility~~ **Decided:** the repo stays public. Rule 7 applies in full: secrets, real financial data and logs never enter the repo. The pre-rebuild code is not republished on an archive branch.
