FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --locked --no-dev

RUN useradd --create-home app
USER app
ENV PATH="/app/.venv/bin:$PATH" PORT=8000
CMD ["sh", "-c", "exec uvicorn --factory nexus.main:create_app --host 0.0.0.0 --port ${PORT}"]
