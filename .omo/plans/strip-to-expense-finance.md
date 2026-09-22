# strip-to-expense-finance — Work Plan

## TL;DR (For humans)

**What you'll get**: The same Nexus Prime app, but stripped from 10+ capabilities down to *only expense & finance* — expense tracking, income logging, bill splitting, IOU settlement, receipt scanning (photo + email), search_web utility, and the web cockpit dashboard. Everything else (transit, groceries, whiteboard, memory, code exec, bug logging, recipes, scheduled content, daily briefing) is removed.

**Why this approach**: Three-phase — (A) strip out-of-scope modules in parallel, (B) simplify survivors to remove all non-finance references, (C) polish docs and deps. Phases A and C are safely parallel; B must follow A because survivors reference the removed modules.

**What it will NOT do**: No architecture changes — the single LangGraph agent loop (`agent_loop.py`) stays as-is. No DB schema changes to kept tables. No new features added. No re-deployment changes.

**Effort**: ~150 files to remove/modify across 7 directories. Most changes are file deletions; the most complex edits are in `agent_loop.py`, `ingress.py`, `dashboard_api.py`, and `showcase/`.

**Risk**: Low — deletions are safe because no remaining code imports the deleted modules (verified per exploration). The main risk is forgetting to remove a reference that causes an `ImportError` at boot — mitigated by the final verification wave which starts the app and runs the smoke test.

**Decisions**: Email integration stays (receipt extraction from Gmail/Outlook). IOU task tracking stays. search_web/fetch_url stay. Web cockpit stays.

## Scope

### IN
- Remove: `capabilities/routes/`, `capabilities/recipes/`, `capabilities/whiteboard/`, `capabilities/memory/`, `capabilities/bug_logging/`, `capabilities/code_exec/`, `capabilities/scheduled_content_delivery/`
- Remove: `skills/bug-logging/`, `skills/code-exec/`, `skills/daily-briefing/`, `skills/memory/`, `skills/recipes-groceries/`, `skills/reminders/`, `skills/transit/`, `skills/whiteboard-planning/`
- Remove: `core/code_sandbox.py`, `core/github_sync.py`
- Remove from `core/models.py`: `GroceryItem`, `PointsBalance`, `WhiteboardProject`, `WhiteboardBlock`, `BusStop`, `QualityAuditLog`, `ConversationAuditLog`, `ProductionBugLog`, `CapabilityRequestLog` (keep: `UserProfile`, `UserCredential`, `ExpenseTransaction`, `IncomeTransaction`, `DeletedExpenseMessage`, `ExpenseUndoEntry`, `TaskItem`, `ScheduledJob`)
- Remove from `core/db.py`: whiteboard, board-cover, and email-digest column migrations
- Remove from `core/skill_registry.py`: `TOOL_MODULES` entries for routes, recipes, whiteboard, memory, bug_logging, code_exec, scheduled_content_delivery
- Remove non-finance tests (~30 files)
- Remove: `config/tag-policy.yaml`, `spec-capability-gaps.md`, `spec.md`, `evals/`, `issues/`, `docs/`
- Remove from `core/audit.py`: models that reference removed tables (keep capability-request telemetry)
- Simplify: `orchestrator/agent_loop.py` — remove bus/transit routing, recipe guidance, tidy system prompt
- Simplify: `app/ingress.py` — remove whiteboard/pin/board callbacks, whiteboard-related callbacks, simplify slash commands
- Simplify: `app/dashboard_api.py` — remove board cover generation, grocery endpoints, whiteboard endpoints
- Simplify: `app/chat_api.py` — remove grocery/reminder event emission
- Simplify: `app/main.py` — remove startup data cleanup for whiteboard/board fields
- Simplify: `core/scheduler.py` — remove task-reminder scheduling, keep only cron job/email sweep
- Simplify: `showcase/` — remove whiteboard/boards/groceries tabs, keep transaction ledger, charts, summary
- Update: `README.md`, `CONTEXT.md`, `map.md`, `pyproject.toml` (remove `e2b`, `pgvector` deps)

