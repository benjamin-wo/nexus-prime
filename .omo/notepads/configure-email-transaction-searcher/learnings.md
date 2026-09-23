# Spike: Verify Laya Package API Surface

Date: 2026-09-23
Task: Todo 1 of configure-email-transaction-searcher plan

## Summary

Verified `laya==0.3.5` API surface against all assumptions in the plan.
**All assumptions confirmed.** No blockers.

## Verified Facts

### `laya.load()`
- **Signature:** `load(model_id_or_path='convaiinnovations/laya', device=None, token=None, subfolder=None) -> laya.agent.Agent`
- Returns a `laya.agent.Agent` instance
- Device auto-detect: CUDA → MPS → CPU
- `device="cpu"` forces CPU (confirmed via source)
- Falls back to CPU on OOM with a warning

### `Agent.predict(state, questions)` / `Agent.system_one()`
- `system_one()` is an alias (same source code, `@torch.no_grad()`)
- **Return shape:**
  ```python
  {
      "model": "laya-rl-agent",
      "answers": {
          "<qid>": {
              "type": "choice" | "score" | "noul",
              "confidence": float,
              "action": {"act_probability": float},
              # For choice:
              "choice": str,
              "probabilities": {str: float},
              # For score:
              "score": float,
              "legend": {str: str},
              "probabilities": {str: float},
              # For noul:
              "noul": float,
          }
      },
      "usage": {"input_tokens": int, "output_tokens": 0}
  }
  ```

### `laya.email` module — **ALL EXIST**
- `laya.email.clean_email_body(body, max_chars=3000) -> str`
  - Strips: quoted history (`On ... wrote:`), `> ` lines, signatures (`-- `), disclaimers, `Original/Forwarded Message`
- `laya.email.email_state(subject, body, sender=None, clean=True, **extra) -> Dict`
  - Returns `{"subject": ..., "body": ..., "from": ...}` (plus extras)
- `laya.email.email_questions(categories=None) -> Dict`
  - Returns 5 questions: `category` (choice), `is_spam` (noul), `is_phishing` (noul), `urgency` (score), `needs_reply` (noul)

### Presets module
- `laya.presets.email_questions()` — same signature as `laya.email.email_questions()` but **different function object**
- Also available: `guard_questions()`, `moderation_questions()`, `router_questions()`, `triage_questions()`

### Model cache
- **Cache location:** `~/.cache/huggingface/hub` (default)
- **Env var:** `HF_HOME` controls the cache root
- **`XDG_CACHE_HOME` is NOT used** by huggingface_hub
- `TRANSFORMERS_CACHE` is an alternative but not checked in laya's code

### Other constants
- `laya.QTYPES = {"choice": 0, "score": 1, "noul": 2}`
- `laya.QTYPE_NAMES = {0: "choice", 1: "score", 2: "noul"}`
- `laya.DEFAULT_MODELS = {"english": (...), "multilingual": (...), "typed-decisions": (...)}`
- `laya.__version__ = "0.3.5"`

## Files Created
- `capabilities/email/validation.py` — docstring contracts (no implementation)

## Implementation — Todo 3 (Wave 1)

Date: 2026-09-23 (continued)
Task: Implement validation module

### File: `capabilities/email/validation.py`

**Architecture decisions that were confirmed correct:**

1. **`asyncio.Lock` guard** — Module-level `_model_lock = asyncio.Lock()` prevents concurrent model instantiation.
   Pattern: `async with _model_lock: if _model is None: _model = load()`
   Verified: three concurrent `load_agent()` calls → `laya.load()` invoked exactly once.

2. **Graceful degradation at module level** — `try: import laya ... except ImportError: LAYA_AVAILABLE = False`. All public functions degrade safely:
   - `load_agent()` returns `None`
   - `validate_transaction_email()` returns fallback dict with `is_transaction=None, is_transaction_probability=None, email_type="unknown", confidence=0.0`
   - `is_transaction_email()` returns `0.5` (maximal uncertainty)

3. **Custom questions (not `laya.email.email_questions()`)** — Two questions for transaction detection:
   - `is_transaction`: `noul` type → calibrated boolean probability
   - `email_type`: `choice` type with criteria: "transaction", "promotional", "security_alert", "spam_phishing", "other"

