# configure-email-transaction-searcher - Work Plan

## TL;DR (For humans)

**What you'll get:** The email transaction searcher will stop logging false-positive transactions (promos, newsletters, login alerts that happen to contain numbers). Users can configure which email senders to always ignore and which content types to track, via the Telegram chat. A new validation step reads the full email body before the LLM tries to extract an expense, catching non-transaction emails fast (~300ms on CPU).

**Why this approach:** Laya (open-source, 421M param decision model) runs on Railway's CPU infrastructure with no API keys or per-call costs. It's specifically trained for email triage with calibrated probabilities — so when it says "85% chance this is a transaction," you can trust that number. Only emails it flags as likely transactions reach the existing Gemini extraction pipeline.

**What it will NOT do:** Change how emails are fetched from Gmail/Outlook. Change the deduplication logic. Introduce a web UI for settings. Require GPU hardware.

**Effort:** Medium — 8 implementation tasks (1 spike + 7 code tasks) + final verification
**Risk:** Low — Laya gracefully degrades; all existing paths untouched until the validation gate is enabled; rolling back just removes the Laya import

**Decisions to sanity-check:**
- Laya was chosen over JEV (open-source, local, $0/inference vs cloud API with per-call cost)
- Validation gate placed inside `log_expenses_from_emails` before the LLM call (not at search time)
- CPU inference on Railway (no GPU available; tested at ~200-500ms/call)
- Persistent volume at `/data` (2 GB minimum) caches model weights across redeploys
- `HF_HOME` env var used for model cache (Laya uses HuggingFace transformers)
- `asyncio.Lock` guards model loading from concurrent access
- Skipped non-transaction emails are immediately tagged processed
- User-facing `update_email_presets()` agent tool (not slash command or web form)

---

## Scope