### OUT (goes without saying for a strip plan)
- No changes to the LangGraph agent architecture
- No DB schema changes to kept models
- No new features
- No changes to docker/deployment configuration beyond dependency pruning

### Must-NOT-Have
- No re-architecting the agent loop
- No changing DB indexes or constraints on kept tables
- No adding or modifying expense/finance functionality
- No changes to the Telegram webhook or OAuth flow

## Verification strategy

| Check | Method |
|-------|--------|
| All deleted modules gone | `from capabilities.routes import ...` fails → correct |
| No dangling imports | `python -c "from core.models import GroceryItem"` fails → correct |
| App boots cleanly | `uvicorn app.main:app --port 8000` starts without ImportError |
| Agent loop runs | Hit `/start` on the Telegram ingress or POST `/api/chat` — reply is the greeting |
| Expense tool works | `POST /api/chat` with "spent $12 at Starbucks" → expense logged |
| Dashboard loads | `GET /api/dashboard/summary` → 200 with finance data |
| search_web works | The agent can still answer web queries via search_web |
| Email auth works | OAuth flow remains intact |
| Tests pass | `pytest tests/ -v` on kept tests |

## Execution strategy

**Phase A — Strip modules** (can be parallel): Delete directories, files, and model classes. These are pure removals — no code changes to survivors needed (verified no remaining code imports these modules).

**Phase B — Simplify survivors** (sequential after A): Edit the remaining files to remove references to deleted modules. Order: (1) orchestrator/agent_loop.py, (2) app/ingress.py, (3) app/dashboard_api.py, (4) app/main.py, (5) app/chat_api.py, (6) core/skill_registry.py, (7) core/db.py, (8) core/scheduler.py, (9) core/models.py, (10) core/audit.py, (11) showcase/ frontend.

**Phase C — Polish**: Update README, CONTEXT, deps. Run final verification.

## Todos

- [x] 1. `capabilities/`: Remove all non-finance capability directories
    - **References**: `capabilities/routes/`, `capabilities/recipes/`, `capabilities/whiteboard/`, `capabilities/memory/`, `capabilities/bug_logging/`, `capabilities/code_exec/`, `capabilities/scheduled_content_delivery/`
    - **Acceptance**: Running `import capabilities.routes`, etc., raises `ModuleNotFoundError`. No remaining file imports from these packages (verified: only `capabilities/email/tools.py` is referenced by `capabilities/expenses/tools.py` — keep email).
    - **QA happy**: `ls capabilities/` shows only `__init__.py`, `expenses/`, `email/`, `general/`, `recipes/` (keep only the directory skeleton), `RECIPES.md` (remove), `routes/` becomes unnecessary error test
    - **QA failure**: An import in a surviving file breaks → the survivor's edit in Phase B must fix it
    - **Commit**: `git rm -r capabilities/routes capabilities/recipes capabilities/whiteboard capabilities/memory capabilities/bug_logging capabilities/code_exec capabilities/scheduled_content_delivery capabilities/RECIPES.md`

- [x] 2. `skills/`: Remove all non-finance skills
    - **References**: `skills/bug-logging/`, `skills/code-exec/`, `skills/daily-briefing/`, `skills/memory/`, `skills/recipes-groceries/`, `skills/reminders/`, `skills/transit/`, `skills/whiteboard-planning/`
    - **Acceptance**: `core/skill_registry.discover_skills()` returns only `expenses`, `email`, `web-research` (since `general` may not have its own skill — check what declares `search_web`)
    - **QA happy**: `ls skills/` shows only `expenses/`, `email/`, `web-research/`
    - **QA failure**: A skill referenced by agent_loop.py system prompt still exists → will be removed in Phase B
    - **Commit**: `git rm -rf skills/bug-logging skills/code-exec skills/daily-briefing skills/memory skills/recipes-groceries skills/reminders skills/transit skills/whiteboard-planning`

