# Spoken canvas: build plan

Status: proposed, waiting for the owner's approval; the spoken part follows [ADR 0005](../adr/0005-prime-views.md) (views in the chat). Decision: [ADR 0006](../adr/0006-spoken-canvas.md). Builds on the panel prototype from [ADR 0001](../adr/0001-prime-opens-domain-panels.md) and [`domain-panels.md`](domain-panels.md), whose Phase 0 eval work carries over here.

## Summary

The user taps to talk. Prime answers aloud in a sentence or two, and the canvas shows the view that goes with the answer, chosen by Prime with `present` from a catalog of hand-built views, with the tools Prime called as the safety net. Figures always come from code. Desktop first, OpenRouter for speech both ways.

The plan follows `CLAUDE.md`: small steps, each with its files and how to check it, each given to a worker. Two tracks run side by side from the start: **views** (catalog, `present`, evals) and **speech** (text to speech, the talk loop). They meet in Phase 2, the canvas.

## Phases at a glance

| Phase | What it delivers | Visible to users |
|---|---|---|
| 0 | View catalog (renamed from panels), `present`, spoken style, evals with view and speech metrics, a baseline | No |
| 1 | Text to speech through OpenRouter, `POST /api/speech`, a spoken turn endpoint with `heard`, the client talk loop | No (owner can try it in the old chat) |
| 2 | The canvas: full-screen, talk button, captions, focus view and strip, ⌘K, six views, behind `CANVAS_ENABLED` | Owner only |
| 3 | Follow-ups update views, open views go back to Prime, pinning, confirm cards for writes | Owner only, then demo |
| 4 | Earlier speech (reply streamed token by token), opening briefing, more views | Members |
| Later | Phones, always-listening, Health and Home & Family views | Later |

## How to read a step

As in `domain-panels.md`: **S** is under half a day, **M** one to two days, **L** three or more. Every Python step also passes `uv run ruff check . && uv run ruff format --check . && uv run mypy`; every web step `cd web && npm run typecheck && npx vitest run`. Integration tests need Postgres (locally on port 5433, see `docker-compose.override.yml`). Real-model eval runs and the listening test need `OPENROUTER_API_KEY`, so the owner runs them. New files are marked **(new)**. Numbers marked **proposal** are for the owner to change.

## View catalog (first version)

| View | Opened by (tools, the safety net) | Params | Fills it | Component | Phase |
|---|---|---|---|---|---|
| `finance.month_outlook` | `month_outlook` | `month`, `adjustments` | `application/month_outlook.py` | from `panels/MonthOutlookPanel.tsx` | 2 |
| `finance.budgets` | `list_budgets` | `month` | budgets use case | from `panels/BudgetsPanel.tsx` | 2 |
| `finance.transactions` | `find_transactions`, `query_ledger` | `start`, `end`, `direction`, `category`, `merchant`, `wallet`, `min`/`max` | ledger query | from `panels/TransactionsPanel.tsx` | 2 |
| `travel.trip_budget` | `trip_status` | `trip_id` | trip money | from `panels/TripBudgetPanel.tsx` | 2 |
| `finance.spending` | `spending_summary` | `start`, `end` | spending summary | new, uses `components/CategoryBars.tsx` | 2 |
| `finance.affordability` | none (only `present`) | `amount` or `trip_id`, `month` | month outlook with the cost as an adjustment, plus the trip's money | new | 2 |
| `finance.bills` | `list_bills` | `days` | bills | new | 3 |
| `finance.cash_flow` | `cash_flow` | `month` or `days` | cash flow | new | 3 |
| `confirm` (card, not a view) | any write that pauses to confirm | the pending action | `agent/confirmation.py` | new | 3 |

---

## Phase 0: views and measurement (invisible)

Parallel plan: 0.1 first. Then 0.2, 0.3 and 0.4 in parallel. 0.5 needs all of them; 0.6 loops on 0.5.

### 0.1 Panels become the view catalog (M)

- **Goal:** one typed catalog of views, each with a spec, replacing `agent/panels.py`. Same behaviour as today, new names.
- **Files:** `src/nexus/agent/views.py` (new, from `panels.py`: `ViewKind`, `ViewSpec` with `name`, `description` (written for the model), `params` (Pydantic model), `key(params)`, `summary(result)`, `status` `planned`/`live`/`held`; `CATALOG`; `SURFACING` and `NON_SURFACING` kept), `src/nexus/agent/panels.py` (removed), `src/nexus/agent/progress.py`, `src/nexus/agent/service.py`, `src/nexus/channels/web/chat_stream.py` (imports, and `panel.upsert` sent as `view.show` with `focus` and `summary`), `tests/integration/test_panels.py` renamed `test_views.py`, `web/src/panels/types.ts` (parse `view.show`).
- **Constraints:** the test that every tool is classified stays. `summary` is built by code from the tool result. Specs for `finance.spending` and `finance.affordability` are added as `planned`.
- **Verify:** `uv run pytest tests/integration/test_views.py tests/unit`, `cd web && npx vitest run src/panels`.

