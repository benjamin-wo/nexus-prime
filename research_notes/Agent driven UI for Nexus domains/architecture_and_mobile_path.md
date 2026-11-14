# Architecture options for conversation-driven domain UIs in Nexus, and the path from desktop web to mobile

Research date: 2026-11-14. Method note: `blog.langchain.com` and `www.langchain.com` could not be fetched from this session (blocked by the network allowlist). The LangChain benchmark findings below come from search-result excerpts of the primary post, not a full read. Several other findings come from search-result excerpts of official docs rather than fully fetched pages; each one is marked where it matters. Items not backed by a source are kept under Inferences or Gaps.

---

## 1. Agent architecture for large domains: one agent with skills/tools vs. supervisor + domain sub-agents vs. handoffs/swarm

### Takeaway
The best public benchmark (LangChain, June 2025) found that a single agent degrades and uses more tokens as unrelated domains are added to its context. Supervisor and swarm architectures held token use flat. Swarm (handoffs) slightly beat supervisor, mainly because a supervisor "translates" sub-agent output. For Nexus, the existing approach of one agent plus on-demand skills is a context-isolation technique that targets the same failure mode. It is the cheapest path. Move to a supervisor or handoffs only when evals show cross-domain confusion. Moving does not require a rewrite in LangGraph.