- [x] 3. `core/models.py`: Remove non-finance models
    - **References**: `GroceryItem`, `PointsBalance`, `WhiteboardProject`, `WhiteboardBlock`, `BusStop`, `QualityAuditLog`, `ConversationAuditLog`, `ProductionBugLog`, `CapabilityRequestLog` (keep audit log models? keep `CapabilityRequestLog` for feature-request telemetry, remove the rest)
    - **Acceptance**: `from core.models import GroceryItem` raises `ImportError`. `SQLModel.metadata.tables` no longer contains these tables.
    - **QA happy**: `from core.models import ExpenseTransaction, IncomeTransaction, TaskItem, DeletedExpenseMessage, ExpenseUndoEntry, UserProfile, UserCredential, ScheduledJob` works
    - **QA failure**: A surviving file references a removed model → fix in Phase B
    - **Commit**: In `core/models.py`, delete class definitions for removed models

- [x] 4. `core/db.py`: Remove whiteboard/board-cover/email-digest column migrations
    - **References**: Lines 55–274 in `core/db.py` contain idempotent `ALTER TABLE` migrations for `whiteboard_seeded`, `cover_ready`, `section_order`, `last_whiteboard_id`, `last_email_digest_at`, `receipt_items` (keep receipt_items — used by expenses), `split_data`, `source_sender_domain`, `logged_at`, `notes`
    - **Acceptance**: `init_db()` only creates tables and runs migrations for `receipt_items`, `split_data`, `source_sender_domain`, `logged_at`, `notes`, and the IOU linkage fields (linked_expense_id, iou_friend, iou_amount)
    - **QA happy**: App boots and `init_db()` succeeds
    - **QA failure**: A migration tries to add a column to a now-deleted table → `SQLModel.metadata.create_all` will create kept tables only; the ALTER TABLE for a non-existent table would error. Remove only migrations for removed tables.
    - **Commit**: In `core/db.py`, remove migrations for `whiteboard_seeded`, `cover_ready`, `section_order`, `last_whiteboard_id`, `last_email_digest_at`

- [x] 5. `core/skill_registry.py`: Trim `TOOL_MODULES`
    - **References**: Lines 28–40 in `core/skill_registry.py` — keep only: `capabilities.general.tools`, `capabilities.email.tools`, `capabilities.expenses.tools`. Remove: `capabilities.routes.tools`, `capabilities.recipes.tools`, `capabilities.reminders.tools`, `capabilities.whiteboard.tools`, `capabilities.memory.tools`, `capabilities.bug_logging.tools`, `capabilities.scheduled_content_delivery.tools`, `capabilities.code_exec.tools`
    - **Acceptance**: `build_tool_registry()` only resolves tools from kept modules
    - **QA happy**: Registry includes `search_web`, `fetch_url`, `extract_expense_from_text`, `log_expenses_from_emails`, `get_user_expenses`, etc. — no `get_bus_timings` or `create_planning_board`
    - **QA failure**: An undeclared tool name in a surviving skill's frontmatter still resolves because it's removed from registry → the skill's frontmatter must not reference removed tools
    - **Commit**: Edit `core/skill_registry.py` — remove 8 module paths from `TOOL_MODULES`

- [x] 6. `core/`: Remove `code_sandbox.py` and `github_sync.py`
    - **References**: `core/code_sandbox.py`, `core/github_sync.py`
    - **Acceptance**: Files are gone. No import in remaining code references them (verified: `AppLogger.github_sync` was in `audit.py`, already checked)
    - **QA happy**: `import core.code_sandbox` raises `ModuleNotFoundError`
    - **QA failure**: A surviving file imports from these → fix in Phase B
    - **Commit**: `git rm core/code_sandbox.py core/github_sync.py`

