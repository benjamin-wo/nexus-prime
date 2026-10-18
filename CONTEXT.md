# Nexus Prime Glossary

The shared language for code, tests and docs. When a term here and a name in code disagree, fix the code. The build plan is [`docs/PLAN.md`](docs/PLAN.md).

## Product

- **Surface**: a way the user reaches the agent. There are two: **Telegram** (quick capture on the phone) and the **Web cockpit** (reviewing and managing money). Both call the same agent and the same use cases.
- **Owner**: the user who runs the deployment and issues invites. **Member**: an invited user. Every user's data is strictly private; there are no shared ledgers.
- **Invite**: a single-use token, valid for 24 hours, that lets one person sign in to the web cockpit with Telegram login.

## Ledger

- **Money**: an exact amount (`NUMERIC(19,4)`) plus an ISO 4217 currency code. Never a float.
- **Home currency**: the currency a user's totals and budgets are reported in.
- **Transaction**: one movement of money, with a **direction** of `in`, `out` or `move`. Income, expenses and moves share one table.
- **Source**: where a transaction came from: `text`, `photo`, `email`, `import` or `manual`.
- **Transaction source record**: the `(user, source, external_id)` key for anything ingested from outside (an email message, a statement row). It outlives a deleted transaction, so it doubles as the **tombstone** that stops the same item being imported again.
- **Revision**: a snapshot taken on create, edit, delete or restore. Undo and history are built from revisions.
- **Soft delete**: setting `deleted_at` instead of removing the row, so a delete can be restored.
- **Split**: one participant's share of a transaction paid by the user. An unpaid split is an **IOU**.
- **Settlement**: money in that pays off all or part of a split.
- **Category**: one per transaction, from the user's own list (twelve defaults to start, plus any they add; one can be merged into another or deleted, except Other and Income). A named category wins, then a rule, then the model's best guess; anything left is **Other** (spending) or **Income** (money in). Deleting one moves its transactions to another category the user picks (Other by default).
- **Category rule**: a pattern that suggests a category, with a stored explanation. A user's correction never silently rewrites a rule.
- **Wallet**: a named place money sits, kept as a label: Nexus tracks what moves in and out, not a balance. Every user has one **Spending** wallet (their main account, the one budgets watch; it can't be deleted). Others are an investment, savings, card or other wallet, with optional match words for imports. Deleting one repoints its moves to a wallet the user picks.
- **Move**: money between two of the user's own wallets (a transaction with direction `move`). It is never spending and never income, has no category, and is left out of budgets, spending, income, cash flow, trips, subscriptions and update messages. Paying a card bill is a move to the Card wallet, so card purchases (expenses) are not counted twice. Paying a friend is not a move; it stays an expense with a split. Nexus only records moves; it never makes one.

## Planning (forecasts, never ledger entries)

- **Forecast**: an expected future transaction. Forecasts produce reminders and projections only; they are never written to the ledger.
- **Recurrence rule**: a repeating pattern proposed after 3 similar transactions and applied only once the user accepts it.
- **Subscription**: a recurring charge with a renewal date and annualised cost. Never cancelled by the app.
- **Bill**: a due date with an optional amount and recurrence. Each due date is a **bill occurrence** that can be snoozed or marked paid. Never paid by the app.
- **Salary schedule**: pay cadence and baseline amount, as reported by the user in chat. Never inferred from transactions or statements.
- **Budget**: a monthly limit, overall or per category, with alerts at 50%, 80% and 100%. No rollover.
- **Cash-flow calendar**: expected money in and out per day and the net movement. Never a predicted balance.
- **FX rate**: a dated rate from Frankfurter. A conversion uses the latest rate on or before the transaction date and shows that date. A missing rate means "conversion unavailable", never a substitute.

## Travel

- **Trip**: a destination with dates, a currency and an optional budget, that keeps its bookings, plans, ideas and money together. Its page has four tabs: Plan, Ideas, Money and Prep. Nexus never books anything.
- **Booking**: a flight, stay, train or ticket. It sits at its time on its day, and its time isn't ours to move. Read from an email or a screenshot, or added by hand.
- **Plan**: something the user means to do on a day, such as dinner or a tour. A time is optional. A plan is an `activity` entry with a day.
- **Idea**: a place saved with no day yet (an `activity` entry with no day, kept in a list such as Food or Nightlife). Putting it on a day makes it a plan; taking it off a day makes it an idea again.
- **Next up**: the one thing to do next on a trip, shown as a strip under its cover with a button: the first gap while planning, the next booking in the last week, what's next today while it's on, who still owes you after it.
- **Stop**: a place a trip is in, such as Tokyo then Kyoto, with the days it is there. The day one stop ends and the next begins is the travel day. Stops follow the hotel stays (grouped by city) until the user edits and saves their own.
- **Suggested label**: a day's name worked out from where its places are and what they are ("Gion · temples & food"), shown with a Suggested chip until the user accepts or types their own. A label the user typed always wins; a suggestion is never saved by itself.
- **Search scope**: where a search for a trip looks: the whole trip, one of its **stops**, or near a day. Near a day, Google Maps is also asked to lean towards a circle round that day's places. The circle is worked out when the search is made and never stored. A scope changes where a search looks, never how many credits it costs.
- **Merged results**: the finder's one list of places, each once: a Google Maps result and a guide idea for the same place are one card, with the rating, the guide's words and source link, and a tag for each that found it.
- **Research into ideas**: saving a trip research's areas as **ideas** on a trip, each under a list named after its area, skipping what is already there and matching Google Maps places when one clearly fits. The research's city is offered as a **stop**, with a confirmation that says what it changes. Nothing is booked.
- **Own pin**: a point the user dropped on the Ideas map, kept with its idea. It is the user's own coordinate, so it is stored; Google's coordinates are fetched with each place and never kept.

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
- **Memory**: what Nexus keeps about a user, quietly and per user. *In-context*: the conversation and a snapshot of their money, given each turn. *Semantic*: facts ("Ann is my sister"). *Procedural*: how they like things done ("split dinners with Ann 50/50"). *Episodic*: dated summaries of what happened. Only from the user's own words; never instructions; changes to data still ask first. Visible and deletable in Settings.
- **Statement import**: upload → parse → preview (duplicates and unclear rows flagged) → confirm → save. Nothing is saved without confirmation.
- **Receipt**: an image or file in the private bucket, attached to a transaction, downloadable only through a short-lived authorised link, and purged 30 days after its transaction is deleted.

## Platform

- **Use case**: an application-layer function such as `log_expense` or `set_budget`. The only entry point for tools, routes and jobs.
- **Tenant**: the user a request acts for, always taken from the authenticated principal, never from request or model arguments.
- **Forwarding address**: a user's own AgentMail inbox (`nexus-…@agentmail.to`) they forward receipts to from any mail provider. Read by the email sweep like a connected mailbox; an email connection with provider `forward`.
- **Subscription**: a recurring payment spotted in the ledger (three regular, similar charges from one merchant) and tracked once the user agrees. Stored in `subscriptions` as proposed, active or dismissed; a dismissed one is never proposed again. Different from a **bill**, which is a reminder the user sets up.
- **Cash flow**: net money movement per day in the home currency. Days so far show what was logged; days from today show what's expected from bills (unless marked paid), tracked subscriptions and payday. It is never a balance: Nexus doesn't know account balances.
- **Telegram updates**: how often a user hears about their transactions: as they happen, hourly, 3 times a day, once a day at 21:00 (the default), or off. Summaries are due at fixed local times outside quiet hours.
- **Job**: a row in the `jobs` table, claimed by a worker with `FOR UPDATE SKIP LOCKED`. Its **dedupe key** makes every side effect (reminder, sweep, import) happen at most once.
- **Leader lease**: a Postgres advisory lock held by one job runner so scheduling happens in one place.
- **Legacy import**: the one-time script that reads the old database read-only and maps its history into the new schema (M3).
