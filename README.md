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

## Deploy (Railway)

The `nexus-app` service builds from the `Dockerfile`. Its settings live on the service in Railway, not in the repo (Railway no longer reads `railway.toml`):

- Pre-deploy command: `alembic upgrade head`, so migrations run before the new version starts.
- Health check: `/healthz`, timeout 60 s. Restart policy: on failure.
- Variables: `DATABASE_URL` referencing the service's own Postgres, `ENVIRONMENT=prod`, `PORT=8000`.