- [x] 7. `core/audit.py`: Remove models referencing deleted tables
    - **References**: `QualityAuditLog`, `ConversationAuditLog`, `ProductionBugLog` — these reference tables being deleted. Keep `CapabilityRequestLog` for feature-request telemetry.
    - **Acceptance**: `from core.audit import perform_conversation_audit` raises `ImportError` (or removed entirely if we strip audit). Keep `log_capability_request`.
    - **QA happy**: Feature-request logging still works via `agent_loop.py`
    - **QA failure**: agent_loop.py references `perform_conversation_audit` → must be removed from agent_loop.py too
    - **Commit**: Edit `core/audit.py` — remove conversation audit, quality audit, production bug models and their functions. Keep `log_capability_request`.

- [x] 8. `tests/`: Remove non-finance test files
    - **References**: 51 test files. Keep only: `test_income.py`, `test_delete_expense.py`, `test_bill_splitting.py`, `test_query_transactions.py`, `test_edit_restore_undo.py`, `test_email_and_expenses.py`, `test_models_and_db.py`, `test_tool_harness.py`, `test_agent_loop_kernel.py`, `test_agent_empty_reply_fallback.py`, `test_agent_loop_model_call_timeout.py`, `test_llm_factory.py`, `test_llm_model_config.py`, `test_model_fallback.py`, `test_provider_chain.py`, `test_checkpointer.py`, `test_checkpointer_guard.py`, `test_skill_registry.py`, `test_general_tools.py`, `test_general_cross_domain_tools.py`, `test_general_url_guard.py`, `test_kernel_trivial.py`, `test_webhook.py`, `test_vault.py`, `test_conftest.py`. Remove: all others.
    - **Acceptance**: `pytest tests/ -v` runs only the kept tests and they pass. No imported test module from a removed test.
    - **QA happy**: `pytest tests/ -v --co` shows ~25 tests collected instead of 51
    - **QA failure**: A test imports from a deleted module → remove that test file too
    - **Commit**: `git rm tests/test_routes_live.py tests/test_whiteboard.py tests/test_memory.py tests/test_recipes*.py tests/test_tasks_and_reminders.py tests/test_reminders.py tests/test_scheduled_content_delivery.py tests/test_bug_logging.py tests/test_code_sandbox.py tests/test_ambient.py tests/test_background_tasks.py tests/test_conversation_audit.py tests/test_evals_*.py tests/test_capability_gaps.py tests/test_github_gap_tickets.py tests/test_scheduler.py tests/test_showcase_*.py tests/test_media_routing.py tests/test_detection_blindspots.py tests/test_latency_budgets.py tests/test_production_bug_audit.py tests/test_silent_reply_incident.py`

- [x] 9. `orchestrator/agent_loop.py`: Remove bus/transit routing and non-finance references
    - **References**: Lines 884–901 handle `pending_bus_stops` — remove this block. Line 127 `_RECIPE_GUIDANCE` — remove the recipe guidance block. Line 119 `_UNSUPPORTED_EXAMPLES` — simplify to finance-relevant examples only. Lines 174–178 `capabilities_desc` — simplify to finance-only description. Lines 382–468 `_handle_multimodal_turn` — keep as-is (receipt photo scanning is finance-relevant). Lines 190–195 in system prompt — remove trip planning references, keep expense/finance guidance.
    - **Acceptance**: The system prompt no longer mentions transit, bus stops, trip planning, recipes, commute, whiteboard, groceries. The bus-continuation kernel check is removed.
    - **QA happy**: An agent turn with "spent $12" → expense logged. "bus 08057" → agent says it can't handle transit (or calls log_capability_gap with a custom message)
    - **QA failure**: A turn still tries to call a removed tool → that was never possible because the tool won't be in the registry. The model might still INVENT a transit name in tool_calls → `log_capability_gap` is fine
    - **Commit**: Edit `orchestrator/agent_loop.py`