### 0.2 The `present` tool (M)

- **Goal:** Prime can choose a view: `present(view, params, focus=True)`, checked against the catalog.
- **Files:** `src/nexus/agent/tools.py` (the tool; its description lists the live views from their specs), `src/nexus/agent/graph.py` (`present` in `CORE_TOOLS`, worked examples in the prompt: "can I afford Japan in March", "show me my budget", "how's this month"), `src/nexus/agent/views.py` (`resolve(view, params)`; unknown view or bad params come back as a tool error naming the allowed values), `src/nexus/agent/progress.py` (a `present` call emits `view.show`; a tool-mapped view the same turn also presented is sent once), `tests/integration/test_present.py` (new).
- **Constraints:** at most three views a turn, one with `focus`; a fourth is a tool error. `present` never takes figures, only params. It opens nothing on Telegram.
- **Verify:** `uv run pytest tests/integration/test_present.py tests/integration/test_views.py`.

### 0.3 Spoken style (S)

- **Goal:** a spoken turn gets short, listenable replies.
- **Files:** `src/nexus/agent/graph.py` (a spoken-style block added to the prompt when the turn is spoken: one or two sentences, no lists, emoji, tables or markdown, figures rounded the way people say them, the detail is on screen), `src/nexus/agent/service.py` (`handle_text(..., spoken=True)` carries the flag in the turn config), `tests/unit/test_spoken_style.py` (new).
- **Constraints:** the personality dials still set tone; this only sets shape. Telegram voice notes are not spoken turns (their reply is read, not heard).
- **Verify:** `uv run pytest tests/unit/test_spoken_style.py`.

### 0.4 Evals: views and speech (L)

- **Goal:** the numbers that decide whether the canvas is good enough, before it exists.
- **Files:** `src/nexus/evals/cases.py` (`views=` on a case, derived from expected tools through `SURFACING` unless given; `spoken=True`), `src/nexus/evals/checks.py` (`SpokenBrief`: at most two sentences and 45 words; `SpokenGrounded`: every figure in the reply appears in a tool result or a view summary from the turn), `src/nexus/evals/runner.py` and `src/nexus/evals/compare.py` (view precision, recall, exact-set match, correct silence, `present` refusals, as mean and spread over `--repeat`), about 60 new cases: single view, composite (affordability), "show me" with no tool, correct silence ("thanks"), follow-up ("and April?"), and the same cases spoken, `tests/unit/test_eval_views.py` (new).
- **Constraints:** cases are made up (PLAN rule 7). Reuse the metric design from `domain-panels.md` 0.2 and 0.3 rather than inventing a second one.
- **Verify:** `uv run pytest tests/unit/test_eval_views.py`; `uv run python -m nexus.evals --area views --dry-run` lists the cases.

### 0.5 Baseline on the production model (S, owner runs it)

- **Goal:** the starting numbers in `docs/EVALS.md`.
- **Verify:** `uv run python -m nexus.evals --area views --repeat 3` with `OPENROUTER_API_KEY` and `EVAL_DATABASE_URL`; the table is in `docs/EVALS.md`.

### 0.6 Fix routing until the targets hold (M, loops on 0.5)

- Changes to `present`'s description, the prompt's examples and view descriptions, re-run after each.

### Phase 0 exit (proposals)

On the production model, `--repeat 3`, means: view precision **at least 0.95**, recall **at least 0.85**, correct silence **at least 0.95**, `present` refusals **at most 2%** of calls, spoken brevity **at least 0.95**, spoken grounding **1.0** (any ungrounded figure is a bug to fix, not a rate to accept). If `present` is the weak part, the canvas starts on the tool mapping alone (ADR 0006 consequence).

---

## Phase 1: speech both ways (invisible to users)

Runs alongside Phase 0. 1.1 first; then 1.2 and 1.3 in parallel; 1.4 needs 1.2 and 1.3; 1.5 any time after 1.1.

### 1.1 Text to speech adapter (M)

