# Nexus Prime Domain & Architecture Glossary

This document records the Ubiquitous Language and Architectural Seams for `nexus-prime` (a 3-Layer Personal Assistant Bot).

## Core Architectural Modules & Seams

### 1. Dual-Surface Ingress Architecture
- **Telegram (Ambient & Conversational Gateway)**: The always-on primary mobile chat interface. Handles conversational flows, photo/receipt snapshots, proactive reminder push notifications, ambient scheduled sweeps, and inline keyboard HITL confirmations.
- **Web Cockpit (Visual Control Center & Copilot)**: The visual analytics and data control plane. Houses high-density metric cards, SVG breakdown charts, sortable/filterable transaction tables, batch operations, and a collapsible contextual AI Copilot Drawer that reactively synchronizes the visual dashboard in real time.
- **TelegramIngress**: A deep adapter module (`app/ingress.py`) that encapsulates all Telegram Bot API concerns:
  - Verifies incoming webhook payloads and normalizes user/chat IDs.
  - Resolves or provisions the `UserProfile` in PostgreSQL.
  - Directly executes all deterministic slash commands (`/jobs`, `/timezone`, `/missing_capabilities`, `/run_now`) without invoking LangGraph.
  - Handles inline keyboard button callback resumption (`Command(resume=...)`) and telemetry feature request tagging (`log_req:<tag>`).
  - Normalizes conversational prompts and multimodal media attachments into a clean `AssistantState` dictionary before handing off across the seam to LangGraph.
- **The Seam**: Decouples external messaging channels (Telegram Webhook, Web Copilot REST/SSE) from the core multi-agent domain orchestrator.

### 2. Orchestration & Multi-Agent Layer
- **PersonalAssistantSupervisor**: The top-level conversational orchestrator agent. Owns the primary user relationship and persona, interprets complex/cross-domain intents, dispatches sub-tasks to Specialist Agents, and synthesizes structured specialist results into a cohesive final response.
- **SpecialistAgent**: A dedicated domain worker agent (e.g., `ExpenseSpecialist`, `EmailSpecialist`, `CommuteSpecialist`, `ReminderSpecialist`, `RecipeSpecialist`) encapsulating domain tools, specialized system prompts, and validation schemas. Operates in two modes:
  1. *Subagent Worker Mode*: Invoked by the `PersonalAssistantSupervisor` during multi-agent workflows, returning structured data contracts (`SpecialistOutput`).
  2. *Direct Interactive Mode*: Exposed directly in the UI as a domain-specific interactive copilot when the user is on that specialist's dedicated dashboard view.
- **SpecialistOutput**: The structured contract returned by a Specialist Agent back to the Supervisor, containing raw domain entities, summary metrics, and status flags.
- **CapabilityRouter**: A deep orchestrator module (`orchestrator/router.py`) that evaluates user intent against declarative registries, managing delegation to appropriate Specialist Agents and enforcing `GuardrailPolicy`.
- **CapabilityPlugin**: The Protocol interface implemented by all domain capabilities (`EmailPlugin`, `ExpensePlugin`, `RoutePlugin`, `RecipePlugin`, `GeneralPlugin`).
  - **Interface**: Requires `name`, `keywords`, `description`, and `async def execute(self, state: AssistantState) -> PluginOutput`.
- **PluginOutput**: A pure Python data structure (`message: AIMessage`, `state_update: Dict[str, Any]`) returned by a `CapabilityPlugin`. It decouples domain capability implementations from LangGraph graph/command internals, allowing 2-line standalone unit tests.
- **GuardrailPolicy**: A declarative policy registry within `CapabilityRouter` that detects unsupported transactional requests (e.g., bank transfers, calendar scheduling, flight bookings, smart home controls) and logs wishlist feature requests.
