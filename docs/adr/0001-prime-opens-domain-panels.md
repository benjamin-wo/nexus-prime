# 0001. Prime opens domain panels from the tools it calls

- **Status:** Proposed
- **Date:** 2026-11-15
- **Research:** [`reports/Agent driven UI for Nexus domains.md`](../../reports/Agent%20driven%20UI%20for%20Nexus%20domains.md)
- **Build plan:** [`docs/plans/domain-panels.md`](../plans/domain-panels.md)

## Context

The owner wants agent-driven app use. As the user talks to Nexus, the **domain** they are talking about appears as a **panel** beside the chat, showing the right information at the right time. **Accuracy** is the success criterion, not branding. A wrong panel costs more than no panel: in adaptive interfaces, accuracy affected performance more than predictability did (Gajos et al., CHI 2008).

Domains are Finance (today's Accounting and Investment departments), Travel, and later Health (wellness only) and Home & Family. Several can show at once. The desktop web app comes first, a mobile app later.

Today the chat is a drawer (`ChatDrawer.tsx`), each department is a set of tabs, and the stream (`channels/web/chat_stream.py`) sends `step`, `replies` and `error`. The agent is one LangGraph loop with `CORE_TOOLS` plus on-demand skills. The eval harness already asserts tools a turn must call (`calls`, `used`), must not call (`forbid`) and may call at most N times (`at_most`), with `--repeat`.

The research found that every production system (MCP Apps, OpenAI Apps SDK, Vercel AI SDK, LangGraph, A2UI, App Intents) binds the model's tool choice to pre-built UI in code, and that fully generated UI is slow and rated below expert-designed UI. So this is a routing problem, not a rendering one: surfacing accuracy equals tool-selection accuracy, which Nexus already measures.

## Decision

1. **Panels open from the domain tools Prime actually calls.** A typed **panel registry** (Python, the source of truth) maps each tool to the panel kind it surfaces, or marks it non-surfacing. `month_outlook(month=2026-08)` opens `finance.month_outlook` for August; a currency conversion inside a trip answer is non-surfacing. Write tools surface nothing unless the registry says so. A test fails for any tool left unclassified. A turn's panels are the union of the domains its tools touched, so "can I afford the Japan trip?" opens `travel.trip_budget` and `finance.month_outlook` with no separate classifier.

2. **`show_panel` is a fallback, not the mechanism.** A core tool `show_panel(kind, params)` covers turns that answer without a tool call (the next payday, answered from the context snapshot) and requests like "open my budget". It sits in `CORE_TOOLS` with worked examples, and the server ignores it when a domain tool already surfaced that panel in the turn.

3. **Panels are hand-built React components, never model-generated UI.** They are the same components the Money, Invest and Travel tabs use, opened with params, so what Prime shows teaches users where things live. **The panel is the system of record.** Its figures come from the same service code as the tool (the web endpoint and the tool both call one use case), and Nexus quotes only those figures. Each panel states its query in plain words and when it was read ("Dining, 1-31 Oct, 42 items, as of 14:02"). Panels are read-only in v1; anything that changes data stays in chat or the tabs, behind the confirm step.

4. **Stream protocol.** Two new SSE events beside `step`, `replies` and `error`:
   - `panel.upsert`: `panel_id` (a stable key, `kind` plus entity), `kind`, `version`, `params`, `as_of`, an optional `summary` of the headline figures, and `message_id` (the turn's `ref`).
   - `panel.close`: `panel_id`.

   The agent loop emits `panel.upsert` at the tool step, before the model writes its reply. v1 emits it when the tool returns successfully: params need the tool's resolved entities ("Japan" becomes a trip id), and a failed tool must not open a panel. The same `panel_id` updates in place; a key is never closed and reopened within a turn. `summary` is built by code from the tool result, never by the model. The client fetches the panel's data by params with TanStack Query, seeds the cache from `summary`, and shows "updated since" if the fetched figures differ. The server also records each opened panel's kind and params (never figures), so a reload, a broken stream or the plain `POST /api/chat` fallback loses nothing. The open panels (ids, kinds, params, selection) go back with each chat request, validated against the registry and shown to the model as data, so "drop that one" resolves.

   AG-UI stays a later option: it is the most complete open protocol, but adopting it replaces the working wire format and its versions have churned. The two events copy its stable-id upsert, so a later move is a translation layer.

5. **One agent with skills stays.** Domain sub-agents come only if a distractor-domain eval run (Health and stub domains bound, as in LangChain's benchmark) shows tool-selection accuracy breaking. If it does, use handoffs, where the domain agent answers the user directly, not a supervisor.

6. **Proactive panels are out of v1.** Later, only from deterministic triggers (a bill due, a flight tomorrow, a budget threshold crossed), as an ignorable chip that reuses **Needs you** and the notification levels, never a takeover.

7. **Telegram gets no panels.** The text reply must stand on its own, and v1 adds nothing to Telegram replies. Later, an optional "Open in Nexus" link button may deep-link to the matching tab view with the same params.

8. **Layout.** Desktop first: a fixed chat column beside a **panel stage**. A panel has a lifecycle (suggested, open, pinned, dismissed, history) and a caption saying why it opened, linked to the message ("Opened because you asked about October dining"). Prime replaces an unpinned panel only in the same slot (same key), never one the user pinned or touched, and auto-expands only for an explicit request; for an ambiguous one it opens the likely panel and offers the other as a chip. Working budget: one expanded panel plus up to three compact ones, a proposal to test, not a finding. Mobile later is one nonmodal bottom sheet over the chat, with several panels as swipeable cards. When mobile starts, registry types, event parsing, the API client and query hooks move to a shared DOM-free TypeScript package.

9. **Accuracy is measured before any UI is built.** Eval cases carry expected panels, derived from their expected tools through the registry unless stated. The harness reports panel precision, recall and F1 (micro and macro), exact-set match, over- and under-surfacing and correct-silence rate, each as mean and spread over `--repeat`. New case types: correct silence, follow-up carry-over ("and last month?" updates the same key), implicit multi-domain ("can I afford the Japan trip?"), topic switch, no-tool answers and a distractor-domain stress run. Online signals: dismissals and time-to-dismiss (false positives), manual opens (false negatives) and re-asks. Gates are in the build plan.

## Consequences

- **Good:** no extra model decision, latency or failure mode; the panel shows what Prime grounded its answer on; the tabs stay the stable map; labels are nearly free, so a baseline exists before UI code.
- **Panel accuracy is tool-selection accuracy.** If the cheap production model picks the wrong tool, the wrong panel opens. Phase 0 of the plan measures this and fixes routing (skill text, tool descriptions) before the stage is built.
- Tools must report what they resolved (a `panels` field on `ToolResult`), and each new tool needs a registry classification.
- Page bodies must become components that take filters as props, not only from the URL. `month_outlook` has no web endpoint, so `finance.month_outlook` needs one that calls the same use case.
- Panel endpoints keep the tab endpoints' authorisation: a trip **member** never gets a trip's money in a panel.
- A small per-user table holds panel state. It joins **Delete my data** (`application/user_data.py`) and has row-level security. Params can hold a merchant search or an amount, so they are personal data.
- Telemetry carries kinds and timings, never params or figures. Real conversations never enter the eval set (PLAN rule 7); sampled cases are rewritten as made-up ones.
- On desktop the chat becomes a column, not a drawer. Phones keep the drawer until the mobile sheet exists.

## Alternatives considered

- **`show_panel` as the main mechanism.** One more decision for a cheap model, on a tool that does nothing functional. Kept as the fallback only.
- **A pre-agent router choosing panels.** More accurate and faster than LLM prompting on labelled data, but a wrong pre-opened panel is visible flicker. Possible later for skill loading, gated at high confidence.
- **Supervisor with domain sub-agents.** Adds a routing hop, "translation" errors and about 15x the tokens in Anthropic's case. Deferred to evidence (decision 5).
- **Model-generated UI, or MCP Apps iframes.** Generated UI is slow and less trusted for money. Iframes serve third-party servers inside someone else's host; Nexus owns all its UI. Relevant only if Nexus domains should later run inside Claude or ChatGPT.
- **Tool results as panel props.** No second fetch, but large payloads, stale on reload, no pagination or refresh, and it duplicates the REST shaping. Replaced by the params-plus-summary hybrid.
- **Panels on Telegram.** No room for a stage in a phone chat; the text reply is what Telegram is for.

## Regulatory notes (need professional review)

Flagged, not settled. A Singapore lawyer should review each before the affected panel ships.

- **Finance (MAS advice line).** Showing a user's own data, factual prices with source and delay, and calculators on their inputs is low-risk. Personalised "buy X" or "switch to insurer Y" content may need a licence under the Financial Advisers Act, and a disclaimer does not change that. Prime opening a trade-plan panel (verdict, entry zone, targets) unprompted raises its prominence, so trade-plan panels are not in v1.
- **Health (HSA, wellness only).** Panels show trends and goals, never interpretations ("your HRV suggests..."); one medical-function feature can make the product a medical device. Consent is per domain, so a multi-domain panel never pulls health data into a Finance view unopted.
- **PDPA.** Salary, loan, credit and insurance data are "presumed significant harm" data (72-hour breach notice). The panel state table and telemetry fall under the breach runbook.

## Open questions

Listed at the end of [`docs/plans/domain-panels.md`](../plans/domain-panels.md): chat as a persistent desktop column, whether write tools may surface a panel, and who gets panels first.
