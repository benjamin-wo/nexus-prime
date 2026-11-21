# Domain panels: build plan

Status: proposed, waiting for the owner's approval. Decision: [ADR 0001](../adr/0001-prime-opens-domain-panels.md). Research: [`reports/Agent driven UI for Nexus domains.md`](../../reports/Agent%20driven%20UI%20for%20Nexus%20domains.md).

## Summary

As the user talks to Nexus, the **domain** they are talking about appears as a **panel** beside the chat, with the right figures. Panels open from the domain tools Prime actually calls, through a typed **panel registry**. They are the same hand-built components the Money, Invest and Travel tabs use, filled by the same service code the tools use. Success is **accuracy**: the right panel, with the right figures, at the right time, and nothing when nothing fits.

The plan follows the owner's workflow in `CLAUDE.md`: small independent steps, each naming its files and how to check it, each delegated to a worker. Phase 0 measures before any UI exists. The eval harness gets expected panels, new metrics and new case types, and a baseline on the production model comes out of it. If the baseline is not good enough, routing is fixed first, because panel accuracy is tool-selection accuracy.

## Phases at a glance

| Phase | What it delivers | Visible to users |
|---|---|---|
| 0 | Panel labels and metrics in the eval harness, new case types, a baseline on the production model, routing fixes until the targets are met | No |
| 1 | Registry (Python source of truth, generated TypeScript types), `panel.upsert` / `panel.close` from the agent loop, panel state kept per user | No |
| 2 | Desktop panel stage with three Finance panels and one Travel panel, behind a setting | Owner only |
| 3 | Carry-over and update semantics ("and last month?"), "updated since", selection sent back to the agent | Owner only |
| 4 | The `show_panel` fallback tool | Owner only, then members |
| 5 | Online signals and the weekly review loop | Members |
| 6 | Mobile: shared TypeScript package, the bottom sheet, version negotiation | Phones |
| 7 | Later domains and cross-domain panels, deterministic proactive chips | Later |

## How to read a step

- **Size:** S is under half a day, M is one to two days, L is three days or more.
- **Depends on / Parallel with:** steps with no dependency between them can go to workers at the same time. A step that touches the same file as another is not parallel with it even if neither depends on the other; those are noted.
- **Verify** gives the commands. Every Python step also passes `uv run ruff check . && uv run ruff format --check . && uv run mypy`, and every web step also passes `cd web && npm run typecheck`. Integration tests need Postgres: `TEST_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/postgres`. Real-model eval runs need `OPENROUTER_API_KEY` and `EVAL_DATABASE_URL`, so the owner runs them or supplies the keys.
- New files are marked **(new)**. Names are proposals; a worker may pick a better one if it says so.
- Numbers called **proposal** are starting points for the owner to change, not findings.

## Panel kinds

The registry names every kind up front, so evals can score kinds whose component is not built yet. A kind is `planned` (scored in evals, never sent to a client), `live` (sent) or `held` (built but not shown until a review clears it).

| Kind | Opened by (tools) | Params | Web data today | Component today | Phase |
|---|---|---|---|---|---|
| `finance.month_outlook` | `month_outlook` | `month`, `adjustments` (signed amounts the user mentioned) | none: new `GET /api/month-outlook` calling the same use case as the tool (`application/month_outlook.py`) | new | 2 |
| `finance.budgets` | `list_budgets` | `month` | `GET /api/budgets`, `/api/budgets/month` | `pages/BudgetsPage.tsx` | 2 |
| `finance.transactions` | `find_transactions`, `query_ledger` (the rows behind a total, average or ranking) | `start`, `end`, `direction`, `category`, `merchant`, `wallet`, `min`/`max` | `GET /api/transactions` | `pages/Ledger.tsx` | 2 |
| `travel.trip_budget` | `trip_status` | `trip_id` | `GET /api/travel/trips/{id}` | `pages/TripMoney.tsx` | 2 |
| `finance.cash_flow` | `cash_flow` | `month` or `days` | `GET /api/cashflow` | `pages/CashFlow.tsx` | 3 or later |
| `finance.spending` | `spending_summary` | `start`, `end` | `GET /api/summary` | `components/CategoryBars.tsx` | later |
| `finance.bills`, `finance.subscriptions` | `list_bills`, `list_subscriptions` | none | `GET /api/bills`, `/api/subscriptions` | `pages/Bills.tsx`, `Subscriptions.tsx` | later |
| `finance.portfolio`, `finance.stock`, `finance.watchlist` | `show_portfolio`, `stock_levels`, `show_watchlist` | `symbol` for `stock` | `GET /api/investments`, `/stocks/{symbol}`, `/watchlist` | `pages/Investment.tsx`, `Stock.tsx`, `Watchlist.tsx` | later |
| `finance.plan` | `show_plan` | `plan_id` | `GET /api/investments/plans/{id}` | `pages/Investment.tsx` | `held`, see the regulatory notes in the ADR |
| `travel.itinerary`, `travel.trips` | `add_to_itinerary`, `research_trip`, `list_trips` | `trip_id` | `GET /api/travel/trips`, `/trips/{id}` | `pages/Trips.tsx` | later |

Tools that surface nothing in v1: every write tool, `calculate`, `web_search`, `product_prices`, `flight_prices`, `flight_status`, `set_timezone`, `load_skill`, `answer_email` and the voice tools. Which write tools may surface a panel (`set_budget`, `create_trip`) is an open question.

---

## Phase 0: measure before any UI

Nothing user-visible ships. The aim is a number for "does Prime call the tool that opens the right panel", on the production model, before a line of panel UI exists.

