# Nexus Prime

Personal finance assistant: quick capture on Telegram and a web cockpit for managing money, over one agent. See [`docs/PLAN.md`](docs/PLAN.md) for the build plan, [`CONTEXT.md`](CONTEXT.md) for the glossary and [`DESIGN.md`](DESIGN.md) for the design system.

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
cd web && npm ci && npm run typecheck && npm test && npm run build
```

Integration tests create and drop a throwaway database per test on the `TEST_DATABASE_URL` server, and are skipped when it is unset.

## Schema changes

Only through Alembic: `uv run alembic revision -m "..."`, then `uv run alembic upgrade head`.

## Telegram

The channel is on when `TELEGRAM_BOT_TOKEN` is set, which then also requires `TELEGRAM_WEBHOOK_SECRET` and `ADMIN_TELEGRAM_CHAT_ID` (the owner). Only the owner and `TELEGRAM_ALLOWED_USER_IDS` are served, in private chats. Updates arrive at `POST /telegram/webhook`, checked against the secret token and de-duplicated by `update_id`.

The app never registers its own webhook, so deploying it can't take a bot away from another service. `python -m nexus.channels.telegram.register` shows the current webhook and, with `--yes`, points the bot here. See [`docs/CUTOVER.md`](docs/CUTOVER.md) for moving from the old bot, including the one-time history import (`python -m nexus.legacy`).

The model comes from `LLM_PROVIDER` (`gemini`, `openrouter`, `deepseek` or `openai`) with the matching key, plus an optional Gemini `LLM_FALLBACK_MODEL`. Receipt photos are read by Gemini. With Telegram on and no usable model configured, the app refuses to start.

## Web access

The web API (`/api/...`) is on when Telegram is configured and the public origin is known (`WEB_ORIGIN`, or Railway's `RAILWAY_PUBLIC_DOMAIN`).

- **Sign-in** uses the Telegram Login Widget. The signature is checked with the bot token and must be less than a day old. The bot's domain must be set with @BotFather `/setdomain`.
- **Inside Telegram (Mini App):** the bot's menu button ("Open Nexus", set at startup) and the `/app` command open the web app inside Telegram. It signs in with the launch data Telegram signs for the Mini App (checked with the bot token, less than a day old), so there is no widget or phone number step. The same access rules apply. These sessions use a `SameSite=None; Partitioned` cookie because Telegram's web clients show the app in an iframe, and the CSP allows only `https://web.telegram.org` to embed it.
- **Who can sign in:** the owner (`ADMIN_TELEGRAM_CHAT_ID`) always can. Anyone else needs a single-use invite, valid for 24 hours, from the owner (`/invite` in the bot, or `POST /api/invites`). Tokens are stored only as hashes.
- **Sessions** are HttpOnly, Secure, SameSite=Lax cookies (Mini App: see above) lasting 30 days, and can be revoked by logging out.
- **Writes** must come from the app's own origin and carry the session's `X-CSRF-Token`.
- **Every route** takes the user from the session. Another user's data returns 404.

## Background jobs

Budget alerts and bill reminders run on a Postgres-backed job queue inside the app process: `JOBS_ENABLED`, which defaults to on only when `ENVIRONMENT=prod`.

- **Exactly once:** each job is claimed with `FOR UPDATE SKIP LOCKED` under a 5-minute lease, and recurring work is queued once per time slot under a unique dedupe key. Overlapping instances during a deploy don't double-send, and no leader election is needed.
- **Retries:** failures back off (2, 4, 8… minutes, capped at an hour) and stop after 5 attempts.
- **Quiet hours:** Telegram messages wait out 22:00–08:00 in the user's timezone.
- **Bills:** a name, an optional amount, a next due date, and a repeat of once, weekly, monthly or yearly. Monthly bills on the 29th–31st land on the last day of shorter months and come back afterwards. Every 30 minutes a sweep sends the most urgent reminder reached (7, 3 or 1 days before), once each. Reminders carry **Mark paid** and **Snooze 1 day** buttons. Snoozing re-sends the reminder a day later. An unpaid bill shows as overdue for a week, then rolls on to its next due date. Marking a bill paid only records it: nothing is paid and the ledger isn't touched.
- **Budgets:** monthly limits in the home currency, overall or per category, with no rollover. Every 10 minutes a sweep records each 50/80/100% threshold reached once per budget per month (`budget_alerts`), and messages the highest new one.

## Deploy (Railway)

The `nexus-app` service builds from the `Dockerfile`. Its settings live on the service in Railway, not in the repo (Railway no longer reads `railway.toml`):

- Pre-deploy command: `alembic upgrade head`, so migrations run before the new version starts.
- Health check: `/healthz`, timeout 60 s. Restart policy: on failure.
- Variables: `DATABASE_URL` referencing the service's own Postgres, `ENVIRONMENT=prod`, `PORT=8000`.