- [x] 10. `app/ingress.py`: Remove whiteboard/pin/board callbacks, simplify slash commands
    - **References**: Lines 26–56 `_pending_pins`, `register_pending_pin`, `consume_pending_pin`. Lines 675–732 `pb:` callback handler. Lines 856–870 `/groceries` slash command. Lines 952–976 `/help` command with non-finance buttons. Lines 930–981 simplify help text. Line 508 `/split` — keep (finance-relevant).
    - **Acceptance**: No whiteboard pin/pending pin code exists. `/groceries` command removed. `/help` shows only finance commands. `pb:` callback not recognized.
    - **QA happy**: `/help` on Telegram returns finance-only help. `/groceries` returns "I don't know that command." A `pb:` callback is ignored.
    - **QA failure**: A whiteboard import in ingress.py causes ImportError → the import was from `capabilities.whiteboard.tools` / `core.models.WhiteboardProject` — remove the import and the handler.
    - **Commit**: Edit `app/ingress.py`

- [x] 11. `app/dashboard_api.py`: Remove board cover generation, whiteboard, grocery endpoints
    - **References**: Lines 54–297 board cover generation (`_generate_board_cover`, `_build_imagen_prompt`, `_schedule_cover_generation`, etc.). Lines 367–372 `GroceryCreateRequest` schema. All endpoints referencing `WhiteboardProject`, `WhiteboardBlock`, `GroceryItem`. Lines 1192+ (after the truncated read) whiteboard CRUD endpoints. Remove the entire whiteboard/grocery schema classes and endpoints.
    - **Acceptance**: `/api/dashboard/summary` no longer returns `pending_groceries_count` or `active_jobs_count`. No whiteboard CRUD endpoints exist. No cover generation imports.
    - **QA happy**: `GET /api/dashboard/summary` returns expense/income data only. `POST /api/dashboard/expenses` still works.
    - **QA failure**: A surviving endpoint calls `WhiteboardProject` → removed import → fix by removing the endpoint
    - **Commit**: Edit `app/dashboard_api.py`