Parallel plan: 0.1 first. Then 0.2 and 0.4 and 0.6 in parallel. 0.3 follows 0.2. 0.5 needs 0.2, 0.3 and 0.4. 0.7 is a loop on 0.5.

### 0.1 Registry stub: tools to panel kinds (S)

- **Goal:** one place that says which panel kinds a tool surfaces, and which tools surface none, so eval labels can be derived from expected tools.
- **Files:** `src/nexus/panels/__init__.py` (new), `src/nexus/panels/registry.py` (new: `PanelKind` names with their domain and status, `SURFACING: dict[str, tuple[str, ...]]`, `NON_SURFACING: frozenset[str]`, and `panels_for_calls(calls) -> set[str]`), `tests/unit/test_panel_registry.py` (new).
- **Constraints:** no params, no schemas yet (Phase 1). Kind names follow the table above. Domain is a string (`finance`, `travel`); do not add a second department registry (`application/departments.py` stays as it is).
- **Verify:** `uv run pytest tests/unit/test_panel_registry.py` passes and includes a test that **every tool in `build_tools(...)` is in exactly one of `SURFACING` or `NON_SURFACING`**, so a new tool cannot be added without a decision. `uv run mypy`.

### 0.2 Harness: expected panels on cases and turns (M)

- **Goal:** a case can say which panels each turn should open, and the runner records which panels the turn's actual tool calls would open.
- **Files:** `src/nexus/evals/cases.py` (add `Case.panels: tuple[str, ...] | None = None` and `Turn.panels`; `None` means "derive from the case's `calls` and `used` for the last turn, or leave unscored if there are none", `()` means "must open nothing"), `src/nexus/evals/runner.py` (`TurnLog.panels` derived from `TurnLog.calls` through `panels_for_calls`; `CaseResult` carries expected and actual sets per turn; a wrong panel set does **not** fail the case's existing pass/fail, so the existing score is unchanged), `src/nexus/evals/panel_metrics.py` (new, pure functions), `tests/integration/test_evals.py` (extend `test_cases_are_well_formed`: every labelled kind exists in the registry; a derived label and an explicit one must agree where both exist), `tests/unit/test_eval_panels.py` (new).
- **Verify:** `uv run pytest tests/unit/test_eval_panels.py` and `TEST_DATABASE_URL=... uv run pytest tests/integration/test_evals.py tests/unit/test_eval_grading.py tests/unit/test_eval_repeat.py`. The existing eval tests must pass unchanged.
- **Parallel with:** 0.4, 0.6. Touches `cases.py`, as 0.4 does: 0.2 lands the two new fields first, then 0.4 adds cases.

### 0.3 Metrics and report (M)

- **Goal:** panel precision, recall and F1 (micro and macro), exact-set match per turn, over-surfacing rate (turns with an unexpected panel), under-surfacing rate (expected panel missing, including turns with no tool call), correct-silence rate (cases labelled `()`), carry-over accuracy, and a per-domain confusion table. With `--repeat N`, each is a mean with min and max across rounds, and `compare` shows them for two result files.
- **Files:** `src/nexus/evals/panel_metrics.py`, `src/nexus/evals/runner.py` (`Summary` gets the panel section and its JSON), `src/nexus/evals/__main__.py` (Markdown report section "Panels"), `src/nexus/evals/compare.py`, `tests/unit/test_eval_panels.py`.
- **Verify:** unit tests on hand-built `TurnLog`s with known answers (all right, one extra panel, one missing, an empty expected set, two rounds). `uv run pytest tests/unit/test_eval_panels.py tests/unit/test_eval_repeat.py`.
- **Depends on:** 0.2.

### 0.4 New eval cases (L)

- **Goal:** about 80 hand-labelled cases in new areas, on top of the labels that come free from the existing 298 cases. All data is made up, from the seed (the seeded user has a Japan trip with a 3,000 SGD budget, a dining budget and the 13 November clock for `money-math`).
- **Files:** `src/nexus/evals/cases.py` (new areas `panel-single`, `panel-silence`, `panel-carry`, `panel-multi`, `panel-topic`, `panel-near-miss`, `panel-no-tool`), `src/nexus/evals/seed.py` only if a case needs a figure the seed lacks.
- **Case types and rough counts:**
  - **Single-domain (about 20):** "how's my dining budget", "what did I spend on Grab this month", "show me the Japan trip's budget".
  - **Correct silence (about 12), labelled `()`:** small talk, general knowledge, "what's 9% GST on 1,250" (`calculate` only), "log coffee 5.50" (a write).
  - **Follow-up carry-over (about 10, multi-turn):** "how much is left to spend" then "and last month?" expects the same `finance.month_outlook` key with `month` changed; the same for transactions with another category.
  - **Implicit multi-domain (about 10):** "can I afford the Japan trip?" expects `travel.trip_budget` and `finance.month_outlook`; "how much have I spent on the Japan trip and what's left this month?".
  - **Topic switch (about 6):** budget talk, then a trip question: the trip panel appears and the budget panel is not re-fetched.
  - **Near-miss distractors (about 8):** an incidental `calculate` or a currency check inside a trip answer must not open a Finance panel; `find_transactions` used to price a trip cost must not open the full ledger (if it does, the registry needs a rule, see 1.1).
  - **No-tool answers (about 6), tagged `target="show_panel"`:** "when's my next payday" (answered from the snapshot) and "open my budget". They are expected to fail until Phase 4 and are reported separately so they do not hide regressions.
- **Label review:** the owner (or a second person) reads every explicit label before the baseline run. Label noise is the main way benchmarks like this go wrong.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_evals.py` (cases well formed, labels valid, figures match the seed). Run with a scripted model for two or three cases to prove grading end to end, as `tests/integration/test_evals.py` does.
- **Depends on:** 0.1, and 0.2 for the fields. Can be split by case type across several workers once 0.2 has landed.

### 0.5 Baseline on the production model (S, needs keys)

- **Goal:** the first panel numbers. Production settings from `docs/EVALS.md`: DeepSeek v4.1 Flash on the four recommended providers.
- **Run:** `OPENROUTER_API_KEY=... EVAL_DATABASE_URL=... uv run python -m nexus.evals --model deepseek/deepseek-v4.1-flash --providers deepinfra,fireworks,atlas-cloud,streamlake --repeat 3` (all cases, so panels are scored over the existing cases' derived labels too), then the same with `--area panel-single --area panel-silence --area panel-carry --area panel-multi --area panel-topic --area panel-near-miss --area panel-no-tool`. Roughly US$1 to 2 in model costs (about $0.0004 a case).
- **Files:** `docs/EVALS.md` (new section "Panel baseline" with the table, flaky cases and the date), `eval-results/` stays git-ignored.
- **Verify:** the report has a "Panels" section; the pass rate of the existing areas is within the usual noise of the last full run in `docs/EVALS.md` (the harness change must not move it).
- **Depends on:** 0.2, 0.3, 0.4.

### 0.6 Distractor-domain stress run (M)

- **Goal:** find out where one agent with skills starts to break, before Health exists.
- **Files:** `src/nexus/evals/distractors/` (new: stub `SKILL.md` folders for Health, Home & Family and one invented domain, each with plausible tool names that return canned text), `src/nexus/evals/__main__.py` (`--distractors N` binds N stub skills and their descriptions into the prompt, and a stricter `--distractors-core` puts their tools in `CORE_TOOLS`, as an upper bound), `src/nexus/evals/runner.py`, `tests/integration/test_evals.py` (stubs are well formed and never in production).
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_evals.py -k distractor`. Then the baseline cases with `--distractors 0`, `1`, `2`, `3` and `--repeat 3`; record in `docs/EVALS.md`.
- **Parallel with:** 0.4. **Depends on:** 0.2 (touches `runner.py` and `__main__.py`, so land after 0.2 and 0.3).

### 0.7 Routing fixes until the targets are met (M to L, loops on 0.5)

- **Goal:** if the baseline misses the targets below, raise tool-selection accuracy first: skill text, tool descriptions, examples in `src/nexus/skills/*/SKILL.md`, as M8d did. This is the cheapest accuracy there is and every fix helps chat as well as panels.
- **Files:** `src/nexus/skills/*/SKILL.md`, `src/nexus/agent/tools.py` (descriptions only), and `docs/EVALS.md`.
- **Verify:** rerun 0.5's commands and `python -m nexus.evals compare eval-results/<baseline>.json eval-results/<after>.json`; the **whole** existing set must not fall by more than the noise (a case that drops by 2 or more out of 3 is a regression, per `docs/EVALS.md`).

### Phase 0 exit criteria (proposals, set from the baseline)

Measured on the production model with `--repeat 3`, means:

- Panel precision **at least 0.95** and recall **at least 0.85** over the labelled single-domain cases. Precision is weighted over recall because a wrong panel costs more than a missing one.
- Exact-set match **at least 0.85** over all labelled turns outside the `panel-no-tool` area.
- Correct-silence rate **at least 0.95**, and over-surfacing at most 5% of turns.
- Carry-over accuracy **at least 0.85** (the right key with the right changed param).
- Implicit multi-domain: precision at least 0.95, recall reported but not gating (it tests multi-step planning).
- Distractor run: tool-selection pass rate falls by at most 3 points with three stub domains. If it falls more, stop and decide on sub-agents (ADR decision 5) before building more.
- No case in a gated area fails every round.
- The baseline and the distractor table are in `docs/EVALS.md`, and the owner has reviewed the explicit labels.

If these cannot be met by 0.7, the panel stage is not built yet, and the owner decides whether to change the numbers or the model.

---

## Phase 1: registry and stream (invisible)

Starts once 0.1 is merged; it can overlap 0.4 to 0.7, since users see nothing. The stage (Phase 2) waits for the Phase 0 exit.

Parallel plan: 1.1, then 1.2, 1.3 and 1.5 in parallel, then 1.4.

### 1.1 Full registry with params (M)

- **Goal:** each kind has a Pydantic params model, a stable key, a function that builds params from a tool call and its result, a `summary` builder, a `version` and a status (`planned` / `live` / `held`).
- **Files:** `src/nexus/panels/registry.py`, `src/nexus/panels/kinds.py` (new: the four first kinds in full, the rest as names), `src/nexus/panels/events.py` (new: `PanelUpsert`, `PanelClose`), `tests/unit/test_panel_registry.py`.
- **Rules to build in:**
  - Params carry ids the tool already resolved ("Japan" becomes `trip_id`); never a `user_id` (the tenant comes from the sign-in).
  - Key = kind plus entity: `finance.month_outlook`, `finance.budgets`, `finance.transactions` (one per thread; the filters are params), `travel.trip_budget:<trip_id>`.
  - Param changes are additive only once a kind is `live` (a test compares the schema against a stored snapshot).
  - A tool can surface conditionally (`when(args)`) if 0.4's near-miss cases show over-surfacing; add the rule only then.
- **Verify:** `uv run pytest tests/unit/test_panel_registry.py` (round trip, key stability, unknown kind rejected, a param that is a `user_id` rejected); `uv run mypy`.

### 1.2 Generated TypeScript types (S)

- **Goal:** the web client gets kinds, params and event types from the registry, never by hand. The pattern exists: `scripts/brand_icons.py` writes `web/src/assets/nexusBrand.generated.ts`.
- **Files:** `scripts/gen_panel_types.py` (new, with `--check`), `web/src/panels/registry.generated.ts` (new), `tests/unit/test_panel_types_generated.py` (new: the committed file equals the generated one).
- **Verify:** `uv run python scripts/gen_panel_types.py --check`, `uv run pytest tests/unit/test_panel_types_generated.py`, `cd web && npm run typecheck`.
- **Depends on:** 1.1.

### 1.3 Tools report what they resolved (M)

- **Goal:** a surfacing tool returns the resolved panel params and summary alongside its text, so the loop can emit them. Only the four first kinds' tools change.
- **Files:** `src/nexus/agent/tools.py` (`ToolResult` gets `panels: list[PanelRef] = []`; `month_outlook`, `list_budgets`, `find_transactions`, `query_ledger`, `trip_status` fill it), `src/nexus/panels/registry.py`, `tests/integration/test_month_outlook.py` and `tests/integration/test_agent.py` (extend).
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_month_outlook.py tests/integration/test_agent.py -k panel`. A test checks `summary` figures equal the figures in the tool's own text.
- **Depends on:** 1.1.

### 1.4 The agent loop emits panel events (M)

- **Goal:** a `PanelSink`, like the existing `StepSink`, fed from the loop right after a surfacing tool returns without an `Error:`; `chat_stream.py` turns it into `panel.upsert` / `panel.close` frames. Dedupe in the turn: the same key twice becomes one upsert with the latest params; a key is never closed and reopened in a turn. `panel.close` is emitted when the turn deletes the panel's entity (for example `delete_trip`). Telegram and every caller without a sink are unchanged.
- **Files:** `src/nexus/agent/progress.py` (the sink type and context variable), `src/nexus/agent/graph.py` (next to `progress.report(...)` in the tool step, about line 1102 and 1139), `src/nexus/agent/service.py` (`handle_text(..., on_panel=...)`), `src/nexus/channels/web/chat_stream.py` (frames and the module docstring), `tests/integration/test_web_api.py` (extend the chat stream tests), `tests/integration/test_agent.py`.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_web_api.py tests/integration/test_agent.py -k "panel or stream"`. Tests: a turn that calls `month_outlook` yields one `panel.upsert` **before** the `replies` frame; a failed tool yields none; two calls for one key yield one; a turn with only `calculate` yields none; the Telegram path yields none and its replies are byte-identical to before. Also add an eval-trace assertion in the harness that the panel event comes at tool time (0.3's "event order" check).
- **Depends on:** 1.3.

### 1.5 Panel state kept per user (M)

- **Goal:** the server records each opened panel (kind, params, key, turn `ref`, lifecycle) so a reload, a broken stream and the `POST /api/chat` fallback do not lose panels. **No figures stored.**
- **Files:** `src/nexus/infra/db/tables.py` and a migration (`uv run alembic revision -m "chat panels"`; new table `chat_panels` with row-level security like the other user tables), `src/nexus/application/panels.py` (new: open, update, close, list, prune after 30 days), `src/nexus/application/user_data.py` (add to the erase list; **leave out of the export**, it is UI state), `src/nexus/channels/web/api.py` (`GET /api/chat/panels`, `POST /api/chat/panels/{id}` for pin and dismiss), `tests/integration/test_panels.py` (new), `tests/unit/test_user_data_coverage.py` (it should fail until the new table is covered) and `tests/integration/test_your_data.py`.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_panels.py tests/integration/test_your_data.py` and `uv run pytest tests/unit/test_user_data_coverage.py`, including a cross-tenant test (another user's panels are never listed or changed) and "Delete my data removes the rows"; the migration test that checks `alembic upgrade head` matches `tables.py`.
- **Parallel with:** 1.2, 1.3. **Depends on:** 1.1.

### Phase 1 exit criteria

- Every test above passes, and the full suite (`uv run pytest`) is green, run with `TEST_DATABASE_URL`.
- The stream behaves as specified with a scripted model, and a real-model run of `--area panel-single` shows the events agree with the harness's derived labels (the same tool calls, so the same kinds).
- Nothing changes for a client that ignores the new events: `cd web && npx vitest run src/chatStream.test.ts src/ChatDrawer.stream.test.tsx` still passes.

---

## Phase 2: desktop panel stage (owner only)

Waits for the Phase 0 exit. Panels are behind a setting, off by default.

Parallel plan: 2.1, 2.2 and 2.3a to 2.3d all in parallel (different files). 2.4 needs 2.1, 2.2 and at least one of 2.3. 2.5 needs 1.4. 2.6 and 2.7 close the phase.

### 2.1 Read the new events (S)

- **Goal:** `streamChat` calls `onPanel(event)` for `panel.upsert` and `panel.close`, typed from the generated file, and ignores unknown kinds and versions.
- **Files:** `web/src/chatStream.ts`, `web/src/chatStream.test.ts`, `web/src/ChatDrawer.stream.test.tsx`.
- **Verify:** `cd web && npx vitest run src/chatStream.test.ts src/ChatDrawer.stream.test.tsx`.
- **Depends on:** 1.2.

### 2.2 Stage state (M)

- **Goal:** a pure reducer for the stage: lifecycle (suggested, open, pinned, dismissed, history), update in place on the same key, never replace a pinned or touched panel (a second panel opens beside it), a dismissed key does not reopen on its own unless the user asks for it explicitly, and the budget of one expanded plus up to three compact panels (proposal). Restores from `GET /api/chat/panels`.
- **Files:** `web/src/panels/stageReducer.ts` (new), `web/src/panels/usePanelStage.ts` (new), `web/src/panels/stageReducer.test.ts` (new).
- **Verify:** `cd web && npx vitest run src/panels/stageReducer.test.ts`: table-driven cases for each rule above, including "same key, new month updates in place".
- **Depends on:** 1.2, 1.5 for the restore call.

### 2.3 The first four panels (M each; run in parallel)

Each step splits the page's body into a component that takes its filters as props (the tab keeps its URL-driven behaviour), then adds the panel wrapper (title, plain-words query, as-of, "Open in Money" and "Ask Nexus about this" actions). Read-only. The panel and the tab must share the component.

- **2.3a `finance.month_outlook`:** `GET /api/month-outlook?month=&adjust=` (repeated `adjust=<signed amount>:<label>`, at most `MAX_ADJUSTMENTS` = 20) in `src/nexus/channels/web/api.py`, calling `month_outlook` in `application/month_outlook.py` exactly as the tool does; `web/src/panels/MonthOutlookPanel.tsx` (new) with received, spent, still expected, projected month-end net, the user's adjustments, overall and headroom, and the list of items with no amount. Verify: `TEST_DATABASE_URL=... uv run pytest tests/integration/test_month_outlook.py tests/integration/test_web_api.py -k outlook`; `cd web && npx vitest run src/panels/MonthOutlookPanel.test.tsx`.
- **2.3b `finance.budgets`:** `web/src/pages/BudgetsPage.tsx` into a shared body, `web/src/panels/BudgetsPanel.tsx` (new). Verify: `cd web && npx vitest run src/pages/BudgetsPage.test.tsx src/panels/BudgetsPanel.test.tsx`.
- **2.3c `finance.transactions`:** a compact read-only list from `web/src/pages/Ledger.tsx` with the filters as props (the page's bulk edit and sort stay on the tab). Verify: `cd web && npx vitest run src/pages/Ledger.test.tsx src/panels/TransactionsPanel.test.tsx`. This is the riskiest extraction; if the page cannot be split cleanly, build the panel on the same endpoint and share only the row component.
- **2.3d `travel.trip_budget`:** `web/src/pages/TripMoney.tsx` (owner only) into a shared body, `web/src/panels/TripBudgetPanel.tsx` (new). A trip **member** gets the endpoint's refusal and the panel shows "Only <owner> can see a trip's money", never figures. Verify: `cd web && npx vitest run src/pages/TripMoney.test.tsx src/panels/TripBudgetPanel.test.tsx` and a backend test that a member's request is refused.

### 2.3e Figures parity tests (S)

- **Goal:** enforce "the panel is the system of record". For each of the four kinds, a test seeds a user, runs the tool and the panel endpoint with the same params, and asserts the headline figures are equal.
- **Files:** `tests/integration/test_panel_parity.py` (new).
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_panel_parity.py`.
- **Depends on:** 1.3 and the endpoints from 2.3a.

### 2.4 Stage and layout (L)

- **Goal:** on wide screens, a fixed chat column beside a panel stage; below the breakpoint, nothing changes yet (panels are hidden and the drawer works as today). Each panel card shows its caption ("Opened because you asked about <topic>", linked to the message), as-of time, pin, dismiss, collapse and a history list of closed panels. New panels do not steal focus; a polite live region announces "Budget opened".
- **Files:** `web/src/components/PanelStage.tsx` (new), `web/src/components/PanelCard.tsx` (new), `web/src/components/Shell.tsx`, `web/src/components/ChatDrawer.tsx` (the chat renders as a column when docked), `web/src/App.tsx`, `web/src/styles.css`, and tests next to each (`Shell.test.tsx`, `ChatDrawer.stream.test.tsx`, `PanelStage.test.tsx`).
- **Constraint:** follow `DESIGN.md`. The chat side is chosen once and never moves (owner's question 1).
- **Verify:** `cd web && npx vitest run src/components src/panels` and `npx playwright test e2e/panels.spec.ts` (from 2.7). Check 320px and a typical laptop width, light and dark.
- **Depends on:** 2.1, 2.2, one of 2.3.

### 2.5 Open panels go back to the agent (M)

- **Goal:** each chat request carries the open panels (id, kind, params, pinned, selection), at most 8, validated against the registry (`user_id` and unknown params rejected). The system prompt gets a short "Open panels" block after `ABOUT_THE_USER`, as data, so "that one" and "drop the hotel" resolve.
- **Files:** `src/nexus/channels/web/api.py` (`ChatIn` gets `panels`), `src/nexus/channels/web/chat_stream.py`, `src/nexus/agent/service.py`, `src/nexus/agent/graph.py` (`_prompt`), `web/src/chatStream.ts`, `web/src/components/ChatDrawer.tsx`, `src/nexus/evals/cases.py` and `runner.py` (a `Turn.open_panels` so cases can start with panels open), `tests/integration/test_web_api.py`, `tests/integration/test_agent_context.py`.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_web_api.py tests/integration/test_agent_context.py -k panel`; `cd web && npx vitest run src/chatStream.test.ts`. A hostile payload (huge, a fake kind, an instruction in a param string) is dropped or truncated and never reaches the prompt as an instruction.
- **Depends on:** 1.4. **Parallel with:** 2.3, 2.4.

### 2.6 The setting, and accessibility (S)

- **Goal:** `PANELS_ENABLED` (off by default; whether it is per user is open question 3) gates both the emitting of events and the stage. Keyboard: panels reachable, dismiss and pin by key, focus never taken from the composer.
- **Files:** `src/nexus/settings.py`, `src/nexus/channels/web/api.py` (`/api/config` tells the client), `web/src/panels/usePanelStage.ts`, `docs/OPERATIONS.md` (a short section).
- **Verify:** `uv run pytest tests/unit/test_settings.py`; `cd web && npx vitest run src/panels`.

### 2.7 Playwright journeys (M)

- **Goal:** the real flows, against the fake API in `web/e2e/fake-api.ts`: ask about a budget and the panel opens beside the chat with its caption; "can I afford the Japan trip" opens two panels; pin one, ask again and it stays; dismiss and it does not return unasked; reload and the stage is restored; a stream that breaks mid-turn still shows the panels once the history catches up.
- **Files:** `web/e2e/panels.spec.ts` (new), `web/e2e/fake-api.ts`.
- **Verify:** `cd web && npx playwright test e2e/panels.spec.ts` at desktop width, plus `npx playwright test` whole (the `mobile` project must be unchanged).
- **Depends on:** 2.4.

### Phase 2 exit criteria

- All Phase 2 tests green, plus the full `uv run pytest`, `cd web && npx vitest run`, `npx playwright test`.
- Parity tests pass for all four kinds.
- Re-run the Phase 0 panel evals on the production model after the code change; every Phase 0 target still holds (the stage must not move accuracy, and if it does something is wrong in the loop).
- The owner uses it for a week with the setting on; every wrong panel, missing panel and annoyance is written down as a made-up eval case.

---

## Phase 3: carry-over and update semantics (owner only)

Parallel plan: 3.1, 3.2, 3.3 and 3.4 are largely independent.

### 3.1 Update rules in code (S)

- **Goal:** the rules that make "and last month?" update in place. Same key with new params: upsert, same card. Same kind while the existing card is pinned: a second card opens. A key the turn already opened is not opened twice. A card the user has not touched for N turns collapses (N is a proposal, 5), but is never removed on the user's behalf.
- **Files:** `src/nexus/panels/registry.py` (`key_of`), `src/nexus/application/panels.py`, `web/src/panels/stageReducer.ts` and its test.
- **Verify:** `uv run pytest tests/unit/test_panel_registry.py tests/integration/test_panels.py`; `cd web && npx vitest run src/panels/stageReducer.test.ts`.

### 3.2 Carry-over passes (M, eval-driven)

- **Goal:** the `panel-carry` cases reach the target. The UI follows the agent: "and last month?" works only if Prime calls the same tool with a changed `month`, so any gap is fixed in skill text and tool descriptions, not the UI.
- **Files:** `src/nexus/skills/cashflow/SKILL.md`, `src/nexus/skills/expenses/SKILL.md`, `src/nexus/skills/budgets/SKILL.md`, `src/nexus/agent/tools.py` (descriptions), `src/nexus/evals/cases.py`.
- **Verify:** `uv run python -m nexus.evals --model deepseek/deepseek-v4.1-flash --providers deepinfra,fireworks,atlas-cloud,streamlake --area panel-carry --repeat 3` and the whole set with `compare` against the Phase 0 baseline.

### 3.3 "Updated since" (S)

- **Goal:** if the fetched figures differ from the event's `summary`, the panel shows a small "updated since this answer" hint with a refresh, and never silently contradicts the chat.
- **Files:** `web/src/panels/PanelCard.tsx`, `web/src/panels/usePanelData.ts` (new: query by params, `initialData` from `summary`), tests next to them.
- **Verify:** `cd web && npx vitest run src/panels`; a Playwright case where a logged expense changes the figure between answer and fetch.

### 3.4 Selection and "that one" (M)

- **Goal:** cases that start with panels open and ask "what's in that category?" or "drop the hotel" call the right tool with the right argument.
- **Files:** `src/nexus/evals/cases.py` (area `panel-selection`, using `Turn.open_panels` from 2.5), `src/nexus/agent/graph.py` (the open-panels block wording), `src/nexus/skills/*/SKILL.md` if needed.
- **Verify:** `uv run python -m nexus.evals ... --area panel-selection --repeat 3`.
- **Depends on:** 2.5.

### Phase 3 exit criteria

- Carry-over accuracy at least 0.85 and topic-switch cases pass at least 0.9 on the production model (proposals).
- Playwright shows no flicker: a follow-up updates the same card without it closing and reopening (assert the DOM node persists).
- The rest of the Phase 0 targets still hold.

---

## Phase 4: the `show_panel` fallback

### 4.1 The tool (M)

- **Goal:** `show_panel(kind, params, action)` with `action` `open` (default) or `close`, offered every turn, for turns with no domain tool ("when's my next payday?") and requests like "open my budget" or "close the budget". The server ignores it when a domain tool already surfaced that key in the turn, and refuses unknown kinds with the list of valid ones, as `_unknown_tool` does. Its description carries three to five worked examples, since one to five examples per tool raised complex-parameter accuracy from 72% to 90% in Anthropic's report.
- **Files:** `src/nexus/agent/tools.py` (the tool), `src/nexus/agent/graph.py` (`CORE_TOOLS`: this changes the cached prompt prefix, which the plan accepts), `src/nexus/agent/progress.py` (`LABELS["show_panel"] = "Opening the panel"`), `src/nexus/panels/registry.py` (`show_panel` is in `NON_SURFACING`, handled specially), `tests/integration/test_agent.py`, `tests/unit/test_panel_registry.py`.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_agent.py tests/unit/test_panel_registry.py -k panel`; `tests/integration/test_evals.py` (the cases' tool names still exist).

### 4.2 Prompt and skill wording (S)

- **Goal:** say plainly when to call it: only when the user asks to see something, or when answering from the snapshot a question a panel answers. Never alongside a domain tool for the same thing, never for small talk. It shows nothing new to quote: Prime quotes only figures it has, from the snapshot or a tool.
- **Files:** `src/nexus/agent/graph.py` (system prompt), the relevant `src/nexus/skills/*/SKILL.md`.
- **Verify:** as 4.3.

### 4.3 Evals: gains without regressions (M)

- **Goal:** the `panel-no-tool` cases now pass; silence and everything else do not regress; `show_panel` is never called twice in a turn (`at_most`) or for a kind a tool already opened.
- **Files:** `src/nexus/evals/cases.py` (`at_most` and `forbid` on the silence cases).
- **Verify:** the whole set, `--repeat 3`, before and after, then `python -m nexus.evals compare`.

### Phase 4 exit criteria

- `panel-no-tool` recall at least 0.8 (proposal), correct-silence not lower than the Phase 0 figure, the whole existing set within noise of the baseline (no case down by 2 or more out of 3).
- The gates from Phase 0 still hold, with the new tool in `CORE_TOOLS`.
- After this the owner may turn panels on for members, as a setting, still opt-in.

---

## Phase 5: online signals and the weekly loop

Parallel plan: 5.1, 5.2 and 5.3 in parallel.

### 5.1 Signals (M)

- **Goal:** record per panel: opened by (agent / tab / `show_panel`), dismissed with time-to-dismiss, pinned, interacted with, **manual open of a panel Prime did not surface** (false negative), and **re-ask** (the user asks for the same kind within two turns of an answer that did not surface it). Kinds, domains, triggers and timings only: no params, no figures, no text.
- **Files:** `src/nexus/channels/web/api.py` (`POST /api/panels/events`, batched, with the CSRF header), `src/nexus/application/panels.py`, `web/src/panels/telemetry.ts` (new), a use of `ops.emit` as the tool step does, `tests/integration/test_panels.py`.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_panels.py -k telemetry`; `cd web && npx vitest run src/panels/telemetry.test.ts`. A test proves no param or figure is ever written.

### 5.2 Weekly review without real data (S)

- **Goal:** turn signals into new eval cases without putting anyone's data in the repo. A script lists last week's fast dismissals, manual opens and re-asks as `(kind, domain, trigger, seconds)` only; the owner reads those turns in the app and writes **made-up** cases for `panel-*` areas by hand.
- **Files:** `scripts/panel_signals.py` (new), `docs/OPERATIONS.md` (a short "Panels" section).
- **Verify:** `uv run pytest tests/unit -k panel_signals`; the script prints only the allowed fields.

### 5.3 Owner view (S)

- **Goal:** panel opens, dismiss rate, fast-dismiss rate, manual opens and re-asks by kind, on the page where the owner already sees costs and ops.
- **Files:** `src/nexus/channels/web/ops_api.py`, `web/src/pages/Costs.tsx` (or the ops page, whichever the owner uses), tests next to them.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_ops.py`; `cd web && npx vitest run src/pages/Costs.test.tsx`.

### Phase 5 exit criteria (proposals)

- After two weeks with real use: fewer than 10% of agent-opened panels dismissed within 5 seconds; manual opens of a kind Prime could have surfaced fewer than 1 in 10 sessions; re-asks fewer than 5% of panel answers. These are guesses (no public baseline exists); replace them with what the first two weeks show.
- The weekly loop has run twice and produced at least five new made-up cases each time.

---

## Phase 6: mobile

Parallel plan: 6.1 first; 6.2, 6.3 and 6.4 then run in parallel.

### 6.1 A shared, DOM-free TypeScript package (L)

- **Goal:** the registry types, SSE parsing, the typed API client and the TanStack Query hooks move to a package either mobile client can use, and the desktop app loses nothing. React components stay in `web/`.
- **Files:** `packages/nexus-core/` (new: `package.json`, `src/panels/*`, `src/chatStream.ts`, `src/api.ts` parts), the root `package.json` (workspaces), `web/package.json`, `web/src/**` imports, `.github/workflows/ci.yml` (if install steps change), `scripts/gen_panel_types.py` (output path).
- **Verify:** `cd web && npm run typecheck && npx vitest run && npm run build`, `npx playwright test`; `uv run python scripts/gen_panel_types.py --check`. No test is deleted or weakened to make this pass.

### 6.2 One bottom sheet on phones (L)

- **Goal:** on phone widths and in the Telegram Mini App, the chat is the base layer with the composer in the thumb zone, and the stage is one **nonmodal** bottom sheet at peek height (the newest panel's title and headline figure) that expands to a modal. Several panels are swipeable cards in the one sheet, never stacked sheets. It collapses to a chip while the keyboard is up and uses `viewportStableHeight` inside Telegram, without a custom drag that fights Telegram's own sheet.
- **Files:** `web/src/components/PanelSheet.tsx` (new), `web/src/components/Sheet.tsx` (reuse), `web/src/viewport.ts`, `web/src/telegram.ts`, `web/src/components/Shell.tsx`, `web/src/styles.css`, tests next to each.
- **Verify:** `cd web && npx vitest run src/viewport.test.ts src/components/PanelSheet.test.tsx`; `npx playwright test e2e/panels.spec.ts --project=mobile` (and a 320px run); a manual check inside Telegram.

### 6.3 Kind and version negotiation (S)

- **Goal:** a client declares the `kind@version` pairs it supports on each chat request; the server sends only those, and for any other panel falls back to text (or a generic table) so an old native build never meets a kind it cannot draw. Param changes stay additive.
- **Files:** `src/nexus/channels/web/api.py`, `src/nexus/channels/web/chat_stream.py`, `src/nexus/panels/registry.py`, `web/src/chatStream.ts`, tests in `tests/integration/test_web_api.py`.
- **Verify:** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_web_api.py -k panel`.

### 6.4 In-app consent for model providers (S)

- **Goal:** a consent screen in web onboarding that names the model provider and says finance data goes to it. Apple's Guideline 5.1.2(i) requires this for a store app, and it is right for the web too.
- **Files:** `web/src/components/GetStarted.tsx`, `web/src/components/GetStarted.test.tsx`, `docs/SECURITY.md`.
- **Verify:** `cd web && npx vitest run src/components/GetStarted.test.tsx`; the wording reviewed by the owner.

### 6.5 Capacitor or Expo (decided: [ADR 0003](../adr/0003-ios-app-shell.md))

**Decided: ADR 0003** (an Expo shell around the live web app, native depth added in steps). The original framing follows. Not part of this plan's build. Capacitor is the faster route to a store, but risks rejection as a repackaged website unless it adds native depth (push, biometric unlock, offline read cache, share sheet). Expo gives a native-feeling sheet and chat but means a new UI layer on top of `packages/nexus-core`. Needs the owner.

### Phase 6 exit criteria

- All web checks green, with the shared package the only source of registry types.
- The phone journeys in 6.2 pass at 390px and 320px, with no horizontal scroll, and the desktop journeys still pass.
- The Phase 0 targets still hold on the production model (the phone changes should not touch accuracy).
- An old client (no `kind@version` support) gets text only in a test.

---

## Phase 7: later domains and cross-domain panels

Each item is its own plan when the time comes. The rules that must hold:

- **Health (wellness only).** Needs a data path first (no public HealthHub API; HealthKit and Health Connect are on-device and need a native app). Panels show trends and goals, never interpretations. **Before the skill ships, re-run the distractor run** (0.6) with the real Health skill bound, and decide on sub-agents if the 3-point rule is broken. Consent is scoped per domain. Legal review (HSA, PDPA) before any health data is stored.
- **Home & Family.** Starts from user input, the calendar and email. Same registry, same gates.
- **Cross-domain panels.** A trip budget (planned against actual spend in SGD, card used), an upcoming-obligations timeline (bills, renewals, flights, passport expiry) and health spending. These need typed entities with shared keys (date range, place, merchant, person) so Prime can compose a view from the domains it touched.
- **Proactive chips.** Only from deterministic triggers (a bill due, a flight tomorrow, a budget threshold crossed). Reuse **Needs you** and the notification levels, quiet hours and daily cap. A chip is ignorable, not a takeover. A separate eval measures false alarms, and a kind the user keeps dismissing is suppressed.
- **Telegram "Open in Nexus".** An optional link button on a reply whose tools surfaced a panel, deep-linking to the matching tab view with the same params. Decide after Phase 5 shows whether Telegram users want it.
- **Trade-plan panels (`finance.plan`).** Stay `held` until the MAS review in the ADR clears them.

---

## Overall dependency map

```
0.1 -> 0.2 -> 0.3 -> 0.5 -> 0.7 -> [Phase 0 exit]
 |      \-> 0.6 (after 0.3)         |
 |->0.4 ------^                      |
 |                                   v
 1.1 -> 1.2, 1.3, 1.5 (parallel) -> 1.4 -> [Phase 2: 2.1, 2.2, 2.3a-d parallel -> 2.4 -> 2.7]
                                      \-> 2.5 -> 3.4
 Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 7
```

Phase 1 may overlap 0.4 to 0.7. Nothing user-visible (Phase 2 onward) starts before the Phase 0 exit.

## Open questions for the owner

1. **Chat position on desktop.** Does the chat become a persistent column (and on which side) in place of the drawer opened from Home and the bar's N? It changes the app's shape on wide screens. The side should be chosen once and never move.
2. **Do write tools open panels?** Today they open nothing (the reply says what was done). Candidates: `set_budget` opens `finance.budgets`; `create_trip` opens the trip. Opening after a write is a good confirmation, but a write that needs confirmation should not open anything before the user says yes.
3. **Who gets panels first, and is the setting per user?** The plan assumes `PANELS_ENABLED` off, owner only, then members opt-in. Do demo accounts and trip guests ever see panels? (The plan says no.)
4. **Emit at tool start or tool end?** v1 emits when the tool returns, with resolved params. A loading skeleton at tool start would appear sooner but would need to guess the key from raw arguments and be retracted on failure. Worth it only if time-to-panel feels slow.
5. **Is the working budget (one expanded plus three compact panels) right?** No study gives a number. It should be tried with real use.
6. **How long is panel history kept?** The plan says 30 days, as for notifications.
7. **Investments under Finance.** Money and Invest are separate tabs and Invest is switchable (`show_invest`). If a user has Invest turned off in the menu, should `show_portfolio` still open a portfolio panel? The plan says yes, since they asked.
8. **Who reviews the eval labels, and who runs the paid evals?** Ground-truth labels need a human. Real-model runs need `OPENROUTER_API_KEY`; roughly US$1 to 2 a baseline run.
9. **Are the proposed targets right?** Precision 0.95, recall 0.85, silence 0.95, carry-over 0.85, at most 5% over-surfacing, at most 3 points lost per distractor domain. Set them after seeing the baseline, and say which are gates and which are reported.
10. **Telegram.** The plan adds nothing to Telegram in v1 and a deep-link button only later. Agree, or add the link in Phase 2?
11. **Legal review.** Who arranges the Singapore review of the MAS advice line (before `finance.plan` ever opens by itself), HSA wellness scope (before Health) and the PDPA breach runbook covering the new panel table?
12. **Capacitor or Expo.** Decided: ADR 0003.
