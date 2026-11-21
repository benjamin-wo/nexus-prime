# Spec template

The triage bot posts a spec as a comment on an issue. The owner reads it and applies `ready-for-agent`. The build bot then builds from the spec, not from the original issue text.

The repo is public. Use made-up names, merchants and amounts only.

## Format

```markdown
## Spec

### Problem
One or two sentences. Who is stuck, and on what.

### Behaviour now / Behaviour wanted
- Now: what happens today.
- Wanted: what should happen instead.

### Acceptance criteria
- [ ] Each item is one observable behaviour that a test can check.
- [ ] Phrase it as what a user or caller sees, not how the code works.

### Out of scope
- Things a reader might expect but that this change does not do.

### Likely files
- `path/to/file.py`

### Test plan
- Which test files, and whether each is unit, integration or Playwright.
- Commands to run (see below).

### Risk
`routine` or `sensitive`, with one line saying why.
```

## Test commands

These match `.github/workflows/ci.yml`. The build bot runs all of them before it opens the PR.

Python (integration tests need `TEST_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/postgres`):

```
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Web (run in `web/`):

```
npm run typecheck
npm test
npm run build
npm run e2e
```

Unit tests live in `tests/unit/`, integration tests in `tests/integration/`, web unit tests in `web/src/`, and Playwright specs in `web/e2e/`.

## Risk: routine or sensitive

Mark the spec `sensitive` if the change touches any of these:

- Sign-in, sessions, CSRF or security headers (`src/nexus/channels/web/security.py`).
- Database migrations (`migrations/`).
- Money arithmetic: `src/nexus/domain/calc.py`, `src/nexus/domain/money.py` (`Money`), `src/nexus/application/fx.py`, `src/nexus/application/budgets.py`, `src/nexus/application/month_outlook.py`.
- Data export or erasure (`src/nexus/application/export.py`, `src/nexus/application/erasure.py`, `src/nexus/application/user_data.py`).
- The LLM system prompt or tool definitions (`src/nexus/agent/graph.py`, `src/nexus/agent/tools.py`).
- Row-level security.
- `deploy/` or `.github/`.
- Secrets, in any form.

Everything else is `routine`. If unsure, choose `sensitive`. A `sensitive` spec gets the `sensitive` label, and the owner reviews it at both the spec and the PR.

## Migrations: expand, then contract

A migration must work with the code that ran before it. A failed deploy rolls back the code but not the database, so the old code has to keep working against the new schema.

- Expand first: add new tables, and add new columns as nullable or with a default. Ship the code that uses them.
- Contract later, in a separate change: drop or rename the old column only once no running code reads it.
- Never drop, rename or tighten a column in the same change as the code that stops using it.

A spec with a migration is always `sensitive`.

## Example

```markdown
## Spec

### Problem
Sam logs a coffee at "Example Cafe" but cannot tell which expenses are shared with a flatmate. The ledger has no way to mark an expense as shared.

### Behaviour now / Behaviour wanted
- Now: every expense looks the same in the ledger list.
- Wanted: an expense can be marked "shared", and the ledger shows a small "Shared" tag on it.

### Acceptance criteria
- [ ] On the add-expense form, ticking "Shared" and saving shows a "Shared" tag on that row in the ledger.
- [ ] An expense saved without the tick shows no tag.
- [ ] Reloading the page keeps the tag.
- [ ] The monthly total does not change.

### Out of scope
- Splitting the amount between people.
- Filtering the ledger by shared.
- The Telegram bot.

### Likely files
- `web/src/components/LedgerRow.tsx`
- `web/src/components/AddExpenseForm.tsx`
- `web/e2e/ledger-add.spec.ts`

### Test plan
- Extend `web/e2e/ledger-add.spec.ts` (Playwright) for the tick, the tag and the reload.
- Add a case to `web/src/components.test.tsx` (web unit) for the tag.
- Run `npm run typecheck`, `npm test`, `npm run build` and `npm run e2e` in `web/`.

### Risk
`routine`: front end only, no money arithmetic and no schema change.
```