- [x] 12. `app/main.py`: Remove startup data-cleanup for non-finance models
    - **References**: Lines 29–46 run a cleanup query for "bogus" expense transactions — keep this (it's expense-related). No whiteboard/board cleanup needed. But remove any whiteboard-related startup imports.
    - **Acceptance**: App boots without any reference to deleted models.
    - **QA happy**: `uvicorn app.main:app --port 8000` starts cleanly
    - **QA failure**: A startup import still references a removed model → the fix is to remove that import/reference
    - **Commit**: Edit `app/main.py` — verify no imports to deleted models

- [x] 13. `app/chat_api.py`: Remove grocery/reminder event emission
    - **References**: Lines 194–199 check for "grocery", "reminder", "scheduled" in replies — remove these non-finance event triggers. Keep only "expenses_changed" events.
    - **Acceptance**: Chat API no longer emits `groceries_changed` or `reminders_changed` events
    - **QA happy**: `POST /api/chat` with "spent $12" also emits `expenses_changed` event
    - **Commit**: Edit `app/chat_api.py`

- [x] 14. `core/scheduler.py`: Simplify to remove task-reminder scheduling
    - **References**: The scheduler has task-reminder functions (`remove_task_reminder`, `snooze_task_reminder`, `trigger_task_alert_now`). Since IOU settlement uses `TaskItem` but not through scheduler (settlement is handled inline in ingress.py/expenses), keep the cron job functionality (`_execute_scheduled_job`, job CRUD). Remove task-reminder-specific functions that aren't referenced by kept code.
    - **Acceptance**: `remove_task_reminder` may still be imported by ingress.py for IOU callbacks — check usage first. If referenced, keep it.
    - **QA happy**: Cron jobs for email sweep still trigger correctly. Task reminder functions are removed only if unreferenced.
    - **QA failure**: ingress.py's `td:` callback calls `remove_task_reminder` — check before removing
    - **Commit**: Edit `core/scheduler.py`

- [x] 15. `showcase/`: Simplify frontend to finance-only
    - **References**: `showcase/index.html`, `app.js`, `transactions.js`, `transaction-entry.js`, `styles.css`, `manifests-data.js` — need to read these to understand what to remove
    - **Acceptance**: The web cockpit shows only transaction ledger, charts, summary cards. No whiteboard tab, no groceries tab.
    - **QA happy**: Opening the cockpit shows finance dashboard. All transaction CRUD works.
    - **QA failure**: A whiteboard/board reference causes JS error → remove the reference
    - **Commit**: Edit files under `showcase/`

- [x] 16. `core/config.py`: Remove unused API key references
    - **References**: Lines 33–35: `tavily_api_key`, `google_maps_api_key`, `lta_account_key` — remove these (no longer needed). Line 87: `admin_only_capabilities` — remove `code-exec` from the set (or keep as empty).
    - **Acceptance**: Settings no longer expose removed capability keys
    - **QA happy**: `from core.config import settings; settings.tavily_api_key` raises `AttributeError`
    - **Commit**: Edit `core/config.py`

- [x] 17. `docs/`, `evals/`, `issues/`, `spec.md`, `spec-capability-gaps.md`: Remove stale documentation
    - **References**: These files reference the old multi-capability architecture
    - **Acceptance**: Files are removed. No code references them.
    - **QA happy**: `ls docs/` shows directory not found (or empty)
    - **Commit**: `git rm -rf docs/ evals/ issues/ spec.md spec-capability-gaps.md`

- [x] 18. Update `README.md` and `CONTEXT.md` to reflect simplified architecture
    - **References**: Both files list all the capabilities that are being removed
    - **Acceptance**: README and CONTEXT no longer mention transit, groceries, whiteboard, memory, code exec, bug logging, scheduled content, daily briefing, recipes
    - **QA happy**: A new developer reads README and understands the app is an expense/finance assistant
    - **Commit**: Edit `README.md`, `CONTEXT.md`, `map.md`

- [x] 19. `pyproject.toml`: Remove unused dependencies
    - **References**: `pgvector` (used by memory/embedding), `e2b` (used by code_sandbox) — no longer needed. Keep everything else.
    - **Acceptance**: `pip install -e .` succeeds without these deps
    - **QA happy**: `uv pip list` shows no `e2b` or `pgvector`
    - **Commit**: Edit `pyproject.toml`

## Final verification wave

- [x] F1. **App boot smoke test**: Run `uvicorn app.main:app --port 8000` and confirm it starts without ImportError or runtime crash. Verify `/health` returns 200.
- [x] F2. **Agent expense turn**: `POST /api/chat` with `{"message": "spent $12 at starbucks"}` — confirm the reply acknowledges the expense and a DB row was created.
- [x] F3. **Dashboard loads**: `GET /api/dashboard/summary` returns 200 with expense/income data and no reference to groceries/whiteboard.
- [x] F4. **Telegram ingress**: Confirm `/start` works via the webhook simulation (or test webhook endpoint). The reply should mention only expenses and finance.
- [x] F5. **No dangling imports**: `python -c "from core.models import GroceryItem"` raises `ImportError`. `python -c "from capabilities.routes.tools import get_bus_timings"` raises `ImportError`.
- [x] F6. **Tests pass**: `pytest tests/ -v` — all kept tests pass, no collected tests from deleted directories.

## Commit strategy

Single commit: `strip codebase to expense/finance agent — remove routes, recipes, whiteboard, memory, bug_logging, code_exec, scheduled_content, daily_briefing, transit, groceries, board/pin callbacks, all non-finance skills, tests, models, and docs`

Rationale: This is a coherent atomic change — the app moves from multi-capability to finance-only. A single commit makes it clear what changed and is easy to revert as a unit. The commit message lists everything removed.

## Success criteria

1. ✅ App boots cleanly (`uvicorn app.main:app` starts without errors)
2. ✅ All expense/finance tools work (log expense, log income, split bill, settle IOU, receipt scan)
3. ✅ Dashboard returns finance data with no references to removed features
4. ✅ All non-finance modules/skills/tests/models are gone (verified by `git diff --stat` showing deletions)
5. ✅ Kept tests pass (`pytest tests/ -v`)
6. ✅ No dangling imports in any survivor file