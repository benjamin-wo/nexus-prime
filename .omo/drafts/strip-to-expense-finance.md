# strip-to-expense-finance - Draft

## State

- **intent**: clear
- **review_required**: false
- **status**: awaiting-approval
- **slug**: strip-to-expense-finance

## User answers

1. **Email integration**: keep (recommended) — Gmail/Outlook OAuth for automated receipt extraction stays
2. **IOU / split tracking**: keep minimal — TaskItem stays only for IOU/settlement tracking
3. **search_web / fetch_url**: keep — general-utility tools stay for currency rates, merchant lookup, etc.
4. **Web cockpit**: keep — the showcase/ dashboard stays as finance visualizer

## Decisions recorded

- Scope IN: expense tracking, income tracking, bill splitting, IOU settlement, receipt scanning (photo + email), email-based expense extraction, search_web/fetch_url, web cockpit dashboard, Telegram ingress
- Scope OUT: transit/bus timings (routes), grocery lists (recipes), whiteboard/planning boards, memory/points, code execution, bug logging, daily briefing, scheduled content delivery
- Architecture: single LangGraph agent (unchanged), strip all non-finance capabilities/modules/skills/tests

## Components ledger

| Id | Component | Outcome | Status |
|----|-----------|---------|--------|
| C1 | core/models.py — trim to finance-relevant models only | Remove: GroceryItem, PointsBalance, WhiteboardProject, WhiteboardBlock, BusStop | pending |
| C2 | core/db.py — simplify init_db migrations | Remove whiteboard/board-cover/email-digest migrations | pending |
| C3 | core/skill_registry.py — trim TOOL_MODULES | Keep only expense, email, general; remove routes, recipes, whiteboard, memory, bug_logging, code_exec, scheduled_content | pending |
| C4 | core/code_sandbox.py — remove | No code_exec capability | pending |
| C5 | core/github_sync.py — remove | No production bug sync needed | pending |
| C6 | capabilities/ — remove non-finance modules | Remove: routes/, recipes/, whiteboard/, memory/, bug_logging/, code_exec/, scheduled_content_delivery/ | pending |
| C7 | skills/ — remove non-finance skills | Remove: bug-logging/, code-exec/, daily-briefing/, memory/, recipes-groceries/, reminders/ (IOU tasks kept via capabilities/reminders/), transit/, whiteboard-planning/ | pending |
| C8 | orchestrator/agent_loop.py — simplify | Remove bus/transit routing, trim system prompt to finance-only, remove recipe guidance | pending |
| C9 | app/ingress.py — simplify callbacks | Remove whiteboard/pin/board callbacks, simplify slash commands to finance-only | pending |
| C10 | app/dashboard_api.py — simplify | Remove whiteboard sections, grocery endpoints, board cover generation | pending |
| C11 | app/main.py — simplify startup | Remove whiteboard-board cleanup code | pending |
| C12 | showcase/ — simplify to finance-only | Remove whiteboard boards, groceries tabs from frontend | pending |
| C13 | tests/ — keep only finance-expense tests | Remove transit, whiteboard, recipes, bug, memory, code, scheduled content, etc. | pending |
| C14 | Additional files — clean up | Update README.md, CONTEXT.md, map.md, remove spec-capability-gaps.md, simplify Dockerfile deps, clean pyproject.toml | pending |
| C15 | core/scheduler.py — simplify | Remove task reminder scheduling, keep only cron jobs for email sweep | pending |
| C16 | app/chat_api.py — simplify events | Remove grocery/reminder event emission, keep only expense/finance events | pending |

## Approach

The simplification follows a **parallel strip then integrate** strategy:

**Phase A — Strip modules** (parallel-safe): Remove entire capability modules, skill folders, test files, and model classes that are out of scope. Each removal can be done independently.

**Phase B — Simplify survivors** (sequential): After stripping, simplify the remaining files — agent_loop.py system prompt, ingress.py callbacks, dashboard_api.py endpoints, main.py startup, showcase frontend.

**Phase C — Polish** (cleanup): Update README, CONTEXT, package deps, and ensure the app boots cleanly.

## Next workflow action

Present approval brief → wait for explicit okay → write plan (no high-accuracy review needed unless user requests it).