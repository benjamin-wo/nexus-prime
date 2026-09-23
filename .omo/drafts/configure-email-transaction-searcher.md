---
slug: configure-email-transaction-searcher
status: drafting
intent: clear
review_required: true
plan_path: .omo/plans/configure-email-transaction-searcher.md
plan_sha256: null
review_round_id: null
pending-action: review .omo/plans/configure-email-transaction-searcher.md
review:
  momus:
    status: pending
    workspace_root: null
    runtime_home: null
    target: .omo/plans/configure-email-transaction-searcher.md
    round_id: null
    plan_sha256: null
    launch_id: null
    session: null
    result: null
  independent:
    status: pending
    workspace_root: null
    runtime_home: null
    target: .omo/plans/configure-email-transaction-searcher.md
    round_id: null
    plan_sha256: null
    launch_id: null
    session: null
    result: null
approach: Add per-user configurable email preset filters (sender domains + content-type patterns) and integrate Laya email-body validation as a deterministic pre-filter before LLM extraction, reducing false-positive transaction auto-logging.
---

# Draft: configure-email-transaction-searcher

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
1. UserProfile config surface (email_content_type_presets, email_include/exclude_domains) | extend UserProfile model with new JSON columns | active | db schema
2. Email query builder extension (build_gmail_query / build_outlook_query) to consume new presets | update build functions to read new fields | active | email_presets.py
3. Laya integration for email body validation | add `laya` dependency + validation gate function | active | new: capabilities/email/validation.py
4. Validation gate insertion in log_expenses_from_emails loop | call Laya before LLM extraction step | active | expenses/tools.py
5. Admin-configurable default presets (env-level fallback) | extend Settings class | active | core/config.py

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
1. **Laya > JEV for this use case**: Laya is open-source, runs locally (ModernBERT-large 421M params), no external API call, no API key needed, ~33ms inference on GPU (CPU acceptable for batch). JEV requires calling TypeSafe's external API (latency + cost + key management). Default: Laya.
2. **Validation gate placement**: Insert Laya validation BEFORE the LLM `extract_expense_from_text` call inside `log_expenses_from_emails`, not at query time. Default: filter at extraction time, not search time.
3. **Config store**: Store per-user email presets as JSON columns on `UserProfile` alongside `tracked_banks`. Default: `email_exclude_domains: List[str]`, `email_content_type_presets: List[str]` (e.g. "receipt", "bank_transaction", "order_confirmation").
4. **Laya questions**: Two typed questions — `is_transaction` (noul — calibrated probability that email IS a genuine financial transaction) and `email_type` (choice — "receipt", "bank_alert", "bill/invoice", "promo/spam", "other").

## Findings (cited - path:lines)

### Current email transaction flow
- `sweep_email_for_expenses` (capabilities/email/tools.py:342-381) → calls `search_email_messages` → calls `log_expenses_from_emails` (expenses/tools.py:1447-1619)
- `log_expenses_from_emails` iterates up to 10 emails, calls `extract_expense_from_text` (expenses/tools.py:612-702) per email
- `extract_expense_from_text` uses LLM (Gemini/DeepSeek) to extract structured data, with regex fallback (`_regex_extract_expense` at expenses/tools.py:467-556)
- False positives happen when the LLM extracts an "amount" from non-transaction emails (promos, newsletters, login alerts) that coincidentally contain currency-like numbers
- Per-email dedup layers: Layer 1 by `source_message_id` (expenses/tools.py:1481), Layer 3 cross-source semantic dedup (expenses/tools.py:1531-1559)

### Current query/preset system
- **Global presets** (`email_presets.py:8-23`): `GLOBAL_BANK_PRESET_DOMAINS` — 13 hardcoded bank/svc domains
- **Keyword presets** (`email_presets.py:3-6`): `DEFAULT_GMAIL_FINANCIAL_QUERY` — 10 keywords (receipt, transaction, charge, payment, order, etc.) + `newer_than:7d`
- **User presets** (`core/models.py:10`): `tracked_banks: List[str] = Field(default=[], sa_column=Column(JSON))` on `UserProfile`
- **Auto-discovery** (`email/tools.py:122-144`): `discover_and_track_bank_domain()` auto-appends sender domain on first encounter
- **Query builders** (`email_presets.py:25-74`): `build_gmail_query()` and `build_outlook_query()` merge global + user presets into search queries
- **No current config surface** for: exclude domains, content-type filters, per-user email type preferences

### Body extraction already available in email responses
- Gmail API: `_extract_gmail_body(payload, limit=4000)` at `providers.py:145` — extracts full MIME body text
- Outlook OAuth: `_html_to_text(body_content, limit=4000)` at `providers.py:513-514` — extracts full body via Microsoft Graph
- Outlook IMAP (`_fetch_outlook_imap` at `providers.py:54`): extracts body via `_body_snippet()` but does NOT populate the `"body"` key in the returned dict (only `"snippet"`)
- All email dicts returned by providers carry `"body"` (except IMAP path) and `"snippet"` fields — sufficient for Laya's 512-token budget

