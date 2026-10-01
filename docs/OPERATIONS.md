# Operations

How Nexus Prime is configured, secured and deployed. For the product and architecture overview, see the [README](../README.md). When something breaks, see the [runbook](RUNBOOK.md).

## Local development

Requires Python 3.12, [`uv`](https://docs.astral.sh/uv/), Node 22 and Docker.

```bash
docker compose up -d db          # Postgres 16 on localhost:5432
cp .env.example .env
uv sync
uv run alembic upgrade head      # the app refuses to start on an unmigrated database
uv run uvicorn --factory nexus.main:create_app --reload
curl localhost:8000/healthz
```

### Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
TEST_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/postgres uv run pytest
cd web && npm ci && npm run typecheck && npm test && npm run build && npm run e2e
```

Integration tests create and drop a throwaway database per test on the `TEST_DATABASE_URL` server, and are skipped when it is unset.

## Schema changes

Only through Alembic: `uv run alembic revision -m "..."`, then `uv run alembic upgrade head`. A test checks that the migrations produce exactly the schema in `nexus/infra/db/tables.py`.

## Telegram

The channel is on when `TELEGRAM_BOT_TOKEN` is set, which then also requires `TELEGRAM_WEBHOOK_SECRET` and `ADMIN_TELEGRAM_CHAT_ID` (the owner). Only the owner and `TELEGRAM_ALLOWED_USER_IDS` are served, in private chats. Updates arrive at `POST /telegram/webhook`, checked against the secret token and de-duplicated by `update_id`.

The app never registers its own webhook, so deploying it can't take a bot away from another service. `python -m nexus.channels.telegram.register` shows the current webhook and, with `--yes`, points the bot here. See [`CUTOVER.md`](CUTOVER.md) for moving from the old bot, including the one-time history import (`python -m nexus.legacy`).

The model comes from `LLM_PROVIDER` (`openrouter`, `gemini`, `deepseek` or `openai`) with the matching key. With `openrouter`, everything goes through OpenRouter and Gemini is never used, even if a Gemini key is set: `OPENROUTER_MODEL` chats and reads emails, `OPENROUTER_FALLBACK_MODELS` (comma separated) are tried in order if it fails, and `OPENROUTER_VISION_MODEL` reads receipt photos (unset: `OPENROUTER_MODEL`, which must then accept images). With the other providers, the optional fallback is a Gemini `LLM_FALLBACK_MODEL` and receipt photos are read by Gemini. The "are you working?" reply names the model in use. Each turn the model also gets a snapshot of the user's money (this month's totals and top categories, budgets, the next 7 days' bills, subscriptions and payday, who owes them, and the last 5 transactions), built once per turn and capped at 2,000 characters; and once a conversation passes 40 messages, all but about the last 20 are condensed into a rolling summary (by the main model, at most 150 words) and dropped, so long chats keep their thread without growing the prompt. Questions about the ledger ("grab on weekends", "top merchants", "compare with last month") go through a read-only `query_ledger` tool: fixed filters, groupings and measures (no SQL from the model), the acting user's confirmed transactions only, in the home currency, at most 5,000 transactions a period. Each turn the model is offered 11 core tools (logging, finding and changing transactions, income, summaries, `query_ledger`, categories and `load_skill`); loading a skill adds its tools for the next five messages. A tool the model calls without its skill loaded still runs. The kernel refuses a payment only when Nexus is asked to make one ("can you pay…", "pay … now"); "pay X on a date" reaches the model as a bill to remember. Long-term memory: after each text message the service queues a `memory.update` job with the user's last three messages (their own words only, never tool results, emails or receipts). A small model (`MEMORY_MODEL` on OpenRouter; unset, the main model) adds, updates or deletes memories, of three kinds: facts, preferences and dated episodes, at most 300 per user with the oldest episodes dropped first. The job's payload is emptied when it finishes, so the jobs table keeps no copy of what was said. Each turn the model is given the user's facts and preferences, plus the episodes that match the message and the latest few, and follows preferences quietly; nothing remembered can override its rules. Users see and delete memories under Settings → What Nexus remembers. Memory needs the job runner (on in production; `JOBS_ENABLED` elsewhere); without it nothing is remembered. With Telegram on and no usable model configured, the app refuses to start.

Statement import (web: Ledger → Import statement) reads a bank or card CSV up to 2 MB and 5,000 rows. It finds the header row below any account details, suggests which column is the date, description and amount (one signed column or separate out and in columns), and remembers a layout the user saves by the file's header row. The preview saves nothing and marks each row new, a possible duplicate (same amount and direction within a day of a logged transaction), already imported, or unreadable; only the ticked rows are added, in one transaction, with `source=import`. Each row's fingerprint is claimed as its source id, so the same file never adds a row twice, even after an undo. Money in is filed as income, never salary. An import can be undone as a whole from the same page. PDF statements (up to 10 MB, 60 pages) are read with pypdf, keeping each row's text on one line; a locked PDF asks for its password, which is used for that request only. A transaction line starts with one or two dates and ends with an amount: on a card statement a plain amount is spending and "CR" a credit; on an account statement the running balance says which way each amount moved. Dates without a year take the statement date's (a December charge on a January statement is last year's), foreign-currency lines are added to the description, and reference, balance and total lines are left out. The rows are checked against the statement's own previous and closing balances, and the preview says whether they add up. The rows then go through the same preview and import as a CSV; the PDF itself is never stored. Scanned statements (no text layer) aren't read yet; the bank's CSV export works instead.

## Web access

The web API (`/api/...`) is on when Telegram is configured and the public origin is known (`WEB_ORIGIN`, or Railway's `RAILWAY_PUBLIC_DOMAIN`).

- **Sign-in** uses the Telegram Login Widget. The signature is checked with the bot token and must be less than a day old. The bot's domain must be set with @BotFather `/setdomain`.
- **Inside Telegram (Mini App):** the bot's menu button ("Open Nexus", set at startup) and the `/app` command open the web app inside Telegram. It signs in with the launch data Telegram signs for the Mini App (checked with the bot token, less than a day old), so there is no widget or phone number step. The same access rules apply. These sessions use a `SameSite=None; Partitioned` cookie because Telegram's web clients show the app in an iframe, and the CSP allows only `https://web.telegram.org` to embed it.
- **Who can sign in:** the owner (`ADMIN_TELEGRAM_CHAT_ID`) always can. Anyone else needs a single-use invite, valid for 24 hours, from the owner (`/invite` in the bot, or `POST /api/invites`). Tokens are stored only as hashes.
- **Sessions** are HttpOnly, Secure, SameSite=Lax cookies (Mini App: see above) lasting 30 days, and can be revoked by logging out.
- **Writes** must come from the app's own origin and carry the session's `X-CSRF-Token`.
- **Every route** takes the user from the session. Another user's data returns 404.

## Exchange rates

Foreign amounts convert to the user's home currency at the [Frankfurter](https://frankfurter.dev) (European Central Bank) reference rate published on or before the transaction's local date, never a later one. With no rate, the conversion is reported as unavailable rather than guessed. Rates for past days are cached in memory.

## Background jobs

Budget alerts, bill reminders and the payday check-in run on a Postgres-backed job queue inside the app process: `JOBS_ENABLED`, which defaults to on only when `ENVIRONMENT=prod`.

- **Exactly once:** each job is claimed with `FOR UPDATE SKIP LOCKED` under a 20-minute lease, and recurring work is queued once per time slot under a unique dedupe key. Overlapping instances during a deploy don't double-send, and no leader election is needed.
- **Throughput:** up to 5 jobs run at once, one user's jobs always in order, and a full batch is followed straight away by the next. Each job has 90 seconds; one that runs longer is abandoned and retried like a failure. Measured numbers are in [`RUNBOOK.md`](RUNBOOK.md).
- **Retries:** failures back off (2, 4, 8… minutes, capped at an hour) and stop after 5 attempts.
- **Quiet hours:** Telegram messages wait out 22:00–08:00 in the user's timezone.
- **Subscriptions:** every 6 hours a sweep looks at each user's expenses from the last 800 days. When a merchant's latest three charges (reference numbers ignored, one per day, same currency) came weekly, monthly or yearly, each within 20% of the latest, and the next is still due, the user is asked once: **Track it / No**. At most 3 new questions per sweep. A tracked subscription follows new charges; a change of more than 1% is a price change, told once. A "No" or "Stop tracking" keeps the row as dismissed so it's never proposed again. Nothing is ever cancelled.
- **Cash flow** (`GET /api/cashflow?month=YYYY-MM`, the Cash flow page, the `cash_flow` chat tool): per day, logged in/out/net in the home currency up to today (foreign amounts at each day's rate; ones with no rate listed separately), and from today the expected bills (not yet marked paid), tracked subscriptions and payday (with the usual salary, if set), converted at today's rate. Up to 62 days per request. Items without an amount are listed but not counted. Movement only, never a balance.
- **Telegram updates:** every 5 minutes a sweep checks whether each user is due a message. The default is a summary at 21:00 local time. Users can choose hourly (08:00–21:00), 3 times a day (09:00, 14:00, 20:00), as it happens, or off. A summary covers what was logged since the last one, in the home currency, plus receipts from email still waiting. Nothing is sent when nothing happened. Updates as they happen only cover what the chat didn't already confirm, such as web entries and payday logging. With them on, each new receipt from email is asked about right away; otherwise receipts wait for the next summary. The first check for a user only starts counting, so turning updates on never replays history. Settings live in `notification_settings`; no row means the default.
- **Budgets:** monthly limits in the home currency, overall or per category, with no rollover. Every 10 minutes a sweep records each 50/80/100% threshold reached once per budget per month (`budget_alerts`), and messages the highest new one.
- **Bills:** a name, an optional amount, a next due date, and a repeat of once, weekly, monthly or yearly. Monthly bills on the 29th–31st land on the last day of shorter months and come back afterwards. Every 30 minutes a sweep sends the most urgent reminder reached (7, 3 or 1 days before), once each. Reminders carry **Mark paid** and **Snooze 1 day** buttons. Snoozing re-sends the reminder a day later. An unpaid bill shows as overdue for a week, then rolls on to its next due date. Marking a bill paid only records it: nothing is paid and the ledger isn't touched.
- **Salary:** only what the user reports. The pay schedule is one of three: a day of the month (clamped to short months), the last weekday, or every two weeks from a date. Weekend paydays move to the Friday before. On payday, from 09:00, there is one check-in. With a usual salary set, it has **Log** and **Not yet** buttons, and Log records the usual amount once per payday. When the user reports a different salary, the bot asks before changing the usual amount; nothing changes silently.

## Categories

New users get twelve defaults: Dining Out, Groceries, Transport, Shopping, Bills & Utilities, Socialising, Health, Travel, Activities, Subscriptions & Software, Income and Other. Migration 0014 gives existing users the same set: Food & Drink becomes Dining Out and Entertainment becomes Activities (unless the user already has a category by the new name), and missing defaults are added. Migration 0015 folds the old bot's Dining into Dining Out and General into Other: their transactions and rules move over (a budget too, unless the new category already has one), and the old category is archived. No undo history is written for it. Migration 0016 adds Subscriptions & Software for everyone and regroups the rest of the old bot's categories (those with imported transactions) by keyword into the defaults, or Other when nothing fits; Personal Care is kept, and categories users added themselves are left alone. Users can also merge one category into another (Settings, `POST /api/categories/{id}/merge`, or chat): its transactions, rules and budget (unless the target has one) move over and it's archived. Names are unique per user regardless of case; a clash is a 409.

Every new transaction gets a category, in this order: the one the user named, a matching rule, the model's (or the receipt or email reader's) best guess from the user's own categories, then Other for spending and Income for money in. Archived categories aren't used. Transactions logged before 0014 without a category keep none.

## Category rules

A rule files new expenses whose merchant or notes mention a word or phrase (whole words, any case). A merchant match beats a notes match, then the longest pattern wins. A category the user gives always wins, rules never touch income, and rules for archived categories are skipped. Each transaction records the rule that filed it, and each rule stores why it exists, so "why is this in Transport?" has an exact answer.

Rules change only when the user says so. Correcting an expense's category leaves the rules as they are and offers one ("Always file “grab” under Food?", or a change to an existing rule) that is saved only if accepted. Removing a rule archives it: expenses it filed keep their category and can still explain it. A rule never recategorises expenses already logged.

## Receipt archive

Receipt photos sent to the bot are kept in a private S3-compatible bucket. In production that's a Railway bucket, wired in with reference variables:

| Variable | Value |
|---|---|
| `STORAGE_BUCKET` | `${{<bucket>.BUCKET}}` |
| `STORAGE_ENDPOINT` | `${{<bucket>.ENDPOINT}}` |
| `STORAGE_REGION` | `${{<bucket>.REGION}}` |
| `STORAGE_ACCESS_KEY_ID` | `${{<bucket>.ACCESS_KEY_ID}}` |
| `STORAGE_SECRET_ACCESS_KEY` | `${{<bucket>.SECRET_ACCESS_KEY}}` |
| `STORAGE_PATH_STYLE` | `true` only if the bucket's Credentials tab says it uses path-style URLs |

Storage is all or nothing: a partial setup stops startup. With none, photos are still read and logged, but not kept.

- **Keys** are `receipts/<user id>/<receipt id>`, and the database checks that each key belongs to its row's user.
- **Downloads** go through `GET /api/transactions/{id}/receipt`, which checks the session's user owns the transaction, then redirects to a presigned link that expires in 5 minutes. Objects are never public.
- **Lifecycle:** a receipt is attached when its expense is confirmed. It's hidden while the expense is deleted, and comes back if the expense is restored. An hourly job erases it 30 days after the delete, and erases photos that were never confirmed after a day. The file goes first, then the row, so a failed delete is retried.

## Connect Gmail

Offered only when a user asks to automate logging ("can you log my expenses automatically?"). Nothing in the app suggests it otherwise.

**How it works.**
1. The bot's `connect_email` tool, or `POST /api/email/link`, makes a one-time link, valid for 10 minutes and stored as a hash. It opens in the phone's browser, because Google refuses sign-in inside in-app web views.
2. The `/connect/gmail` page names the Nexus account the mailbox will join, so nobody connects their mail through a link someone else sent. It explains Google's "unverified app" screen, then continues to Google's consent screen.
3. The callback spends the link, so a replay connects nothing. It stores the refresh token encrypted, queues a sweep and tells the user in Telegram.

**Sweeps.**
- Every 15 minutes, Nexus asks Gmail only for receipt-like emails, checking at most 25 new ones per mailbox per run.
- A cheap model screens each email, and the main model reads likely receipts into a draft.
- Each new receipt is a Telegram question with **Log it / Skip**. The first sweep instead sends one summary of the last 30 days, linking to the Email page.
- Logged expenses use the `email` source with a dedupe key naming the mailbox and message. An email whose expense was deleted is never imported again, even after disconnecting and reconnecting.
- PDF attachments are kept in the receipt archive.
- If Google revokes access, the mailbox is marked for reconnecting and the user is told once.

**The Email page** (`/email`, and a card on Plan once connected) lists every checked email from the last 30 days with its outcome. It can log, skip, supply a missing amount, or disconnect (which also revokes the grant with Google).

**One-time setup (owner).**
1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. **OAuth consent screen:** choose External. Add the scope `https://www.googleapis.com/auth/gmail.readonly`. Then **Publish app** (In production).
   - Left in Testing, a connection expires after 7 days.
   - Unverified, users see Google's warning, and the app is capped at 100 users.
3. **Credentials → Create OAuth client ID → Web application.** Set the authorised redirect URI to `https://<your domain>/api/email/gmail/callback`.
4. On the service in Railway, set these variables:

| Variable | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | the client ID |
| `GOOGLE_CLIENT_SECRET` | the client secret |
| `TOKEN_ENCRYPTION_KEY` | a Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Comma-separate several to rotate; the first encrypts. |
| `EMAIL_CLASSIFIER_MODEL` | optional: a cheap OpenRouter model for screening (needs `OPENROUTER_API_KEY`) |

Gmail settings are all or nothing, and a missing or malformed encryption key stops startup.

## Forwarding addresses (other mail providers)

For Outlook, iCloud, Yahoo, work email, or Gmail users who'd rather not sign in. Like Connect Gmail, it's offered only when a user asks to automate logging.

**How it works.**
1. The bot's `forward_email` tool makes the user's own inbox on [AgentMail](https://agentmail.to), with an unguessable address like `nexus-3f9a2c7e1b04@agentmail.to`. It's made the first time they ask; asking again gives the same address.
2. The tool gives step-by-step instructions for their provider, including a rule that forwards only emails whose subject says receipt, invoice, order, payment, transaction, paid or purchase. Forwarding a single receipt by hand works too.
3. The regular 15-minute sweep reads new mail at each address and treats it like Gmail: screened, read into a draft, and confirmed by the user. There's no 30-day look-back, because a new address starts empty.

**Setup help.**
- **Provider confirmations.** Gmail (and others) email the forwarding address to confirm it. Mail from Google, Microsoft or Apple whose subject mentions forwarding or confirming is passed on to the user in Telegram, with the code and a button for the provider's own link. Links to any other host are dropped.
- **Test my setup.** The `test_email_setup` tool asks the user to email themselves "Nexus test receipt", which passes the suggested filter. It then checks the address 1, 3 and 6 minutes later, and the user is told in chat when the test arrives.
- **Which senders to filter.** `email_status` lists which senders sent receipts and which sent other mail, for choosing what a filter keeps.
- **Quiet addresses.** If an address receives nothing for 14 days, the user is told once, until mail arrives again.

AgentMail leaves out spam and mail that fails sender authentication. Anyone who learns an address could send it mail, but nothing is logged without the user's confirmation. Disconnecting on the Email page deletes the inbox, so the address stops accepting mail.

**One-time setup (owner).**
1. Create an AgentMail account and an API key.
2. On the service in Railway, set these variables:

| Variable | Value |
|---|---|
| `AGENTMAIL_API_KEY` | the API key |
| `AGENTMAIL_DOMAIN` | optional: a custom domain set up in AgentMail; unset uses AgentMail's own |
| `TOKEN_ENCRYPTION_KEY` | as for Gmail (already set if Gmail is) |

A missing encryption key stops startup when `AGENTMAIL_API_KEY` is set.

## Evaluating the assistant

`src/nexus/evals` scores models on how well the assistant does what users mean. About 100 made-up requests (logging, clarifying questions, income, questions about money, edits, planning, categories, safety, follow-ups and memory) each start from the same seeded user: two months of invented Singapore spending, a split dinner, a budget, bills, a pay schedule, a rule and a subscription, with "now" fixed at Monday 28 September 2026, 2pm. The real agent (kernel, graph, tools and confirmations, which are approved unless a case says otherwise) handles each case, and grading checks the tool calls, confirmations, replies and the data afterwards. Cases the current assistant can't do yet name the M8 part expected to fix them.

```bash
OPENROUTER_API_KEY=... EVAL_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/postgres \
  uv run python -m nexus.evals --model <openrouter model id> [--model ...] [--case q-] [--area ask]
```

It creates and drops its own database on that server, and writes a Markdown report and a JSON file per model to `eval-results/` (ignored by git): pass rate by area and by expected fix, reply time per turn, tokens and cost (from OpenRouter's public price list). The key is read from the environment and never printed. CI runs `tests/integration/test_evals.py` instead, with a scripted model: the cases are well formed, the seed's figures match what the cases expect, and grading passes and fails the right things. Real models are only called on demand.

## Deploy (Railway)

The `nexus-app` service builds from the `Dockerfile`. Its settings live on the service in Railway, not in the repo (Railway no longer reads `railway.toml`):

- Pre-deploy command: `alembic upgrade head`, so migrations run before the new version starts.
- Health check: `/healthz`, timeout 60 s. Restart policy: on failure.
- Variables: `DATABASE_URL` referencing the service's own Postgres, `ENVIRONMENT=prod`, `PORT=8000`.
