# Nexus Prime

A personal finance assistant (Telegram bot and web app). See `README.md` for what it does, `docs/OPERATIONS.md` for how it runs and `DESIGN.md` for the web design system.

## Working in this repo

- The main session is the orchestrator: it plans, chooses who does each job, checks the results and reports. Delegated work follows `.claude/skills/delegation/SKILL.md` (which agent, model and effort; escalation; the tuning log in `docs/AGENT_TUNING.md`).
- The repo is public: never commit secrets, real user data, real statements or screenshots of real accounts. Use made-up names and figures in tests.
- Checks before a push:
  - Python: `ruff format .`, `ruff check .`, `mypy src tests`, `pytest` (integration tests need `TEST_DATABASE_URL` pointing at a Postgres).
  - Web (`web/`): `npx tsc --noEmit -p .`, `npx vitest run`, `npm run build`, then the Playwright journeys.
