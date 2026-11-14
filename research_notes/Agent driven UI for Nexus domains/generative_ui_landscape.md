# Agent-driven / Generative UI Landscape (as of Nov 2026)

Research method note: WebSearch worked. WebFetch could reach github.com, but modelcontextprotocol.io, developers.openai.com and docs.langchain.com were blocked by this session's network allowlist. Many details below therefore come from search-result summaries of those official pages, not from full reads, and the citations point to the official URLs that the summaries cite. Anything that needs a primary-source check is flagged.

## 1. What each product/protocol offers and how it works technically

### Takeaway
The field has settled on three layers. (a) A transport/event protocol between agent and frontend: AG-UI, LangGraph streaming, AI SDK UI message parts. (b) A UI description format: a fixed component catalog plus declarative JSON (A2UI, Adaptive Cards, LangGraph named components, AI SDK per-tool components, Thesys C1), or a sandboxed HTML iframe (MCP Apps, OpenAI Apps SDK, Claude interactive apps). (c) Fully model-generated pages, used only in experiments (Gemini dynamic view). In nearly every production system the decision about *which* UI to show runs through a **tool call**: the model chooses a tool, and code or metadata binds that tool to a UI.

### Cited Findings

**MCP Apps (SEP-1865) / `ui://` resources (OpenAI + Anthropic + MCP community)**
- Proposed Nov 21, 2025 on the official MCP blog, as an optional MCP extension for serving interactive UIs from servers — [MCP blog 2025-11-21](https://blog.modelcontextprotocol.io/posts/2025-11-21-mcp-apps/); [SEP-1865](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp)
- Mechanism: servers declare UI resources under the `ui://` scheme in advance. Tools reference them through metadata (`_meta["ui/resourceUri"]`). UI templates are ordinary MCP resources with MIME type `text/html;profile=mcp-app`. The extension id is `io.modelcontextprotocol/ui` and must be negotiated through extension capabilities — [SEP-1865](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp); [Ruby SDK MCP Apps docs](https://ruby.sdk.modelcontextprotocol.io/extensions/mcp-apps/)
- The host owns the sandboxed iframe and the `ui/*` postMessage bridge. The server only ever receives ordinary `resources/read` and `tools/call` requests — [Ruby SDK MCP Apps docs](https://ruby.sdk.modelcontextprotocol.io/extensions/mcp-apps/)
- Status: reported as the first official MCP extension to reach production-ready status (Jan 2026). Some sources say it has been "stable since the 2026-01-26 spec revision", and the Ruby SDK calls it "Final" — [Alpic](https://alpic.ai/blog/mcp-apps-goes-official-claude-chatgpt-support); [Ruby SDK](https://ruby.sdk.modelcontextprotocol.io/extensions/mcp-apps/). I could not confirm the exact spec-revision wording against the primary spec page because it was blocked.
- Use cases listed at the proposal stage: dashboards, configuration wizards, document review — [The New Stack](https://thenewstack.io/anthropic-extends-mcp-with-an-app-framework/)
- Anthropic and OpenAI collaborated on the shared spec so that apps work across platforms — [WorkOS, 2026-01-27](https://workos.com/blog/2026-01-27-mcp-apps)

**Anthropic Claude interactive apps (MCP Apps in Claude)**
- Launched Jan 26, 2026. Launch partners were Amplitude, Asana, Box, Canva, Clay, Figma, Hex, monday.com and Slack, with Salesforce to follow — [The Register 2026-01-26](https://www.theregister.com/2026/01/26/claude_mcp_apps_arrives); [TechCrunch 2026-01-26](https://www.techcrunch.com/2026/01/26/anthropic-launches-interactive-claude-apps-including-slack-and-other-workplace-tools/)
- Available on web and desktop for paid plans. Not in Claude Cowork at launch — [SBBIT (JP)](https://www.sbbit.jp/article/cont1/179405); [TechCrunch](https://www.techcrunch.com/2026/01/26/anthropic-launches-interactive-claude-apps-including-slack-and-other-workplace-tools/)
- Anthropic's own announcement post is titled "interactive tools in Claude" — [claude.com blog](https://claude.com/de/blog/interactive-tools-in-claude)

**OpenAI Apps SDK / ChatGPT apps**
- Built on MCP. A tool's `structuredContent` is passed to the widget, which reads it from `window.openai.toolOutput`. `structuredContent`, `content` and `_meta` are separate payloads: the model reads `structuredContent`, while `_meta` is widget-only. The docs say to keep fields concise because "the model reads them verbatim" — [Apps SDK reference](https://developers.openai.com/apps-sdk/reference); [ChatGPT UI guide](https://developers.openai.com/apps-sdk/build/chatgpt-ui)
- A widget can call other tools with `window.openai.callTool(name, args)`, which requires `openai/widgetAccessible: true` on the tool. The host pushes updates through an `openai:set_globals` event — [Apps SDK reference](https://developers.openai.com/apps-sdk/reference); [Alpic deep-dive](https://alpic.ai/blog/inside-openai-s-apps-sdk-how-to-build-interactive-chatgpt-apps-with-mcp)
- Current official direction: "New UI should use the MCP Apps bridge whenever the shared specification provides an equivalent", and use `window.openai` only for ChatGPT-specific capabilities. The docs still label the Apps SDK "preview" — [MCP Apps in ChatGPT](https://developers.openai.com/apps-sdk/mcp-apps-in-chatgpt)
- Reported bug (community): when a tool returns both `content` and `structuredContent` with a widget, `content` was not forwarded to the model — [openai-apps-sdk-examples issue #144](https://github.com/openai/openai-apps-sdk-examples/issues/144)

**Google A2UI (Agent-to-User Interface)**
- Open source (Apache-2.0) protocol plus libraries. The agent sends **data, not code**: structured JSON that maps to a predefined **catalog of trusted components**, and the client renders it natively and controls the look. Google contrasts this with MCP's "prefab HTML in a sandbox" and calls A2UI "native-first". Used by the Flutter GenUI SDK, Opal and Gemini Enterprise — [The Decoder](https://the-decoder.com/googles-open-standard-lets-ai-agents-build-user-interfaces-on-the-fly/); [Analytics Vidhya, Dec 2025](https://www.analyticsvidhya.com/blog/2025/12/google-a2ui-explained/)
- Repository (fetched Nov 2026): links a "v1.0" protocol spec, with "Protocol v1.1" on the roadmap. "The widget catalog provides access to the widgets the agent is allowed to compose." Renderers exist for Lit, Angular, React, Flutter and SwiftUI, with Jetpack Compose mentioned. `@a2ui/catalog-mcp` renders A2UI returned in MCP tool results and UI resources. "Embedding A2UI in MCP Apps and vice versa" is on the roadmap. It integrates with A2A through `a2ui-a2a`. UI is validated data, schema-checked, and "designed so agents cannot handle protected data like payment or PII" — [github.com/google/A2UI](https://github.com/google/A2UI)
- v0.9 message model: four server-to-client messages, `createSurface` (needs `surfaceId` and `catalogId`, optional `theme`; replaces v0.8 `beginRendering`), `updateComponents` (a flat component list; one component must have `id:"root"`), `updateDataModel` (`path` + `value`, where an omitted value deletes the key) and `deleteSurface`. Catalogs are referenced by URL, e.g. `a2ui.org/specification/v0_9/catalogs/basic/catalog.json` — [a2ui.org messages reference](https://a2ui.org/reference/messages/); [v0.9 evolution guide](https://a2ui.org/specification/v0.9-evolution-guide); [Ant Design X A2UI v0.9 reference](https://cdn.jsdelivr.net/npm/@ant-design/x-skill@2.9.0/skills/x-card/reference/COMMANDS.md)
- v0.9 made the protocol bidirectional: the client can send its full surface data model with each action — [CopilotKit blog](https://copilotkit.ai/blog/a2ui-whats-new-in-google-generative-ui-spec)
- Transport-agnostic, so it can be carried over A2A, AG-UI, MCP and others — [Analytics Vidhya](https://www.analyticsvidhya.com/blog/2025/12/google-a2ui-explained/)
- Genkit has an A2UI integration — [genkit.dev A2UI](https://genkit.dev/docs/agents/a2ui/)

**Google Gemini "dynamic view" / Generative UI (Google Research)**
- Google Research blog, Nov 18, 2025, paper "Generative UI: LLMs are Effective UI Generators". Built on Gemini 3 Pro, with tool access (image generation, web search) and detailed system instructions covering goal, planning, examples and technical specs. The model **generates the full interactive page (code)**. Shipped as the "dynamic view" experiment in the Gemini app and in AI Mode in Search — [Google Research blog](https://research.google/blog/generative-ui-a-rich-custom-visual-interactive-user-experience-for-any-prompt/)

**Vercel AI SDK**
- AI SDK RSC (`streamUI`, which streams React Server Components from tool execution) is "experimental", and its "development is currently paused". The docs recommend AI SDK UI for production — [AI SDK RSC reference v6](https://v6.ai-sdk.dev/docs/reference/ai-sdk-rsc); [Vercel rsc-genui template](https://vercel.com/templates/ai/rsc-genui)
- AI SDK 5+ pattern: each tool gets a typed message part `tool-${toolName}` with states (e.g. `output-available`). The client switches on `part.type` and renders a React component per tool. `data-*` parts carry server-streamed data components, and `dynamic-tool` covers untyped tools. In the docs' words, generative UI means "connecting the results of a tool call to a React component" — [AI SDK generative UI docs](https://ai-sdk.dev/docs/ai-sdk-ui/generative-user-interfaces); [AI SDK 5 blog](https://vercel.com/blog/ai-sdk-5); [chatbot tool usage](https://ai-sdk.dev/v5/docs/ai-sdk-ui/chatbot-tool-usage)

**CopilotKit / AG-UI**
- AG-UI is an open, event-based protocol between agent backends and user-facing apps. Events are typed JSON over SSE or binary protobuf, and there are about 16 standard event types. It includes shared-state events (`STATE_SNAPSHOT`, and delta events) that keep app UI and agent state in sync in real time. It does not render UI itself: it manages UI lifecycle through tool events and state deltas, so it is "spec-agnostic" — [AG-UI repo](https://github.com/ag-ui-protocol/ag-ui); [CopilotKit AG-UI intro](https://copilotkit.ai/blog/introducing-ag-ui-the-protocol-where-agents-meet-users); [CopilotKit showcase docs](https://docs.showcase.copilotkit.ai/ag-ui-protocol)
- Integrations (repo, Nov 2026): LangGraph and CrewAI as launch partners. First-party: Microsoft Agent Framework, Google ADK, AWS Strands, Mastra, Pydantic AI, Agno, LlamaIndex, AG2. Community: Claude Agent SDK and others. OpenAI Agents SDK is "in progress". The repo lists MCP Apps as supported under "Generative UI". About 17.2k GitHub stars, MIT licence — [AG-UI repo](https://github.com/ag-ui-protocol/ag-ui)
- AWS published a guide to generative UI on Bedrock AgentCore with AG-UI — [AWS ML blog](https://aws.amazon.com/blogs/machine-learning/build-generative-ui-for-ai-agents-on-amazon-bedrock-agentcore-with-the-ag-ui-protocol/)

**LangGraph generative UI (LangGraph Platform / LangSmith deployments)**
- Server: a graph node calls `push_ui_message(name, props, message=...)`, which ties a named component and its props to an AI message. API: `push_ui_message`, `delete_ui_message`, `ui_message_reducer`. Components are bundled through a `ui` entry in `langgraph.json`. Client: `useStream` (`@langchain/langgraph-sdk/react`) plus `<LoadExternalComponent>`, which can take a local component map instead of fetching component code from the server. Pushing again with the same UI message id updates the component in place. `onCustomEvent` and `uiMessageReducer` handle streamed UI events. TS uses `typedUi(...).push()` — [LangGraph UI reference](https://reference.langchain.com/python/langgraph/graph/ui); [LangSmith generative UI guide](https://docs.langchain.com/langsmith/generative-ui-react); [assistant-ui LangGraph genUI](https://www.assistant-ui.com/docs/runtimes/langgraph/generative-ui)

**Thesys C1**
- An OpenAI-compatible "generative UI API" middleware: you change the baseURL and key, and the LLM responds with structured UI components instead of text. It streams UI progressively. It is rendered by the Crayon React SDK (MIT), which constrains output to a component library. There is also a "visualize" endpoint that turns data passed to it into UI. Launched around May 2025 — [Thesys docs: what is C1](https://docs.thesys.dev/guides/what-is-thesys-c1); [how C1 works](https://docs.thesys.dev/guides/how-c1-works); [Crayon](https://docs.thesys.dev/guides/crayon); [r/LLMDevs launch post, May 2025](https://reddit.birdcat.cafe/r/LLMDevs/comments/1kjc67w/we_built_c1_an_openaicompatible_llm_api_that). Sources are vendor docs only.

**Microsoft 365 Copilot / Adaptive Cards**
- Declarative agents and API plugins render API responses with **developer-authored Adaptive Card templates** in the plugin definition, so the agent picks the action and the template renders the data. Copilot Studio supports Adaptive Card schema 1.6 and earlier, and the right version depends on the host — [MS Learn training module](https://learn.microsoft.com/training/modules/copilot-declarative-agent-action-api-plugin-adaptive-cards-vsc); [Copilot Studio Adaptive Cards overview](https://learn.microsoft.com/microsoft-copilot-studio/adaptive-cards-overview)

**Apple App Intents interactive snippets (iOS 26, WWDC June 2025)**
- `SnippetIntent` (iOS 26) returns interactive SwiftUI views (buttons, controls) shown in system surfaces such as Siri, Spotlight and Visual Intelligence. Buttons in the snippet fire further app intents. The view is driven by `@Parameter` variables. Related iOS 26 APIs: `supportedModes`, `requestChoice(between:)`, `@DeferredProperty`. Here the *system* chooses the intent and the *app's own native code* draws the UI — [Superwall blog](https://superwall.com/blog/app-intents-interactive-snippets-in-ios-26); [Blake Crosley](https://blakecrosley.com/blog/app-intents-2-ios-26-additions). These are secondary sources; Apple's documentation was not fetched.

### Inferences
- Across these systems, "who decides" is almost always the **model, through tool selection**. MCP Apps and Apps SDK bind a tool to a `ui://` template. AI SDK maps `tool-X` to component X. Adaptive Cards bind a plugin action to a card template. Apple binds an intent to a SnippetIntent view. LangGraph and A2UI let graph code or the agent emit named components. For Nexus, the "which domain opens" decision is therefore best treated as a tool-routing or classification problem with code-bound UI, not as free-form generation.
- LangGraph `push_ui_message` (Nexus already uses LangGraph) and AG-UI/CopilotKit (which has a first-party LangGraph integration) are the two lowest-friction paths for a React web app. A2UI is the most portable declarative format if the later native mobile client should render natively.

### Gaps
- Exact `ui/*` method names in the final MCP Apps spec (e.g. `ui/initialize`, tool-input/result notifications, `ui/message`, model-context update, display modes) could not be verified because modelcontextprotocol.io was blocked. From prior knowledge (unverified here), the spec includes host→view notifications for tool input (including partial input) and results, view→host `tools/call`, a message-to-chat call, and a context update.
- OpenAI Apps SDK display modes (inline / fullscreen / picture-in-picture), `setWidgetState`, `sendFollowUpMessage` and current GA status were not verified because developers.openai.com was blocked.
- Gemini dynamic view runtime mechanics (sandbox, format) are not detailed beyond the blog.
- Exact AG-UI event names were not confirmed from the primary spec; the repo page only says "~16 event types".
- No official Apple developer doc was fetched.

## 2. Which pattern dominates for safety and consistency: fixed catalog vs. generated markup/code

### Takeaway
For production rendering, the **fixed component catalog with model-chosen props/data** dominates: A2UI, Adaptive Cards, AI SDK typed tool parts, LangGraph named components, Thesys/Crayon and Apple snippets. The **sandboxed developer-authored HTML** of MCP Apps is the cross-vendor standard for *third-party* apps inside chat hosts. Fully model-generated pages (Gemini dynamic view) remain experimental because of latency and accuracy.

### Cited Findings
- A2UI's security rationale is explicit: data, not code. Agents are limited to a trusted catalog, which reduces code-injection risk. Inputs and outputs are schema-validated. The client keeps visual control — [github.com/google/A2UI](https://github.com/google/A2UI); [The Decoder](https://the-decoder.com/googles-open-standard-lets-ai-agents-build-user-interfaces-on-the-fly/)
- MCP Apps isolates UI in a host-controlled sandboxed iframe. Templates are predeclared server resources (not model-generated), so hosts can review them in advance — [Ruby SDK MCP Apps docs](https://ruby.sdk.modelcontextprotocol.io/extensions/mcp-apps/); [SEP-1865](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp)
- Google frames the trade-off as "native-first" A2UI versus MCP's "prefab HTML in a sandbox". Native gives deeper host integration and consistent styling; HTML gives the third party full control of its UI — [The Decoder](https://the-decoder.com/googles-open-standard-lets-ai-agents-build-user-interfaces-on-the-fly/)
- Model-generated full pages: Google's own Gen UI can "take a minute or more", has "occasional inaccuracies", and quality "strongly depends" on the underlying model — [Google Research blog, Nov 2025](https://research.google/blog/generative-ui-a-rich-custom-visual-interactive-user-experience-for-any-prompt/)
- Vercel paused its most "generative" path (RSC `streamUI`) and recommends AI SDK UI, i.e. client-side components bound to typed tool parts — [AI SDK RSC docs](https://v6.ai-sdk.dev/docs/reference/ai-sdk-rsc)
- Practitioners report that constraining the model to a fixed component inventory is more reliable, and that picking a pre-validated template is the lowest-latency, most cacheable option — [metacto guide](https://www.metacto.com/blogs/generative-ui-production-guide); [ajing.github.io, 2026-01-01](https://ajing.github.io/posts/2026-01-01-generative-ui-doesnt-move-the-needle-steering-does) (practitioner opinion, not measured)
- Convergence: the A2UI roadmap includes A2UI-in-MCP-Apps and vice versa, and AG-UI lists MCP Apps support. The layers are composing rather than competing — [A2UI repo](https://github.com/google/A2UI); [AG-UI repo](https://github.com/ag-ui-protocol/ag-ui)

### Inferences
- For Nexus, a first-party app whose domains are known in advance (Finance, etc.), a catalog of hand-built domain dashboards and panels selected by tool or route and filled with model-chosen parameters is the clear fit. It is consistent, fast, safe and testable. Iframe or HTML generation brings sandboxing cost for no benefit, because Nexus owns all of its UI.
- Accuracy ("right info at right time") is then mostly a routing and parameterisation problem that can be evaluated offline, as tool-selection accuracy. It is not a rendering problem.

### Gaps
- No published head-to-head study of catalog vs. generated UI on correctness or safety was found.

## 3. Multiple UIs per turn, update-vs-open, and UI state flowing back to the agent

### Takeaway
Multiple UIs: every tool-call-bound system supports several UI parts or messages per turn (one per tool call or UI message). A2UI models this explicitly as multiple **surfaces**. Updates: done by stable ids (LangGraph same-id push; A2UI `surfaceId` with `updateComponents`/`updateDataModel`; AG-UI state deltas; Apps SDK `set_globals`). State back to the agent: either through explicit tool calls or actions from the UI, or through shared-state sync (AG-UI, A2UI v0.9 data model).

### Cited Findings
- A2UI: each UI is a surface with a `surfaceId`. You create it with `createSurface`, incrementally change it with `updateComponents` (flat list, so it streams) or `updateDataModel(path, value)`, and remove it with `deleteSurface`. That gives clean "update the open UI vs. open a new one" semantics — [a2ui.org messages](https://a2ui.org/reference/messages/); [Ant Design X reference](https://cdn.jsdelivr.net/npm/@ant-design/x-skill@2.9.0/skills/x-card/reference/COMMANDS.md)
- A2UI v0.9 is bidirectional, and the client can send its full surface data model with every user action — [CopilotKit blog](https://copilotkit.ai/blog/a2ui-whats-new-in-google-generative-ui-spec)
- LangGraph: pushing with the same UI message id updates the existing component, and `delete_ui_message` removes it. UI messages live in graph state through `ui_message_reducer`, so the agent can read them — [LangSmith genUI guide](https://docs.langchain.com/langsmith/generative-ui-react); [LangGraph UI reference](https://reference.langchain.com/python/langgraph/graph/ui)
- AG-UI: shared-state events (`STATE_SNAPSHOT`, deltas) keep frontend and agent state in sync in real time, which is CopilotKit's "shared state" feature — [CopilotKit showcase docs](https://docs.showcase.copilotkit.ai/ag-ui-protocol); [agentwiki AG-UI](https://agentwiki.org/ag_ui_protocol) (community)
- OpenAI Apps SDK: the widget calls tools (`window.openai.callTool`), and the host pushes fresh globals (`openai:set_globals`). The model sees `structuredContent` but not widget `_meta`, which separates model context from UI-only data — [Apps SDK reference](https://developers.openai.com/apps-sdk/reference)
- MCP Apps: on the server side, UI interactions show up only as ordinary `tools/call` and `resources/read` — [Ruby SDK](https://ruby.sdk.modelcontextprotocol.io/extensions/mcp-apps/)
- AI SDK: one typed part per tool call in `message.parts`, so several tool calls in a turn render several components in order — [AI SDK 5 blog](https://vercel.com/blog/ai-sdk-5)
- Apple: buttons in a snippet fire further app intents, and the view re-renders from `@Parameter` values — [Superwall](https://superwall.com/blog/app-intents-interactive-snippets-in-ios-26)

### Inferences
- Nexus pattern suggested by the evidence: keep a persistent "workspace" of domain surfaces keyed by stable id (e.g. `finance`, `calendar`). Prime's tool calls emit open/update/close events (LangGraph `push_ui_message` with a stable id, or an AG-UI/A2UI-style surface model), and the user's interactions in a panel write to shared state that Prime reads on the next turn. Updating by id instead of re-pushing reduces flicker.
- Chat-inline widgets (ChatGPT/Claude style) tie a UI to a message. Nexus's vision of *side panels that stay open* is closer to CopilotKit shared state or A2UI surfaces than to inline widgets.

### Gaps
- Explicit host policies on concurrent widgets (e.g. whether ChatGPT limits fullscreen to one widget at a time) were not verified.
- MCP Apps' exact mechanism for pushing UI state into model context could not be confirmed from the primary spec.

## 4. Published evidence of user outcomes (engagement, task success, latency, failure modes)

### Takeaway
Hard outcome data is scarce. The only rigorous published evaluation is Google's: human raters strongly preferred generated UI over text and search results, but ranked it below expert-built sites, and it ignored latency. Latency for fully generated UI is on the order of a minute or more. Most other "evidence" is vendor surveys or practitioner opinion. No public A/B data from OpenAI, Anthropic or Microsoft on widget engagement or task success was found.

### Cited Findings
- Google Research (Nov 2025): with generation speed ignored, human raters "strongly preferred" generative UI over standard LLM text and the top Google Search result. Expert-designed websites ranked highest, generative UI was close behind, and other formats trailed by a substantial gap. Google released or announced the PAGEN dataset of expert-made sites. Limitations: generation can "take a minute or more", outputs have "occasional inaccuracies", and quality depends heavily on the model — [Google Research blog](https://research.google/blog/generative-ui-a-rich-custom-visual-interactive-user-experience-for-any-prompt/)
- Academic (2026): in an ASSETS '25 study, full-page HTML regeneration took 1 to 5 minutes per page — [arXiv 2604.25455](https://arxiv.org/pdf/2604.25455). A separate paper on generative interfaces for LLMs reports that iterative refinement adds latency of up to several minutes — [arXiv 2508.19227 via Emergent Mind](https://www.emergentmind.com/papers/2508.19227)
- Vendor survey: Thesys reports 145 respondents, 77% of whom said generative UI could save time. This is self-reported preference, not measured task success — [dev.to summary](https://dev.to/rahulkhinchi03/ui-based-chatbots-vs-text-based-chatbots-task-completion-rate-time-on-task-and-user-satisfaction-2o4e)
- Practitioner argument: generative UI by itself "doesn't move the needle"; steering, meaning getting the right content and action, does — [ajing.github.io, 2026-01-01](https://ajing.github.io/posts/2026-01-01-generative-ui-doesnt-move-the-needle-steering-does) (opinion)
- Known failure modes in docs and bug reports: the model not receiving `content` when a widget is attached (Apps SDK issue) — [GitHub issue #144](https://github.com/openai/openai-apps-sdk-examples/issues/144). Renderers silently ignoring valid A2UI fields (`theme`, `sendDataModel` in Ant Design X) — [Ant Design X reference](https://cdn.jsdelivr.net/npm/@ant-design/x-skill@2.9.0/skills/x-card/reference/COMMANDS.md)

### Inferences
- For Nexus, the measurable quality is **routing precision and recall** (did the right domain panel open, with the right filters, and did unneeded panels stay closed) plus time-to-first-panel. Catalog plus tool routing keeps latency at roughly tool-call speed, while generated UI costs tens of seconds to minutes based on the cited studies. Building an offline eval set of utterance → expected panel(s) is likely higher-leverage than any rendering choice. This is inferred from the absence of other strong evidence and from the latency data.

### Gaps
- No public data on wrong-UI or flicker rates, or on engagement lift, from ChatGPT apps, Claude interactive apps, M365 Copilot or Gemini dynamic view.
- No controlled study comparing fixed-catalog and generated UI on task completion or time-on-task was found.
- No published accuracy metrics for "when to show UI" or "which UI" decisions (tool-routing accuracy for UI) in any vendor system.