### Database models & config surface
- UserProfile (`core/models.py:5-14`): `user_id` (PK), `tracked_banks` (JSON), plus timezone, home_currency, whiteboard flags
- UserCredential (`core/models.py:16-21`): `user_id`, `provider` ("gmail"/"outlook"), `encrypted_token_payload` (Fernet)
- ExpenseTransaction (`core/models.py:23-37`): `source_message_id` (unique), `source_sender_domain` — primary dedup keys
- Settings (`core/config.py:1-108`): Pydantic BaseSettings from `.env`, singleton `settings = Settings()`
- Vault (`core/vault.py`): `encrypt_token()` / `decrypt_token()` using lazy-init Fernet

### Test patterns
- SQLite per-test database (`conftest.py`): `autouse` fixture creates/drops all tables per test
- Tests use `async_session_factory()` + direct SQLModel inserts
- LLM and HTTP calls mocked via `monkeypatch` extensively
- Existing `test_email_and_expenses.py` (999 lines) covers all email/expense flows

### Laya compatibility (from research)
- `pip install laya` — pure Python, downloads ~808MB model from HuggingFace on first use
- `email_utils.py` provides `clean_email_body()`, `email_state()`, `email_questions()` helpers
- Questions: `choice` (categorical), `score` (ordinal scale), `noul` (calibrated boolean probability)
- 512 tokens per question — sufficient for subject (avg 80 chars) + cleaned body (priority paragraphs)
- Runs ~33ms on GPU (T4), ~200-500ms on CPU; no API key required, no external calls
- 421M params (ModernBERT-large backbone) — ~2GB peak RAM

### JEV comparison (from research)
- `pip install jev` — decorator-based, calls TypeSafe external API (`TYPESAFE_API_KEY`)
- `@jev.fn` decorator compiles Python fn → Pydantic model → typed questions to API
- Per-call cost + latency (~200-500ms API round-trip); requires internet access always
- Better for: when you want calibrated probabilities via an external API without local compute
- Worse for: this use case (always-on, latency-sensitive email sweep, no external dependency)

## Decisions (with rationale)

1. **Use Laya over JEV**: Laya is open-source, runs locally (no API call, no cost per request), and the model is specifically fine-tuned for email triage. JEV adds an external dependency and per-request cost. Laya's `noul` question type with calibrated probability is ideal for the false-positive gate.
2. **Validation at extraction time**: Adding the gate at search time would be fragile (different email providers have different search capabilities). Adding it in `log_expenses_from_emails` before the LLM call means we apply the same logic regardless of email source. Low-confidence non-transactions are skipped (not logged), and the email is still marked processed.
3. **Extend UserProfile with JSON columns**: Follows the existing pattern of `tracked_banks: List[str]` on UserProfile. New fields: `email_exclude_domains: List[str]` (domains to always ignore), `email_content_type_presets: List[str]` (types of financial emails to track).
4. **Async Laya inference**: The laya model supports async inference. We can wrap it in an async function that runs on a thread pool executor for CPU inference, keeping the async event loop free.
5. **Graceful degradation**: If Laya is not installed or the model is not downloaded, fall back to the current LLM-only extraction (no validation gate = no change in behavior).

## Scope IN

1. Add `email_exclude_domains` and `email_content_type_presets` JSON columns to `UserProfile`
2. Add a Laya-based email validation function in `capabilities/email/validation.py`
3. Insert Laya validation gate in `log_expenses_from_emails` before `extract_expense_from_text`
4. Update `build_gmail_query` / `build_outlook_query` to accept exclude domains and content type filters
5. Add env-level default config settings (default exclude domains, default content types)
6. Add a user-facing tool to update their email presets (e.g. `update_email_presets`)
7. Tests for the Laya validation integration, preset query building, and the new tool

## Scope OUT (Must NOT have)

1. No Web UI for managing presets — only agent/tool interface
2. No changes to the email provider fetching layer (Gmail/Outlook API calls)
3. No changes to how `search_email_messages` works — only the downstream processing
4. No auto-retraining of Laya — we use the pre-trained model as-is
5. No migration for existing users — new columns default to empty lists

## Open questions (resolved)

1. ~~**Laya model download strategy**: ~808MB download. Options: (a) ship as `lay[aya]` optional extras in pyproject.toml, (b) pre-download in Docker build, (c) download on first use at app startup. Default: optional extras + download on first use to keep the base image lean.~~ ✅ **Resolved**: Optional pip extras (`pip install nexus-prime[laya]`). Model downloads on first inference via HuggingFace, cached on persistent Railway volume at `/data`. If `laya` import fails, silently skip validation (graceful degradation).
2. ~~**CPU vs GPU inference**: Laya's 421M ModernBERT-large needs ~2GB RAM on CPU (~300ms/call) or can use GPU via torch+cuda. Railway deployments may not have GPU. Default: pure CPU path, with an opt-in GPU flag via env var `LAYA_DEVICE=cuda`.~~ ✅ **Resolved**: Railway is CPU-only (no GPU). Laya runs fine on CPU at ~200-500ms/call. Hobby plan (48 vCPU, 48 GB) is more than sufficient. Use env var `LAY_CACHE_HOME=/data` to persist model on volume.
3. **User-facing tool for presets**: What should the Telegram-facing tool look like? Options: (a) a `configure_email_presets` tool the agent calls, (b) a slash command like `/email-presets`, (c) a web cockpit form. **Default**: agent tool `update_email_presets()` with structured args (sender_domains to include, exclude; content_type_presets list).

## Approval gate
status: approved
<!-- User approved the approach. Writing plan now. -->