# Nexus Prime Glossary

The shared language for code, tests and docs. When a term here and a name in code disagree, fix the code. The build plan is [`docs/PLAN.md`](docs/PLAN.md).

## Product

- **Surface**: a way the user reaches the agent. There are two: **Telegram** (quick capture on the phone) and the **Web cockpit** (reviewing and managing money). Both call the same agent and the same use cases.
- **Owner**: the user who runs the deployment and issues invites. **Member**: an invited user. Every user's data is strictly private; there are no shared ledgers.
- **Invite**: a single-use token, valid for 24 hours, that lets one person sign in to the web cockpit with Telegram login.

## Ledger

- **Money**: an exact amount (`NUMERIC(19,4)`) plus an ISO 4217 currency code. Never a float.
- **Home currency**: the currency a user's totals and budgets are reported in.
- **Transaction**: one movement of money, with a **direction** of `in` or `out`. Income and expenses share one table.
- **Source**: where a transaction came from: `text`, `photo`, `email`, `import` or `manual`.
- **Transaction source record**: the `(user, source, external_id)` key for anything ingested from outside (an email message, a statement row). It outlives a deleted transaction, so it doubles as the **tombstone** that stops the same item being imported again.
- **Revision**: a snapshot taken on create, edit, delete or restore. Undo and history are built from revisions.
- **Soft delete**: setting `deleted_at` instead of removing the row, so a delete can be restored.
- **Split**: one participant's share of a transaction paid by the user. An unpaid split is an **IOU**.
- **Settlement**: money in that pays off all or part of a split.
- **Category rule**: a pattern that suggests a category, with a stored explanation. A user's correction never silently rewrites a rule.

## Planning (forecasts, never ledger entries)

- **Forecast**: an expected future transaction. Forecasts produce reminders and projections only; they are never written to the ledger.
- **Recurrence rule**: a repeating pattern proposed after 3 similar transactions and applied only once the user accepts it.
- **Subscription**: a recurring charge with a renewal date and annualised cost. Never cancelled by the app.
- **Bill**: a due date with an optional amount and recurrence. Each due date is a **bill occurrence** that can be snoozed or marked paid. Never paid by the app.
- **Salary schedule**: pay cadence and baseline amount, as reported by the user in chat. Never inferred from transactions or statements.
- **Budget**: a monthly limit, overall or per category, with alerts at 50%, 80% and 100%. No rollover.
- **Cash-flow calendar**: expected money in and out per day and the net movement. Never a predicted balance.
- **FX rate**: a dated rate from Frankfurter. A conversion uses the latest rate on or before the transaction date and shows that date. A missing rate means "conversion unavailable", never a substitute.

## Agent

- **Agent**: one LangGraph tool-chaining loop with a bounded number of steps. Tools call use cases; they never touch the database directly.
- **Skill**: a `skills/<name>/SKILL.md` folder with frontmatter, loaded on demand. Adding a skill means adding a folder.
- **Safety kernel**: deterministic checks that run before or around the model and never depend on it:
  - **Identity guard**: overwrites any `user_id` the model supplies with the authenticated user.
  - **Termination intent**: "stop" or "cancel" ends the turn.
  - **Media turn**: a photo is treated as a receipt first.
  - **Income write**: plain phrasings are parsed and saved deterministically; anything else goes to the model's `record_income` tool, which always asks the user to confirm, and the income skill tells it to ask rather than guess.
  - **Guardrail policy**: payments, transfers and cancellations are refused honestly and logged as a **capability gap**.
  - **Self-diagnosis**: "is this broken?" is answered from the app's own health checks.
- **HITL (human in the loop)**: a confirmation step, using LangGraph `interrupt()` and resume, before consequential or ambiguous writes. Telegram shows buttons; the web shows a dialog.

## Ingestion

- **Mailbox connection**: a Gmail account the user connected, only when they asked to automate logging. Its refresh token is stored encrypted only.
- **Email sweep**: a job every 15 minutes that asks each connected mailbox for receipt-like emails only. A cheap model screens them (EMAIL_CLASSIFIER_MODEL on OpenRouter, or the main model), the main model reads likely receipts into drafts, and the user confirms each one. The first sweep looks back 30 days.
- **Email log**: what became of each email a sweep read (logged, waiting, skipped, not a receipt, no amount, already logged), kept as sender, subject and outcome only, never the body.
- **Statement import**: upload → parse → preview (duplicates and unclear rows flagged) → confirm → save. Nothing is saved without confirmation.
- **Receipt**: an image or file in the private bucket, attached to a transaction, downloadable only through a short-lived authorised link, and purged 30 days after its transaction is deleted.

## Platform

- **Use case**: an application-layer function such as `log_expense` or `set_budget`. The only entry point for tools, routes and jobs.
- **Tenant**: the user a request acts for, always taken from the authenticated principal, never from request or model arguments.
- **Forwarding address**: a user's own AgentMail inbox (`nexus-…@agentmail.to`) they forward receipts to from any mail provider. Read by the email sweep like a connected mailbox; an email connection with provider `forward`.
- **Subscription**: a recurring payment spotted in the ledger (three regular, similar charges from one merchant) and tracked once the user agrees. Stored in `subscriptions` as proposed, active or dismissed; a dismissed one is never proposed again. Different from a **bill**, which is a reminder the user sets up.
- **Telegram updates**: how often a user hears about their transactions: as they happen, hourly, 3 times a day, once a day at 21:00 (the default), or off. Summaries are due at fixed local times outside quiet hours.
- **Job**: a row in the `jobs` table, claimed by a worker with `FOR UPDATE SKIP LOCKED`. Its **dedupe key** makes every side effect (reminder, sweep, import) happen at most once.
- **Leader lease**: a Postgres advisory lock held by one job runner so scheduling happens in one place.
- **Legacy import**: the one-time script that reads the old database read-only and maps its history into the new schema (M3).
