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

The app never registers its own webhook. Pointing a bot at this service is a deliberate step (M3 cutover), so deploying the app can't take a bot away from another service.

The model comes from `LLM_PROVIDER` (`gemini`, `openrouter`, `deepseek` or `openai`) with the matching key, plus an optional Gemini `LLM_FALLBACK_MODEL`. Receipt photos are read by Gemini. With Telegram on and no usable model configured, the app refuses to start.

## Deploy (Railway)

The `nexus-app` service builds from the `Dockerfile`. Its settings live on the service in Railway, not in the repo (Railway no longer reads `railway.toml`):

- Pre-deploy command: `alembic upgrade head`, so migrations run before the new version starts.
- Health check: `/healthz`, timeout 60 s. Restart policy: on failure.
- Variables: `DATABASE_URL` referencing the service's own Postgres, `ENVIRONMENT=prod`, `PORT=8000`.