### Must have
1. New JSON columns on `UserProfile`: `email_exclude_domains: List[str]` and `email_content_type_presets: List[str]`
2. `capabilities/email/validation.py` — Laya wrapper module with: model loader, email preprocessor (using Laya's `clean_email_body`), transaction classifier (`is_transaction` noul question)
3. Validation gate in `log_expenses_from_emails` loop before `extract_expense_from_text`: if Laya reports `is_transaction < 0.85`, skip the email (mark processed), unless confidence is in the 0.40–0.85 band → route to Gemini fallback
4. `update_email_presets()` agent tool — sets `email_exclude_domains` and `email_content_type_presets` on the user's profile
5. Update `build_gmail_query` / `build_outlook_query` to accept exclude domains and content-type filters (filter out from search results)
6. Fix Outlook IMAP path (`_fetch_outlook_imap`) to populate `"body"` field in returned dict
7. Railway deployment config: Dockerfile adjustment, persistent volume at `/data`, optional `[laya]` extras

### Must NOT have (guardrails)
- No changes to the Gmail/Outlook API fetching layer itself
- No changes to `search_email_messages` signature or behavior
- No web cockpit UI for preset management
- No Laya model served as a separate Railway service (goes in the existing app)
- No migration for existing users — new cols default to `[]`
- No re-training or fine-tuning of Laya (use pre-trained model as-is)

## Verification strategy
- **Test decision:** Tests-after (add tests alongside new code)
- **Framework:** pytest + pytest-asyncio (existing pattern)
- **Evidence:** `.omo/evidence/configure-email-transaction-searcher/task-<N>/`
- Key QA scenarios:
  - Laya wrapper: mock model → test correct questions asked, correct confidence routing
  - Validation gate in `log_expenses_from_emails`: mock Laya returning 0.9 → email passes through; mock 0.3 → email skipped; mock 0.6 → falls to Gemini glue
  - `update_email_presets` tool: set/get/clear presets, verify query builder uses them
  - Query builder: exclude domain removes from output; content-type filter narrows search
  - Graceful degradation: `import laya` fails → no crash, old path works unchanged

## Execution strategy

### Parallel execution waves

**Wave 0 — Pre-flight (Todo 1)**
Laya API spike: verify actual function signatures before writing code.

**Wave 1 — Foundation (Todos 2–4)**
Database schema + migration, Laya wrapper, validation gate. These must land first and in order.

**Wave 2 — User config + query (Todos 5–7)**
Agent tool for preset management + query builder + provider protocol update + Outlook IMAP fix. Can parallelize within the wave.

**Wave 3 — Deploy (Todo 8)**
Railway config. Depends on Laya wrapper being verified.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1. Laya API spike | — | 3 | 2 |
| 2. DB schema + migration | — | 5 | 1 |
| 3. Laya wrapper | 1 | 4, 8 | 2 |
| 4. Validation gate | 3 | — | — |
| 5. Agent tool | 2 | — | 6, 7 |
| 6. Query builder + provider | 2 | — | 5, 7 |
| 7. Outlook IMAP fix | — | — | 5, 6 |
| 8. Railway config | 3 | — | 5, 6, 7 |

## Todos
> Implementation + Test = ONE todo. Never separate.

- [x] 1. Spike: Verify Laya package API surface
  What to do / Must NOT do: In a test environment (local machine or CI), run `pip install laya` and probe its actual API. Specifically verify: (a) `laya.load("convaiinnovations/laya")` works and returns an object with a `predict` method; (b) `agent.predict(state, questions)` returns a dict with the expected shape `{"answers": {...}}`; (c) the existence and signatures of `laya.email.clean_email_body()`, `laya.email.email_state()`, `laya.email.email_questions()`. (d) the env var that controls model cache location — test `HF_HOME` and `XDG_CACHE_HOME`. (e) whether `predict()` works on CPU with torch. Document the verified function signatures into `capabilities/email/validation.py` as docstring contracts. Must NOT implement any production code — this is purely investigative. Must NOT assume API names before this spike.
  Parallelization: Wave 0 | Depends on: — | Blocks: 3
  References: `pip install laya`, HuggingFace repo `convaiinnovations/laya`, `laya.agent`, `laya.email`
  Acceptance criteria: All five API probes return expected types. Verified signatures documented as reference before Todo 3 begins.
  Commit: N/A (spike, no code committed)

- [x] 2. Extend UserProfile with email preset columns + ALTER TABLE migration
  What to do / Must NOT do: (a) Add `email_exclude_domains: List[str]` and `email_content_type_presets: List[str]` JSON columns to `UserProfile` in `core/models.py` (following the existing `tracked_banks` pattern at line 10, default `[]`). (b) In `core/db.py:init_db()`, add `ALTER TABLE userprofile ADD COLUMN email_exclude_domains JSON DEFAULT '[]' NOT NULL` and the same for `email_content_type_presets`, using the existing pattern (`_is_duplicate_column_error` catch + per-dialect SQL, `core/db.py:56-82`). CRITICAL: `SQLModel.metadata.create_all` does NOT add columns to existing tables — only manual ALTER TABLE in init_db works for production databases.
  Must NOT remove or rename existing columns. Must NOT use Alembic.
  Parallelization: Wave 1 | Depends on: — | Blocks: 5, 6
  References: `core/models.py:5-14` (UserProfile model + tracked_banks), `core/db.py:52-196` (init_db with existing ALTER TABLE migration pattern — see lines 56-82 for the exact SQLite+Postgres pattern)
  Acceptance criteria: New fields present in `UserProfile.__fields__`; existing test `test_models_and_db.py` continues to pass; new test creates UserProfile with both new fields set, reads them back correctly; existing DB with UserProfile table gets columns after migration.
  QA scenarios: happy → create UserProfile with `email_exclude_domains=["spam.com"]` and `email_content_type_presets=["receipt","bank_transaction"]`, assert values read back; failure → empty defaults should be `[]` not `None`; migration → init_db on existing table adds columns without error.
  Commit: feat(db): add email_exclude_domains and email_content_type_presets to UserProfile

- [x] 3. Create Laya transaction validation module
  What to do / Must NOT do: Create `capabilities/email/validation.py` with: (a) `load_laya_model()` — lazy loader guarded by `asyncio.Lock` to prevent concurrent model loading (use pattern: `async with _model_lock: if _model is None: _model = _load()`); (b) `validate_transaction_email(sender, subject, body) -> dict` — uses Laya's API to build state and ask questions; (c) `is_transaction_email(sender, subject, body) -> float` — returns probability 0.0-1.0 (returns 0.5 if Laya not installed, documented as "unknown/fallback" not "real confidence").
  Must NOT block startup if Laya is not installed. Must NOT download model at import time. Must NOT assume Laya API names without verifying against the actual installed package in the spike Todo 0 (now Todo 1).
  Parallelization: Wave 1 | Depends on: 1 | Blocks: 4
  References: Results of Todo 1 spike (verified Laya API signatures), `laya.email.clean_email_body`, `laya.email.email_state`, `laya.agent.laya.load()`, `agent.predict()`; Use `HF_HOME` env var for model cache (not `LAY_CACHE_HOME` — Laya uses HuggingFace transformers cache).
  Acceptance criteria: When `laya` is installed, `is_transaction_email()` returns a float in [0.0, 1.0]; when not installed, returns 0.5 (no crash); model loading is guarded by `asyncio.Lock`; test with mocked model returns correct values.
  QA scenarios: happy → mock agent.predict returns `{"answers": {"is_transaction": {"noul": 0.92}}}` → assert 0.92 returned; failure → mock ImportError → assert 0.5 returned; concurrency → simulate 2 concurrent calls, verify model loads exactly once.
  Commit: feat(email): add Laya-based email transaction validation module

- [x] 4. Insert Laya validation gate into log_expenses_from_emails
  What to do / Must NOT do: In `capabilities/expenses/tools.py`, inside `log_expenses_from_emails` (lines 1470-1485), insert a call to `is_transaction_email()` BEFORE the `extract_expense_from_text` call. Routing: probability >= 0.85 → proceed to extraction (no change); 0.40-0.85 → call extraction normally but clamp the final output confidence to `min(extracted.confidence, laya_confidence)` so the existing 0.8 HITL threshold catches uncertain ones; < 0.40 → skip the email AND immediately call `apply_email_processed_tag()` for that email (so it's never re-scanned). Must NOT change the function signature or return shape. Must NOT modify the LLM extraction function itself.
  Parallelization: Wave 1 | Depends on: 3 | Blocks: —
  References: `capabilities/expenses/tools.py:1449-1619` (log_expenses_from_emails), lines 1470-1485 (per-email loop starts + LLM extraction call), lines 1578-1585 (processed tag applied after save), `capabilities/email/providers.py` (body field in email dict)
  Acceptance criteria: With Laya enabled, a mock non-transaction email is correctly skipped and tagged processed; a mock transaction email proceeds to extraction; skipped emails never re-appear. Return dict still has `logged`, `skipped`, `deduped` keys.
  QA scenarios: happy → mock `is_transaction_email` returns 0.95 → email processed normal; happy → returns 0.30 → email added to `skipped` AND `apply_email_processed_tag` called; happy → returns 0.55 → extraction called, final confidence clamped; failure → Laya not installed → extraction proceeds as before (no regression).
  Commit: feat(expenses): add Laya validation gate before LLM extraction in email sweep

- [x] 5. Create update_email_presets agent tool
  What to do / Must NOT do: Add `@tool @identity_bound` function `update_email_presets(user_id, exclude_domains=None, content_type_presets=None)` in `capabilities/email/tools.py`. Updates the two new JSON columns on `UserProfile`. Returns current state. Also add `get_email_presets(user_id)` read-only tool. Register in the email skill's `SKILL.md` frontmatter. Must NOT affect existing queries or email fetch behavior (presets are consumed by query builders in a separate todo).
  Parallelization: Wave 2 | Depends on: 2 | Blocks: —
  References: `core/models.py:5-14` (UserProfile), `capabilities/email/tools.py:122-144` (discover_and_track_bank_domain as analogous tool pattern), `skills/email/SKILL.md:5-10` (tools: section), `core/tool_guard.py` (identity_bound)
  Acceptance criteria: Set presets → read back → assert exact values; omit args → no change to non-provided fields; get tool returns dict with both fields.
  QA scenarios: happy → `update_email_presets(exclude_domains=["spam.co"])` → assert profile.email_exclude_domains == ["spam.co"]; happy → partial update updates only specified field; failure → invalid args handled gracefully.
  Commit: feat(email): add update_email_presets and get_email_presets agent tools

- [x] 6. Update query builders to consume exclude domains and content-type presets
  What to do / Must NOT do: (a) Update `build_gmail_query()` and `build_outlook_query()` in `core/shared_tools/email_presets.py` to accept optional `exclude_domains: Optional[List[str]] = None` param. (b) Add domain exclusion logic: for Gmail queries, emit `-from:domain` clauses; for Outlook Graph, expand the `$filter` to exclude senders. (c) Update `search_email_messages` to pass `profile.email_exclude_domains` through to the query builders. (d) Update `EmailProvider` protocol (`providers.py:196-205`) and all three implementations (`GmailProvider`, `OutlookProvider`, mock) to accept `exclude_domains` parameter. (e) Update mock provider returns to include `"body"` field for test compatibility. Must NOT break existing `custom_query` path. Must NOT change existing required parameters.
  Parallelization: Wave 2 | Depends on: 2 | Blocks: —
  References: `core/shared_tools/email_presets.py:25-74` (both query builders), `capabilities/email/tools.py:187-225` (search_email_messages builds query params), `core/models.py:10` (tracked_banks pattern), `capabilities/email/providers.py:196-208` (EmailProvider protocol), `capabilities/email/providers.py:224-234` (Gmail mock — add "body" field), `providers.py:447-457` (Outlook mock — add "body" field)
  Acceptance criteria: Excluded domain does not appear in generated query; without exclude_domains param, query is identical to current output; custom_query path still returns query verbatim; EmailProvider protocol accepts new param; mock data includes "body".
  QA scenarios: happy → `build_gmail_query(exclude_domains=["chase.com"])` → assert "chase.com" not in output; happy → empty exclude_domains → output identical to current; failure → None passed → no crash; happy → mock providers return dicts with "body" key.
  Commit: feat(email): update email query builders and provider protocol to support domain exclusions

- [x] 7. Fix Outlook IMAP body extraction to include full body
  What to do / Must NOT do: In `_fetch_outlook_imap` (`capabilities/email/providers.py:54-143`), the returned dict currently has `"snippet"` but NOT `"body"` (line 128). Add `"body"` field populated with the full email body text via `email.message_from_bytes`. Must NOT change the existing `"snippet"` behavior. The IMAP path is synchronous (runs in a thread via `asyncio.to_thread`) — the body field must be a plain string.
  Parallelization: Wave 2 | Depends on: — | Blocks: —
  References: `capabilities/email/providers.py:54-143` (IMAP path), lines 93-96 (extracts msg, subject, body via `_body_snippet`), line 128 (only sets snippet)
  Acceptance criteria: IMAP path returns dict with both `"body"` (full text) and `"snippet"` (existing) keys; existing snippet unchanged.
  QA scenarios: happy → IMAP fetch returns dict with `"body"` containing full email text; regression → snippet continues to work as before.
  Commit: fix(email): add full body extraction to Outlook IMAP path

- [x] 8. Add Railway deployment config for Laya
  What to do / Must NOT do: (a) Add `[laya]` optional extras to `pyproject.toml` — `laya` + `torch` (CPU-only, `--index-url https://download.pytorch.org/whl/cpu`). (b) Update `Dockerfile` line 16 from `pip install .` to `pip install --no-cache-dir .[laya]`. (c) Set `HF_HOME=/data` env var for model cache (Laya uses HuggingFace's cache, not `LAY_CACHE_HOME`). (d) Recommend minimum 2 GB persistent volume (torch CPU ~800MB + Laya model ~808MB = ~1.6GB minimum). (e) Add startup log that reports Laya availability (laya import success/failure). Must NOT make Laya a required dependency in base install. Must NOT assume < 2 GB volume.
  Parallelization: Wave 3 | Depends on: 3 | Blocks: —
  References: `core/config.py:1-108` (env var loading pattern), Railway pricing docs (Hobby: up to 8 vCPU / 8 GB per service, persistent volumes 5 GB max), `Dockerfile:16` (pip install .)
  Acceptance criteria: `pip install nexus-prime[laya]` installs laya + torch-cpu; without extras, `import laya` raises ImportError; Docker build with [laya] succeeds; Railway volume at `/data` caches model across deploys.
  QA scenarios: happy → docker build with [laya] extras → Laya loads and runs inference on CPU; failure → without extras → graceful degradation still works; volume → model weights survive redeploy when HF_HOME points to volume.
  Commit: chore: add optional laya extras, update Dockerfile, and document Railway volume config

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit — verify all TODOs completed, scope boundaries respected, no Must-NOT-Have violated
- [x] F2. Code quality review — lint + type check passes, new code follows existing patterns (identity_bound, SQLModel, async)
- [x] F3. Real manual QA — run the full email sweep pipeline against mock data: enable Laya, send known non-transaction email, verify it's skipped; send receipt email, verify it's logged
- [x] F4. Scope fidelity — verify no web UI, no API changes, no model fine-tuning, no separate Laya service

## Commit strategy
- N/A (spike, no code committed)
- `feat(db): add email_exclude_domains and email_content_type_presets to UserProfile`
- `feat(email): add Laya-based email transaction validation module`
- `feat(expenses): add Laya validation gate before LLM extraction in email sweep`
- `feat(email): add update_email_presets and get_email_presets agent tools`
- `feat(email): update email query builders and provider protocol for domain exclusions`
- `fix(email): add full body extraction to Outlook IMAP path`
- `chore: add optional laya extras, update Dockerfile, and document Railway volume config`

## Success criteria
1. Non-transaction emails (promos, newsletters, login alerts) are no longer logged as expenses
2. Users can configure exclude domains and content-type presets via Telegram chat
3. The Outlook IMAP path provides full email body for validation
4. Laya gracefully degrades if not installed — no crashes, no behavior change
5. Railway deploy includes persistent volume for model caching
6. All existing tests continue to pass; new tests cover Laya gates + presets + query builder exclusions