4. **Body cleaning applied before state building** — `_clean_email_body(body, max_chars=3000)` strips quoted replies and disclaimers; `email_state(clean=False)` skips double-cleaning.

5. **`is_transaction_email()` returns `None`-safe 0.5 fallback** — Critical nuance: the fallback dict returns `is_transaction_probability: None`, and `is_transaction_email()` checks `if prob is None: return 0.5`. Using `0.0` as fallback would incorrectly signal "definitely not a transaction".

### Test file: `tests/test_validation.py`

- 9 tests, all pass
- `ExitStack` pattern required for dynamic context managers (Python doesn't support `*` unpacking in `with` statements)
- Concurrency test uses `time.sleep(0.05)` inside a sync `laya.load()` mock to force coroutine queuing behind the lock
- Module state (`_model`) is reset before concurrency test for clean isolation

### Gotchas encountered

- Python 3.14 does NOT allow `with (ctx_a, *ctx_list):` syntax — must use `ExitStack.enter_context()` for dynamic context manager lists
- `laya.load()` is synchronous, so it blocks the event loop while inside `async with _model_lock`. The lock still prevents double initialization because the lock acquisition/release is async; only one coroutine enters the critical section at a time, even though the load itself is sync-blocking.

---

# Todo 7: Fix Outlook IMAP Body Extraction

Date: 2026-09-23

## Summary

Added full body text extraction to `_fetch_outlook_imap()` — the function previously only extracted a truncated 220-char snippet, missing the `"body"` key entirely that other providers (Gmail, Graph) include.

## Changes

### `capabilities/email/providers.py`

1. **Added `_extract_body_text(message)`** (lines 54-73): Extracts the full plain-text body from a parsed email message without truncation. Same logic as `_body_snippet` but:
   - No `[:limit]` truncation
   - No `" ".join(text.split())` whitespace normalization (preserves paragraph formatting)
   - Returns `text.strip()` instead

2. **Modified `_fetch_outlook_imap()`** (lines 118-119, 151): Added `full_body_text = _extract_body_text(msg)` alongside the existing `body = _body_snippet(msg)` call, and added `"body": full_body_text` to the returned dict. The existing `"snippet"` field is unchanged.

### `tests/test_email_and_expenses.py`

3. **Added `test_outlook_imap_fetch_body_and_snippet`**: Mocks IMAP connection with multipart email containing 600-char body. Verifies:
   - `"body"` key exists with full text (len > 220)
   - `"snippet"` key exists and is truncated (len ≤ 220)
   - Existing fields preserved (provider, subject, sender)

4. **Added `test_outlook_imap_fetch_singlepart_body`**: Same scenario with non-multipart email. Verifies body extraction works for simple messages too.

## Design Decisions

- **Separate extraction for body vs snippet**: Rather than modifying `_body_snippet` to return both, adding a parallel `_extract_body_text` keeps the snippet behavior risk-free and makes the code's intent explicit.
- **No whitespace normalization on body**: The `_body_snippet` function normalizes all whitespace (`" ".join(text.split())`), which is fine for a preview but loses paragraph structure. The full body preserves the original text layout for LLM consumption.
- **Plain string, not bytes**: The function runs synchronously inside `asyncio.to_thread`, and the body field is a plain Python string — consistent with other providers.

## Verification

- 2 new tests pass (IMAP mock with multipart and single-part emails)
- All 38 existing tests pass (1 pre-existing Gmail failure unrelated)
- Settings `outlook_email` and `outlook_app_password` must be set via monkeypatch for IMAP path to activate (otherwise returns `[]` or static mock)

---

# Todo 5: update_email_presets & get_email_presets agent tools

Date: 2026-09-23

## Summary

Added two new `@tool @identity_bound` async functions to `capabilities/email/tools.py`:

- **`update_email_presets(user_id, exclude_domains=None, content_type_presets=None)`** — Updates `UserProfile.email_exclude_domains` and `UserProfile.email_content_type_presets` with partial-update semantics (pass `None` to leave a field unchanged). Returns `{"status": "ok", "exclude_domains": [...], "content_type_presets": [...]}`.
- **`get_email_presets(user_id)`** — Read-only, returns the same dict shape. Returns error dict if user profile doesn't exist.

## Changes

### `capabilities/email/tools.py`
- Added both tools after `discover_and_track_bank_domain` (line 145), following the same DB access pattern (`async_session_factory`, `select(UserProfile)`, `session.add()`, `session.commit()`, `session.refresh()`).
- Uses `@tool @identity_bound` decorator pattern matching all existing tools.
- Partial update: checks `is not None` for each optional parameter before writing.

### `skills/email/SKILL.md`
- Added `update_email_presets` and `get_email_presets` to the frontmatter `tools:` list.

### `tests/test_email_and_expenses.py`
- 8 new tests covering:
  - `test_get_email_presets_default_empty` — fresh profile returns `[]` for both fields
  - `test_update_email_presets_set_both` — set both fields, read back exact values
  - `test_update_email_presets_partial_exclude_only` — only exclude_domains changes
  - `test_update_email_presets_partial_presets_only` — only content_type_presets changes
  - `test_update_email_presets_clear_fields` — empty list clears the field
  - `test_update_email_presets_invalid_user_graceful` — error on non-existent user
  - `test_get_email_presets_invalid_user_graceful` — error on non-existent user
  - `test_update_email_presets_db_persistence` — data persists in DB, verified via direct SQL read
- Uses `@pytest_asyncio.fixture` to seed UserProfile rows (tests need profiles to exist in DB)

## Design Decisions

- **Partial update via `None` sentinel**: When a parameter is `None`, that field isn't touched. This lets the model update only one preset category without knowing the other's current value. An explicit empty list (`[]`) clears the field.
- **`session.refresh()` after commit**: Re-reads the profile from DB so the returned state is authoritative (important for SQLite fallback where in-memory object might not reflect actual DB state).
- **Error return on missing profile**: Rather than silently creating a profile or returning empty, the tool returns `{"status": "error", "message": "..."}` to make missing-profile situations debuggable. This matches the pattern of other tools that check for profile existence.
- **Test seeding separate from tool**: Tests create `UserProfile` rows explicitly via fixtures rather than relying on auto-creation. This keeps the tool's error behavior testable.

## Verification

- 8/8 new tests pass
- All 204 tests collected, only pre-existing failures (unrelated test files)

---

# Todo 6: Domain Exclusions in Email Query Builders & Provider Protocol

Date: 2026-09-23

## Summary

Added `exclude_domains` support to email query builders, provider protocol, and all implementations. When a user configures `email_exclude_domains` on their profile, those sender domains are excluded from email search results.

## Changes

### `core/shared_tools/email_presets.py`

1. **`build_gmail_query()`**: Added `exclude_domains: Optional[List[str]] = None` parameter. Appends `-from:domain1 -from:domain2` clauses at the end of the Lucene query string. Custom query path returns verbatim (no exclusion applied).

2. **`build_outlook_query()`**: Added `exclude_domains` parameter. Appends `and not(from/emailAddress/address eq 'domain')` clauses to the `$filter` parameter. Custom query path still returns verbatim, with exclusion clauses appended to the default `$filter`.

### `capabilities/email/providers.py`

3. **`EmailProvider` protocol**: Added `exclude_domains: Optional[List[str]] = None` to `search_messages()` signature.

4. **`GmailProvider.search_messages()`**: Passes `exclude_domains` through to `build_gmail_query()` (both mock and real OAuth paths). Mock return dict now includes `"body": ""` field.

5. **`OutlookProvider.search_messages()`**: Passes `exclude_domains` through to `build_outlook_query()` (mock, real Graph, and IMAP fallback paths). Mock return dict now includes `"body": ""` field.

6. **`_fetch_outlook_imap()`**: Added `exclude_domains` parameter with sender-domain filtering logic (skips messages whose sender domain matches an excluded domain).

### `capabilities/email/tools.py`

7. **`search_email_messages()`**: Reads `profile.email_exclude_domains` from DB and passes it to each provider's `search_messages()` call. Falls back to `None` when profile is missing.

### `tests/test_email_and_expenses.py`

8. **`test_gmail_query_exclude_domains()`**: Verified: excluded domain produces `-from:` clause; empty exclude list = identical output; custom_query path unchanged.

9. **`test_outlook_query_exclude_domains()`**: Verified: excluded domain produces `not(from/emailAddress/address eq '...')` in `$filter`; empty list = identical output; custom_query path preserved.

10. **`test_mock_provider_body_field()`**: Verified mock `GmailProvider` and `OutlookProvider` return dicts include `"body"` key.

## Design Decisions

- **Backward compatible**: All new params default to `None` — existing callers and tests pass unchanged.
- **Custom query path**: For Gmail, custom_query returns verbatim (exclusions not appended). For Outlook, exclusions are appended to `$filter` even in custom_query mode since the $filter is additive.
- **Exclusion is additive to filter, not subtractive from search**: For Outlook, excluded domains remain in the `$search` text match but are filtered out at the OData level. This is because Graph's `$search` is a keyword/content search, not a structured field filter.
- **`$search` untouched**: Excluded domains are NOT removed from the `$search` parameter — they're only added to `$filter` as negative conditions. This avoids breaking search tokenization.

## Verification

- 3 new tests pass (exclude_domains for Gmail, exclude_domains for Outlook, mock body field)
- All 42 email tests pass (including 39 existing, unchanged)
- 2 existing model/DB tests pass (email_exclude_domains field store/read)

---

# Todo 4: Laya Validation Gate in log_expenses_from_emails

Date: 2026-09-23

## Summary

Inserted the Laya transaction validation gate into `log_expenses_from_emails` in `capabilities/expenses/tools.py`. The gate calls `is_transaction_email(sender, subject, body)` before the LLM extraction call and routes based on the returned probability.

## Changes

### `capabilities/expenses/tools.py`

1. **Import** (lines 31-37): Added `try/except` import of `is_transaction_email` from `capabilities.email.validation`. Falls back to a local `is_transaction_email` returning `0.5` (maximal uncertainty) if the module is unavailable.

2. **Laya gate** (lines 1484-1517): Inserted between the dedup check (line 1481) and the LLM extraction call (line 1519):
   - `< 0.40`: Append to `skipped` with `reason="non-transaction"`, call `apply_email_processed_tag()`, then `continue`
   - `0.40-0.85` (and not 0.5): Sets `needs_confidence_clamp = True`
   - `>= 0.85` or `== 0.5`: Proceed unchanged (0.5 is the Laya-not-installed fallback)

3. **Confidence clamping** (lines 1526-1530): After extraction succeeds (amount present), if `needs_confidence_clamp` is True, clamp `extracted["confidence"] = min(extracted.get("confidence", 0.9), laya_prob)`.

### `tests/test_email_and_expenses.py`

4 new tests at end of file:

- **`test_log_expenses_laya_high_confidence`**: Mocks `is_transaction_email`→0.95. Verifies email logged normally (1 logged, 0 skipped).
- **`test_log_expenses_laya_low_confidence`**: Mocks `is_transaction_email`→0.30. Verifies email skipped with `reason="non-transaction"` and `apply_email_processed_tag` called.
- **`test_log_expenses_laya_mid_confidence`**: Mocks `is_transaction_email`→0.55, extraction returns 0.95. After clamping: min(0.95, 0.55)=0.55 < 0.8 → skipped by the existing low-confidence check.
- **`test_log_expenses_laya_not_installed`**: Mocks `is_transaction_email`→0.5 (fallback). 0.5 treated as "proceed normally" → email logged normally.

## Design Decisions

- **`needs_confidence_clamp` flag**: Rather than duplicating the extraction + confidence check logic, a boolean flag is set before extraction and checked after. This keeps the extraction path single and the confidence clamp point explicit.
- **0.5 as sentinel**: `laya_prob == 0.5` is the fallback from `validation.py` when Laya is not installed. The gate explicitly skips the routing for 0.5 so that a missing Laya dependency doesn't change behavior. The `< 0.40` check also excludes 0.5 with `laya_prob != 0.5 and laya_prob < 0.40`.
- **try/except around `is_transaction_email`**: If the function raises for any reason (model load failure, OOM, etc.), `laya_prob` is set to 0.5, causing the gate to fall through to normal processing.
- **Mock pattern**: Uses `monkeypatch.setattr` for `is_transaction_email` at the module path `"capabilities.expenses.tools.is_transaction_email"`. For `apply_email_processed_tag`, a mock with `.ainvoke` lambda is required because the production code calls `.ainvoke()` on the tool object.

## Verification

- 4/4 new Laya gate tests pass
- 2 existing log_expenses tests pass unchanged (including cross-source duplicate dedup test)
- All 46 tests in `test_email_and_expenses.py` collected, 0 regressions