### Cited Findings
- **LangChain benchmark (June 2025):** used a modified tau-bench, the first 100 examples of the retail-domain test split, with an increasing number of "distractor" domains added. It compared single agent, supervisor and swarm. — [LangChain blog: Benchmarking Multi-Agent Architectures](https://www.langchain.com/blog/benchmarking-multi-agent-architectures) (seen via search excerpt only; the page was not fetchable)
- In the same post, the single agent "uses consistently more tokens as the number of distractor domains grows, while supervisor and swarm remain flat". The single-agent baseline degraded significantly as context was added. — [LangChain blog](https://www.langchain.com/blog/benchmarking-multi-agent-architectures)
- Swarm "slightly outperforms supervisor architecture across the board". The gap is attributed to supervisor "translation" errors: sub-agents cannot answer the user directly, which also raises supervisor token use. — [LangChain blog](https://www.langchain.com/blog/benchmarking-multi-agent-architectures)
- Improvements to LangChain's supervisor implementation produced "a nearly 50% increase in performance on this benchmark". From LangChain's background, these were removing handoff messages from sub-agent context and adding a `forward_message` tool so the supervisor can pass a sub-agent's answer through verbatim. I could not verify these details against the full text, so treat them as unverified. — [LangChain blog](https://www.langchain.com/blog/benchmarking-multi-agent-architectures)
- **Conflict:** a secondary summary says the supervisor outperforms the others with many distractor environments, which contradicts the primary post. Prefer the primary. — [blockchain.news summary](https://blockchain.news/news/evaluating-multi-agent-architectures-performance-benchmark)
- A secondary write-up from January 2026 says LangChain now recommends starting with a single agent and good prompt engineering before going multi-agent. — [AIMultiple: agentic frameworks](https://aimultiple.com/agentic-frameworks) (secondary)
- **Anthropic's multi-agent research system (June 2025):**
  - Agents use about 4x the tokens of chat. The multi-agent system used about 15x the tokens of chat.
  - An Opus 4 lead with Sonnet 4 subagents beat single-agent Opus 4 by 90.2% on internal research evals.
  - Token usage alone explained about 80% of performance variance on BrowseComp.
  - Anthropic said multi-agent systems need tasks "where the value of the task is high enough to pay for the increased performance".
  - [The Decoder](https://the-decoder.com/anthropic-shares-blueprint-for-claude-research-agent-using-multiple-ai-agents-in-parallel/), [ZenML LLMOps DB](https://www.zenml.io/llmops-database/building-production-multi-agent-research-systems-with-claude) (secondary coverage of Anthropic's "How we built our multi-agent research system")
- **OpenAI Agents SDK, two official patterns:**
  - **Handoffs:** a specialist "should own the next response". The handoff is exposed to the model as a tool named `transfer_to_<agent_name>`. — [OpenAI: Orchestration and handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration); [Agents SDK JS: Handoffs](https://openai.github.io/openai-agents-js/guides/handoffs)
  - **Agents as tools (manager pattern):** the parent keeps the conversation and calls specialists for bounded subtasks via `agent.asTool()`. — [Agents SDK JS: multi-agent](https://openai.github.io/openai-agents-js/guides/multi-agent)
  - Secondary sources say handoffs pass the full history by default, with input filters available. In the agents-as-tools pattern, sub-agents do not inherit the parent's conversation automatically. — [agentpatterns.ai](https://agentpatterns.ai/patterns/agent-design/agent-as-tool-vs-handoff/) (secondary)

### Inferences
- **Option A: one agent, domain skills and tools loaded on demand (Nexus today).** The LangChain failure mode is distractor context: tool definitions and instructions from irrelevant domains. On-demand skill loading addresses exactly that.
  - Pros:
    - Lowest latency: one LLM loop, no routing hop.
    - Lowest cost.
    - One checkpointer thread.
    - One place to emit UI events.
    - Easiest to debug.
  - Cons: the skill-selection step becomes the router. Its accuracy has to be evaluated, especially on a cheap fast model and in multi-domain turns ("can I afford the Lisbon trip?" touches both Finance and Travel).
- **Option B: supervisor (manager / agents-as-tools) with domain sub-agents.**
  - Pros:
    - Clean ownership per domain: separate prompts, tools and evals.
    - Sub-agents can run in parallel for multi-domain turns, which fits "several panels open together".
  - Cons:
    - An extra LLM hop per turn, so more latency and tokens.
    - The translation-error risk LangChain measured.
  - Mitigations: forward sub-agent answers verbatim, and have sub-agents emit UI events directly instead of through the supervisor.
- **Option C: swarm / handoffs.** The active agent changes, and the domain agent talks to the user directly.
  - Pros: slightly better quality than supervisor in the benchmark, and no translation step.
  - Cons:
    - Harder to handle "open Finance and Travel panels together", since only one agent is active.
    - Shared state (open panels, user profile) must be explicit.
    - Routing back to a generalist must be designed.
- **With a cheap fast model,** each extra routing hop is a place where the weaker model can misroute. Every hop adds time-to-first-token on top of the existing step-then-reply SSE flow.
- **Recommendation for a small team:**
  1. Keep Option A.
  2. Make skills strictly domain-scoped: tools, instructions, panel catalogue.
  3. Build a small routing and multi-domain eval set.
  4. Move to Option B (LangGraph supervisor or subgraphs) only for domains that grow large tool surfaces, such as Health.
- All three options are expressible in LangGraph with the same Postgres checkpointer, so no rewrite is needed. Adopting the OpenAI Agents SDK instead would mean replacing LangGraph orchestration, which is effectively a rewrite with no clear payoff here.

### Gaps
- Exact benchmark scores per architecture and model, and the full list of supervisor changes. The LangChain blog could not be fetched; `www.langchain.com` would need to be allowed in the session's network settings.
- No credible public benchmark found comparing these architectures specifically with small or cheap models (for example Haiku- or mini-class models) on multi-domain personal-assistant tasks.
- No published latency numbers (p50 or p95 per extra routing hop) found for the LangGraph supervisor vs. a single agent.

---

## 2. UI event protocol: streaming "show/update this panel with these params", and feeding panel actions back to the agent

### Takeaway
Four open options exist:
- **AG-UI:** a general event protocol with tool-call, state-snapshot/delta and CUSTOM events.
- **LangGraph UI messages:** `push_ui_message`, with an id-based update.
- **Vercel AI SDK data parts:** id-reconciled, typed parts.
- **MCP Apps:** sandboxed `ui://` HTML resources rendered in iframes, stable since January 2026.

Nexus has a Python/FastAPI backend, a custom SSE stream and a Telegram Mini App. The lowest-risk choice is a small custom SSE event, `panel.open`/`panel.update`/`panel.close`, whose shape deliberately mirrors AG-UI or AI SDK semantics (stable id, upsert, JSON-patchable state). It leaves room to adopt AG-UI later.

### Cited Findings
- **AG-UI** defines typed events:
  - Tool calls stream as `TOOL_CALL_START` → `TOOL_CALL_ARGS` (chunked args) → `TOOL_CALL_END`, with a separate `TOOL_CALL_RESULT`.
  - `STATE_SNAPSHOT` and `STATE_DELTA` carry state; `STATE_DELTA` is a JSON Patch (RFC 6902).
  - `CUSTOM` (with a `name`) and `RAW` cover app-specific events.
  - [AG-UI Python SDK events](https://docs.ag-ui.com/sdk/python/core/events.md); [AG-UI JS SDK events](https://docs.ag-ui.com/sdk/js/core/events.md); [AG-UI architecture](https://docs.ag-ui.com/concepts/architecture)
  - SDKs differ: Python types `delta` as a list, while one TS source shows a record. Field shapes vary by SDK version. — [AG-UI Python events](https://docs.ag-ui.com/sdk/python/core/events.md) (from search excerpt)
- AG-UI is driven by CopilotKit, and its docs are mirrored on `docs.copilotkit.ai`. A November 2026 article refers to "AG-UI 1.0" alongside "AI SDK 7". — [CopilotKit AG-UI docs](https://docs.copilotkit.ai/ag-ui/sdk/js/core/events); [DevelopersDigest: Streaming and Generative UI for Agent Apps](https://www.developersdigest.tech/blog/streaming-and-generative-ui-for-agents) (title only; 1.0 status not independently verified)
- TanStack AI documents an AG-UI-based protocol in its chunk definitions. TanStack is already in the Nexus stack via TanStack Query. — [TanStack AI chunk definitions](https://tanstack.com/ai/latest/docs/protocol/chunk-definitions)
- **LangGraph generative UI:**
  - The graph calls `push_ui_message` (Python) or `ui.push()` (TS), optionally linked to an AI message.
  - Pushing again with the same id updates the component; `delete_ui_message` removes it.
  - On the client, `useStream()` plus `LoadExternalComponent`. By default this fetches component code from LangGraph Platform, but you can pass a mapping of locally bundled components instead.
  - [LangChain docs: Generative UI (React)](https://docs.langchain.com/langsmith/generative-ui-react); [langgraph.graph.ui reference](https://reference.langchain.com/python/langgraph/graph/ui)
- Async `get_stream_writer()` custom streaming needs Python ≥ 3.11 for contextvar propagation. Nexus is on 3.12, so this is fine. — [LangChain docs: Generative UI](https://docs.langchain.com/langsmith/generative-ui-react) (search excerpt)
- **Vercel AI SDK (v5+):** the server writes typed `data-*` parts with `writer.write()` inside `createUIMessageStream`.
  - Writing a part with an existing `id` updates it in `message.parts` rather than appending, which enables loading-then-final updates.
  - Transient parts arrive only via `useChat`'s `onData` and are not persisted.
  - v5 removed the v4 `data` role and changed the API.
  - [AI SDK: Streaming Custom Data](https://ai-sdk.dev/docs/ai-sdk-ui/streaming-data); [AI SDK 5 migration guide](https://ai-sdk.dev/v5/docs/migration-guides/migration-guide-5-0); [AI SDK stream protocol (v7)](https://ai-sdk.dev/v7/docs/ai-sdk-ui/stream-protocol)
- **MCP Apps** (extension `io.modelcontextprotocol/ui`, announced 2025-11-21):
  - Tools reference `ui://` resources (HTML) via metadata.
  - The host renders them in sandboxed iframes, which talk to the host over MCP JSON-RPC.
  - Both sides opt in, and servers must still work as text-only.
  - Spec version 2026-01-26 is reported as Stable, with a draft in progress.
  - A secondary source says the flat `_meta["ui/resourceUri"]` key is deprecated.
  - [MCP blog: MCP Apps](https://blog.modelcontextprotocol.io/posts/2025-11-21-mcp-apps/); [modelcontextprotocol/ext-apps](https://github.com/modelcontextprotocol/ext-apps); [mcp.directory: MCP Apps spec 2026](https://mcp.directory/blog/mcp-apps-spec-2026-when-should-your-server-render-ui) (secondary)
- One secondary source claims MCP Apps was folded into a 2026-07-28 extensions framework. I could not confirm this from a primary source. — [ecorpit guide](https://ecorpit.com/mcp-apps-server-rendered-ui-extension-build-guide-2026/) (unverified)

### Inferences
- **Option 1: custom SSE events.** Add `ui` events next to the existing `step` and `replies` events, for example:

  ```
  {type:"panel.upsert", panel_id, kind:"finance.budget", params:{month,category}, version, message_id}
  {type:"panel.close", panel_id}
  ```

  - Pros:
    - Fits the current FastAPI SSE and React client with no new dependencies.
    - Works identically in the Telegram Mini App and a future React Native client.
    - Fully under the team's control.
  - Cons: you own the spec. Mitigate by copying proven semantics: stable ids with upsert (AI SDK and LangGraph), and JSON Patch for state deltas (AG-UI).
- **Option 2: LangGraph `push_ui_message`.**
  - Pros: native to the existing graph, and UI messages are persisted in graph state with the checkpointer, so reloading a thread can restore panels.
  - Cons:
    - The React helpers (`useStream`, `LoadExternalComponent`) assume the LangGraph Platform/Server API shape. Nexus streams through its own FastAPI endpoints, so you would use only the Python side and translate it into your own SSE.
    - Still a reasonable way to store panel state in the checkpoint.
- **Option 3: AG-UI.**
  - Pros:
    - Most complete open protocol: tool lifecycle, shared state, custom events.
    - Python SDK exists.
    - Could unlock CopilotKit and TanStack AI clients.
  - Cons:
    - Replaces the current `step`/`replies` wire format, a moderate refactor of the stream layer and client hooks.
    - Its version history shows churn.
  - Worth it if Nexus wants off-the-shelf clients or shared-state sync.
- **Option 4: AI SDK data parts.** Excellent semantics, but the server helpers are TypeScript. A Python backend would have to hand-emit the UI message stream protocol, which is possible but a poor fit.
- **Option 5: MCP Apps.**
  - Designed for third-party hosts (Claude, ChatGPT, etc.) rendering a server's UI in iframes. Wrong fit for first-party panels inside Nexus's own React app: iframe isolation, styling and performance cost, and no shared TanStack cache.
  - Relevant only if Nexus wants its domains usable inside other assistants.
- **Feeding panel state and actions back to the agent.** Two complementary channels:
  1. **Context:** send the open-panel list with ids, kinds, params and the user's current selection as structured metadata on each chat request (AG-UI calls this state). The agent can then resolve "that one" or "drop the hotel".
  2. **Actions:** a panel button posts a typed action (`{panel_id, action:"approve_budget_change", args}`) either:
     - to a normal REST endpoint, with deterministic actions bypassing the LLM, or
     - as a synthetic user or tool message into the thread, for actions needing reasoning. This is close to AG-UI frontend tools, where the client returns a tool result.
  - Keep confirmations for money-moving actions as LangGraph interrupts, so the checkpointer holds the pending state.

### Gaps
- No published production case study comparing AG-UI and custom SSE on effort or maintenance.
- Exact AG-UI version and stability status (1.0 or not) in late 2026 not verified from ag-ui.com release notes.
- Whether LangGraph's `useStream` can target a non-LangGraph-Server backend without an adapter not verified.

---

## 3. Panel data: should panels get data from the agent (tool results) or fetch it from the API by params (server-driven UI)?

### Takeaway
Prior art supports both. AI SDK data parts and LangGraph UI messages ship props from the agent, while SDUI systems ship a typed component reference that the client renders against data. For Nexus, the strongest pattern is a hybrid. The agent emits panel kind plus params plus a data version or snapshot id. The panel fetches through the existing TanStack Query API, keyed by those params. A small inline payload of what the agent "saw" lets the UI flag drift.

### Cited Findings
- The AI SDK pattern streams data from the server into the message: a loading state first, then the final data under the same `id`. This puts data in the agent message. — [AI SDK: Streaming Custom Data](https://ai-sdk.dev/docs/ai-sdk-ui/streaming-data)
- LangGraph UI messages carry props from the graph, and the component reads extra context via `meta` / `useStreamContext`. — [LangChain docs: Generative UI (React)](https://docs.langchain.com/langsmith/generative-ui-react)
- DoorDash's generic SDUI components use a protobuf `Component` message whose id maps to an entry in the client's component library. The server picks the component; the client owns rendering. — [DoorDash Engineering: Improving Development Velocity with Generic, Server-Driven UI Components (2021)](https://careers.doordash.com/?p=5364)

### Inferences
- **Agent-pushed data (tool results as props).**
  - Pros:
    - The panel shows exactly what the model reasoned over, so the text and panel are consistent by construction.
    - No extra round trip.
  - Cons:
    - Large payloads bloat the SSE stream and the checkpointed state.
    - Stale on reload.
    - Panels can't paginate, filter or refresh on their own.
    - Duplicates the REST API's shaping logic.
- **Params-only, panel fetches (SDUI style).**
  - Pros:
    - Reuses existing FastAPI endpoints and TanStack Query caching.
    - Panels stay live and interactive.
    - Panels can be opened from the UI without the agent.
    - The same panel works on web, Telegram and a native client.
  - Cons: the agent's sentence ("you spent €412 on dining") can disagree with the panel if data changed between the tool call and the fetch, or if tool and API compute differently.
- **Hybrid (recommended):**
  - Domain tools and REST endpoints call the same service-layer functions, so numbers are computed identically.
  - The `panel.upsert` event carries `params` and an `as_of` timestamp or ledger version. It may also carry a small `summary` (the figures the agent quoted).
  - The panel fetches by params. If the server's version is newer than `as_of`, it shows an "updated since" hint.
  - The panel can seed TanStack Query's cache from the inline summary (`initialData`) for instant render, then revalidate.
- For Finance especially, compute numbers deterministically in tools and the service layer, never in the LLM. The agent should quote tool output, and the panel shows the same service output.

### Gaps
- No primary source found that measures agent-vs-panel inconsistency rates or documents this hybrid in a production agent product. The recommendation is an inference from SDUI and AI SDK patterns.

---

## 4. Server-driven UI at scale: lessons from Airbnb, Lyft, Shopify, DoorDash, and how they apply to agent-chosen panels

### Takeaway
Airbnb's Ghost Platform has three building blocks:
- **Sections:** independent, reusable typed UI units.
- **Screens:** layout and placements.
- **Actions:** interaction handling.

DoorDash maps server ids to a client component library. The transferable lessons for Nexus are a typed, finite panel registry: the agent chooses from a catalogue, it never generates UI. Panel schemas should be versioned and validated, layout should be decoupled from content, and actions should be typed. At Nexus's scale, a full SDUI layout engine would be over-engineering.

### Cited Findings
- **Airbnb Ghost Platform (GP):**
  - Sections are "the most primitive building block", independent of each other, and reusable across the app.
  - Screens describe layout and where sections appear ("placements"), and a response can include any number of screens.
  - Layouts can vary by form factor.
  - Actions handle user interaction.
  - [Airbnb Engineering: A Deep Dive into Airbnb's Server-Driven UI System (2021)](https://medium.com/airbnb-engineering/a-deep-dive-into-airbnbs-server-driven-ui-system-842244c5f5); [InfoQ coverage (July 2021)](https://www.infoq.com/news/2021/07/airbnb-server-driven-ui)
- **DoorDash:** the goals were faster releases, by leaning on backend rather than mobile releases, and fixing problems from an earlier SDUI attempt. A protobuf `Component` id maps to a client library entry. — [DoorDash Engineering (2021)](https://careers.doordash.com/?p=5364)
- **Lyft and Uber** are cited secondarily as using protobuf-typed UI component schemas. No primary versioning details were found. — [Medium: Ship your Compose UI updates in seconds](https://medium.com/@developerchunk/ship-your-compose-ui-updates-in-seconds-78e5207b9cb6) (secondary)
- A preprint on config-driven UI frameworks lists "contract fragility" and the need to "ensure N−k versioning and multi-version legacy support" as open problems. — [engrXiv preprint](https://engrxiv.org/preprint/download/7565/12349/10642)
- Thoughtworks Technology Radar has a technique entry on server-driven UI. Its exact ring and advice were not read. — [Thoughtworks Radar: Server-driven UI](https://thoughtworks.com/radar/techniques/server-driven-ui)

### Inferences
- **Mapping to Nexus.** An agent-chosen panel is the equivalent of a GP "section":
  - Panel `kind` (`finance.budget_overview`, `finance.transactions`, `travel.itinerary`) plus a params schema (Pydantic on the server, generated TS types on the client).
  - The client registry maps `kind` → React component. Unknown kinds render a fallback, as LangGraph's docs show with `fallback`.
  - The "screen" (layout, meaning which panels are open, their order and their docking) should stay client-owned and simple. A side dock with stacked or tabbed panels is enough.
- **Registry as the single source of truth.** Generate three things from one registry: the agent's tool or skill description ("open_panel(kind, params)" with an enum of kinds and JSON schemas), the backend validator, and the client's TS types (for example via OpenAPI or JSON Schema → TS). This prevents the model inventing panels or params.
- **Versioning.**
  - On web, the client and server deploy together on one droplet, so versioning is nearly free.
  - Once native app binaries exist, old clients persist. Then you need:
    - a `kind@version` or capability handshake (the client sends its supported panel kinds and versions on each request);
    - additive-only param changes;
    - server-side fallback to text or a generic table for unsupported kinds.
  - This is the core SDUI lesson that becomes relevant at the mobile step.
- **Don't build a full SDUI DSL** (server-specified trees of primitives) for a small team. Airbnb and DoorDash built theirs to dodge app-store release cycles across large teams. Nexus needs agent-selectable, coarse-grained panels, and those panels should be hand-written domain components.

### Gaps
- No primary Lyft or Shopify engineering posts on SDUI versioning were reached within the time budget. Shopify's mobile SDUI practices are not covered.
- No public case study found of an agent product using an SDUI registry for agent-chosen panels. The mapping above is inference.

---

## 5. Desktop web → mobile: PWA vs. React Native/Expo vs. Capacitor vs. Telegram Mini App

### Takeaway
- **Capacitor:** the cheapest way into the stores. It reuses the React and Vite app almost unchanged, but carries App Store Guideline 4.2 ("repackaged website") rejection risk unless it adds native depth (push, offline, biometrics, share).
- **Expo / React Native:** the "proper mobile app" path. It shares TS types, the API client, TanStack Query and business logic, but UI components are rewritten. Expo DOM components can reuse specific web components, such as charts, inside the native app.
- **PWA:** free, but on iOS push only works after a Home Screen install. EU status has been politically unstable.
- **Store policies for an AI and finance assistant:** Apple's November 2025 Guideline 5.1.2(i) requires clear disclosure and explicit permission before sending personal data to third-party AI. This applies directly to Nexus sending finance data to an LLM provider.

### Cited Findings
- **Expo DOM components:**
  - The `"use dom"` directive runs web React code in a webview on native, and as-is on web.
  - SDK 56+ uses `@expo/dom-webview` by default; earlier SDKs use `react-native-webview`.
  - DOM components have their own React tree: they share no context with the native app and no JS globals with each other.
  - Expo advises native navigation (Expo Router) and keeping navigation out of DOM components.
  - Guidance favours them for specialised content such as charts rather than whole screens, because of webview overhead.
  - [Expo docs: DOM components](https://docs.expo.dev/guides/dom-components/); [Expo blog: The magic of Expo DOM components (Nov 2024)](https://expo.dev/blog/the-magic-of-expo-dom-components)
- One team used DOM components to reuse `recharts` charts instead of rebuilding them natively. — [Expo blog: DOM component use case](https://expo.dev/blog/dom-component-use-case)
- **Capacitor and Guideline 4.2:**
  - A hybrid Capacitor app was rejected repeatedly under 4.2 (Minimum Functionality). The reviewer said it was not sufficiently different from web browsing, and that Core Location or sharing alone was not enough. — [Apple Developer Forums thread](https://developer.apple.com/forums/thread/812889)
  - Vendor guidance says the fix is genuine native depth: offline support, device integration, native navigation, push, auth. A wrapped app that shows a browser error page offline is a common tell. — [Capgo: How to pass App Store review 2026](https://capgo.app/blog/how-to-pass-app-store-review-2026/); [MobiLoud: webview wrapper guidelines](https://www.mobiloud.com/blog/app-store-review-guidelines-webview-wrapper) (vendor sources)
- **PWA on iOS:**
  - Web push for Home Screen web apps has existed since iOS 16.4, and only after the user adds the app to the Home Screen.
  - Safari 18.4 added Declarative Web Push.
  - iOS 26 opens Home Screen sites as web apps by default (reported).
  - [MagicBell: PWA iOS limitations](https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide) (secondary)
- **EU:** Apple said it would disable Home Screen web apps in the EU in iOS 17.4 (February 2024) under the DMA, then reversed and kept them. Some 2026 SEO pages still describe the removal as current, so this conflicts. — [The Register (Feb 2024)](https://www.theregister.com/2024/02/16/apple_web_apps/); reversal reported by [TechCrunch](https://techcrunch.com/?p=2673309). Current status not verified from Apple or WebKit primary docs.
- **Guideline 5.1.2(i), updated 2025-11-13:** you must "clearly disclose where personal data will be shared with third parties, including with third-party AI, and obtain explicit permission before doing so". — [Apple Developer News: Updated App Review Guidelines](https://developer.apple.com/news?id=ey6d8onl); [TechCrunch (2025-11-13)](https://techcrunch.com/2025/11/13/apples-new-app-review-guidelines-clamp-down-on-apps-sharing-personal-data-with-third-party-ai)
- Developer forum threads show rejections citing 5.1.1(i)/5.1.2(i) for third-party AI services. Implementation guides say a privacy-policy line alone may not suffice and an in-app consent step is expected. Sources diverge on exactly what Apple requires. — [Apple Developer Forums: App rejected due to third-party AI service](https://developer.apple.com/forums/thread/816140); [Stora: 5.1.2(i) implementation guide (May 2026)](https://stora.sh/blog/2026-05-06-apple-ai-consent-rule-5-1-2-i-implementation-guide) (secondary)

### Inferences
- **Option comparison for Nexus:**

| Option | Code reuse | Effort | Perf / feel | Push | Offline | Store risk | Rewrite? |
|---|---|---|---|---|---|---|---|
| PWA (current app + manifest + service worker) | ~100% | Very low | Web | iOS only after Home Screen install; Android fine | Service worker cache | None (no store) | No |
| Telegram Mini App (exists) | ~100% | None | Web in Telegram webview | Via the Telegram bot (no web push) | Limited | Telegram's rules, not Apple's | No |
| Capacitor wrap | ~90%+ | Low–medium | Webview; fine for dashboards and chat | Native APNs/FCM via plugin | Must add | 4.2 risk if thin; 5.1.2(i) applies | No |
| Expo / React Native | Types, API client, TanStack Query, hooks, SSE logic; UI rewritten (DOM components for charts) | High (new UI layer) | Native | Native (expo-notifications) | Good | 5.1.2(i) applies; lower 4.2 risk | UI layer only |
| Expo + react-native-web / Tamagui / Solito (one UI for web and native) | Highest long-term | Very high now | Native on mobile | Native | Good | As above | **Yes, rewrites the existing web UI** |

- **Recommended path for a small team:**
  1. **Now:** keep the desktop React app and the Telegram Mini App. Add PWA basics (manifest, installability, web push on Android and desktop) at near-zero cost.
  2. **Design for portability today:**
     - Keep the panel registry, the SSE event types, the API client (generated from FastAPI OpenAPI) and the TanStack Query hooks in a framework-agnostic TS package, with no DOM in hooks.
     - This is what a later React Native client reuses.
  3. **Mobile v1:** if speed to store matters, ship Capacitor with real native depth to clear 4.2: native push for proactive assistant messages, biometric unlock (a natural fit for finance), offline read cache, share sheet. If a polished native chat and panels experience is the goal, start Expo and reuse the shared TS package plus DOM components for complex charts.
  4. **Avoid** a react-native-web / Tamagui / Solito unification now. It forces rewriting the working web UI for speculative reuse.
- **SSE on React Native:** `fetch` streaming / EventSource support needs a polyfill or library, so plan for it in the shared client. This is from general knowledge, not sourced here.
- **5.1.2(i) consent is unavoidable for any store build.** Nexus sends personal finance and health data to an LLM provider, so it needs an explicit, in-app, provider-named consent screen before first use. Building this into the web onboarding now avoids rework.
- Health data will add more constraints (HealthKit rules, health-data guidelines). Investment features may hit finance-app rules. These were not researched here.

### Gaps
- **Finance-specific store rules not researched:**
  - Apple 3.1.x / 5.x rules for apps showing investments or trading.
  - Google Play's financial services declaration.
  - Whether "investment information" vs. "advice" triggers licensing requirements.
- Telegram Mini App platform limits and policies (payments, storage, background, notifications) as of 2026 not researched.
- No primary-source performance benchmarks (startup time, memory, scroll) for Capacitor vs. React Native in 2026 were collected.
- Current EU status of iOS Home Screen web apps not confirmed from a primary Apple or WebKit source.
- Google Play 2026 policies on AI-generated content and webview apps not researched.