- **Goal:** turn a sentence into audio through OpenRouter.
- **Files:** `src/nexus/application/ports.py` (`Speaker` protocol: `async speak(text, voice) -> bytes`, plus `SpeakError`), `src/nexus/infra/speech/openrouter_tts.py` (new: `POST https://openrouter.ai/api/v1/audio/speech`, `response_format` mp3, timeout, one fallback model), `src/nexus/settings.py` (`TTS_MODEL`, default `openai/gpt-4o-mini-tts-2025-12-15` until the listening test; `TTS_VOICE`; `TTS_FALLBACK_MODEL`; `TTS_DAILY_CHARACTERS` 20000, proposal; `TTS_DEMO_DAILY_CHARACTERS` 3000, proposal), `src/nexus/infra/costs*` (a `speech_out` feature, billed per character), `tests/unit/test_openrouter_tts.py` (new, with a fake HTTP transport).
- **Constraints:** never log the text or the audio, only the model, characters and time, as the speech-to-text adapter does. Model slugs carry their date suffix (short slugs are refused).
- **Verify:** `uv run pytest tests/unit/test_openrouter_tts.py`.

### 1.2 `POST /api/speech` (S)

- **Goal:** the client turns a reply sentence into audio.
- **Files:** `src/nexus/channels/web/api.py` (JSON `{text}`, at most 400 characters; returns `audio/mpeg`; 429 past the daily cap; 503 when speech isn't set up; CSRF as other posts), `tests/integration/test_speech_api.py` (new).
- **Constraints:** only signed-in users; the cap counts characters per user per local day. The text must be one Nexus said in the user's recent history (so the endpoint is not a free speech service): check it against the last turn's replies.
- **Verify:** `uv run pytest tests/integration/test_speech_api.py`.

### 1.3 A spoken turn as a stream (M)

- **Goal:** one request from recording to reply, with the transcript first.
- **Files:** `src/nexus/channels/web/api.py` (`POST /api/chat/talk`: multipart audio like `/chat/voice`, answered with the chat stream), `src/nexus/channels/web/chat_stream.py` (a `heard` frame first, then the turn as a spoken turn), `tests/integration/test_talk_stream.py` (new).
- **Constraints:** same size, type and rate rules as `/chat/voice`; reuse its code rather than copying it. An empty or failed transcript ends with `error`, never a turn.
- **Verify:** `uv run pytest tests/integration/test_talk_stream.py`.

### 1.4 Client talk loop (L)

- **Goal:** the browser side of a spoken turn, with no UI opinion yet.
- **Files:** `web/src/talk/useTalk.ts` (new: a state machine `idle → listening → sending → working → speaking → idle`, using `useVoiceRecorder.ts`; tapping in `speaking` or `working` stops playback and calls `/api/chat/stop`), `web/src/talk/speechQueue.ts` (new: splits the reply into sentences, fetches `/api/speech` for the first at once and the next while the first plays, plays in order with Web Audio, `stop()`), `web/src/talk/mute.ts` (new, remembered per user), `web/src/chatStream.ts` (`heard`, `view.show`, `view.close`, `confirm`), tests beside each (new).
- **Constraints:** muted, the loop skips speech and returns to `idle` when the reply arrives. A failed speech request falls back to the text, silently.
- **Verify:** `cd web && npx vitest run src/talk src/chatStream.test.ts`.

### 1.5 Listening test (S, owner)

- **Goal:** pick the speech model and voice by ear.
- **Files:** `scripts/tts_listen.py` (new: speaks ten made-up Nexus replies with each candidate model and voice into a local folder, with each one's price per 1,000 characters and time to first byte).
- **Verify:** the owner listens and sets `TTS_MODEL` and `TTS_VOICE`.

---

## Phase 2: the canvas (owner only)

Needs 0.1, 0.2 and 1.4. 2.1, 2.2 and 2.3 in parallel; 2.4 needs all three; 2.5 and 2.6 close the phase.

### 2.1 One endpoint for every view (M)

- **Goal:** `GET /api/views/{view}?<params>` returns the view's data from the same use case its tool uses.
- **Files:** `src/nexus/channels/web/views_api.py` (new: looks the view up in `CATALOG`, validates params with its model, calls its use case, returns data plus `as_of`), `src/nexus/main.py` (router), `tests/integration/test_views_api.py` (new: for each view, the figures equal the tool's figures for the same params).
- **Constraints:** each view keeps its tab's authorisation (a trip member never gets a trip's money). `planned` views answer 404.
- **Verify:** `uv run pytest tests/integration/test_views_api.py`.

### 2.2 Views (L, can split per view)

- **Goal:** the six Phase 2 views as components that take only their params.
- **Files:** `web/src/views/` (new: one file per view, moved from `web/src/panels/` for the first four; `SpendingView.tsx` and `AffordabilityView.tsx` new; `registry.ts` maps view names to components and titles), `web/src/views/useViewData.ts` (new: TanStack Query on `/api/views/{view}`, seeded from the event's `summary`).
- **Constraints:** each view states its query in plain words and when it was read. Large, glanceable figures first, detail below: these are read from across a desk while listening, not scanned like a table.
- **Verify:** `cd web && npx vitest run src/views`.

### 2.3 Canvas shell (L)

- **Goal:** the full-screen desktop canvas.
- **Files:** `web/src/canvas/Canvas.tsx` (new: focus view centre, strip of earlier views, captions), `web/src/canvas/TalkButton.tsx` (new: tap or hold Space; shows each state, with the step label while working), `web/src/canvas/Captions.tsx` (new: what the user said, from `heard`, and what Prime said, kept short), `web/src/canvas/CommandMenu.tsx` (new: ⌘K to type a message, open a page, switch mute), `web/src/canvas/canvasReducer.ts` (new, from `panels/stageReducer.ts`: focus, strip, pinned, history), `web/src/App.tsx` (the canvas is `/` on desktop when `canvas_enabled`), `web/src/styles.css` (canvas section; motion through `motion.tsx`, respecting reduced motion).
- **Constraints:** no tab bar on the canvas. Typing is always one keystroke away. Captions are always on (they double as accessibility). Pinned views are never replaced by Prime.
- **Verify:** `cd web && npx vitest run src/canvas`.

### 2.4 Wire it together (M)

- **Goal:** a spoken turn drives the canvas end to end.
- **Files:** `web/src/canvas/Canvas.tsx` (uses `useTalk` and the stream's view events), `src/nexus/settings.py` and `/api/config` (`CANVAS_ENABLED`, `canvas_enabled`).
- **Verify:** owner run: "how's this month?" speaks a sentence and shows the month outlook; "can I afford a 2,000 trip in March?" shows affordability.

### 2.5 Remove the panel stage (S)

- **Goal:** one way, not two.
- **Files:** remove `web/src/components/PanelStage.tsx`, `PanelCard.tsx`, `panels/useDocked.ts`, the docked-column code in `ChatDrawer.tsx` and `PANELS_ENABLED`; update `.env.example`, `CONTEXT.md` (Domains and panels becomes Views and the canvas).
- **Verify:** `uv run pytest`, `cd web && npx vitest run && npm run typecheck`.

### 2.6 Playwright journeys (M)

- **Files:** `web/e2e/canvas.spec.ts` (new, replaces `panels.spec.ts`): a fake microphone and a stubbed `/api/speech`; talk, see the caption, see the view, interrupt while speaking, mute, ⌘K typed turn, pin then ask again.
- **Verify:** `cd web && npx playwright test e2e/canvas.spec.ts`.

### Phase 2 exit

All tests green; the Phase 0 numbers still hold after the code change; the owner has used it for a week. Proposal for felt speed, measured in the browser: transcript caption within **1.5 s** of the tap that ends speech, first view within **4 s**, first spoken word within **2 s** of the reply arriving.

---

## Phase 3: conversation on the canvas (owner, then demo)

- **3.1 Follow-ups update in place (M).** "And April?" updates the same view key; open views (ids, params, pinned) go back with each turn as data for Prime. Files: `chat_stream.py`, `service.py`, `graph.py` (open views in the turn's context), `canvasReducer.ts`, eval cases for carry-over.
- **3.2 Views kept per user (M).** A per-user table for open and pinned views, row-level security, in **Delete my data** (`application/user_data.py`), so a reload restores the canvas. Files: a migration, `infra/db/tables.py`, a repository, `views_api.py`.
- **3.3 Confirm cards (L).** A write that pauses at `confirm` sends a `confirm` event; the canvas shows the card; "yes" or Confirm resumes the run, "no" or Cancel drops it. Files: `agent/confirmation.py`, `chat_stream.py`, `web/src/canvas/ConfirmCard.tsx` (new), eval cases where a spoken "yes" confirms and a spoken "no" doesn't.
- **3.4 Bills and cash flow views (M).** As 2.2.
- **3.5 Demo on the canvas (S).** The demo account opens on the canvas with the lower speech cap; a first-run hint says "Tap and ask: how's my month?".

## Phase 4: faster and ahead of you (members)

- **4.1 Reply streamed token by token.** The agent loop streams the final reply (`reply.delta` events), and the speech queue starts on the first full sentence instead of the whole reply.
- **4.2 Opening briefing.** On open, deterministic triggers (a bill due, a flight tomorrow, a budget nearly spent) arrange the canvas; Prime speaks the briefing only when the user taps.
- **4.3 More views** as the owner designs them, each with a spec, component, endpoint case and eval cases.

## Open questions

- The speech model and voice (1.5).
- Whether Telegram voice notes should also get a spoken reply (an audio message back). Out of scope here.
- Phones: the canvas as one sheet over the talk button, or the Telegram Mini App with speech.
