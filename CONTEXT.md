# Nexus Prime Domain & Architecture Glossary

This document records the Ubiquitous Language and Architectural Seams for `nexus-prime` (a general-purpose agentic assistant living on Telegram and a web cockpit).

## Core Architectural Modules & Seams

### 1. Dual-Surface Ingress Architecture
- **Telegram (Ambient & Conversational Gateway)**: The always-on primary mobile chat interface. Handles conversational flows, photo/receipt snapshots, proactive reminder push notifications, ambient scheduled sweeps, and inline keyboard HITL confirmations.
- **Web Cockpit (Visual Control Center & Copilot)**: The visual analytics and data control plane. Houses high-density metric cards, SVG breakdown charts, sortable/filterable transaction tables, batch operations, and a collapsible contextual AI Copilot Drawer that reactively synchronizes the visual dashboard in real time.
- **TelegramIngress**: A deep adapter module (`app/ingress.py`) that encapsulates all Telegram Bot API concerns:
  - Verifies incoming webhook payloads and normalizes user/chat IDs.
  - Resolves or provisions the `UserProfile` in PostgreSQL.
  - Directly executes all deterministic slash commands (`/jobs`, `/timezone`, `/run_now`) without invoking LangGraph.
  - Handles inline keyboard button callback resumption (`Command(resume=...)`) and telemetry feature request tagging (`log_req:<tag>`).
  - Normalizes conversational prompts and multimodal media attachments into a clean `AssistantState` dictionary before handing off across the seam to LangGraph.
- **The Seam**: Decouples external messaging channels (Telegram Webhook, Web Copilot REST/SSE) from the core agentic orchestrator.

### 2. Agentic Core & Safety Kernel (`orchestrator/`)
- **AgentLoop (`agent_turn`)**: THE orchestrator. One tool-chaining agent (bounded rounds) with the full conversation history, the skill index, and every tool declared by installed skills. Replaces the former plan → dispatch subagent pipeline.
- **Safety Kernel**: The deterministic checks inside `agent_turn` that never reach the LLM:
  - `TerminationIntent` — "stop"/"cancel"/"that's enough" end the turn.
  - `MediaTurn` — receipt-expense extraction first, multimodal description as fallback.
  - `IncomeWrite` — incoming-money parsing + persistence (and friend-repayment IOU settlement) stay deterministic; money writes never depend on the model.
  - `BusContinuation` — a pending bus-stop disambiguation answer stays inside the live LTA arrivals handler.
  - `GuardrailPolicy` — unsupported transactional categories (bank transfers, bookings, smart home, email send) are refused honestly and logged as capability-gap telemetry.
  - `SelfDiagnosis` — "why did you..."/"is this broken?" questions are answered from the bot's own integration health (`orchestrator/self_diagnostics.py`), not routed into a skill flow.
  - `IdentityGuard` — any model-supplied `user_id` is overridden with the authenticated one before a tool runs.
- **HITL (Human-in-the-Loop)**: LangGraph `interrupt()` / `Command(resume=...)` suspends the turn for ambiguous expenses and other consequential writes; Telegram and the cockpit render the confirmation buttons.

### 3. Skill System (`skills/` + `core/skill_registry.py`)
- **Skill**: A folder `skills/<name>/` containing `SKILL.md` — markdown with YAML frontmatter (`name`, `description`, `tags`, `side_effect: read|write|spend|irreversible`, `tools: [...]`) plus an instruction body. The body is loaded on demand via the `load_skill` tool (progressive disclosure). Adding a skill = dropping a folder; no code changes.
- **SkillTool**: An optional `skills/<name>/tools.py` holding `@tool` callables owned by that skill; loaded lazily alongside core tools.
- **ToolRegistry**: The name → callable index of every executable `@tool` across `capabilities/*/tools.py`, `orchestrator/recipes.py`, and skill-owned `tools.py` modules. Frontmatter `tools:` entries resolve against it; unknown names warn at load.
- **SkillIndex**: The compact one-line-per-skill listing injected into the agent's system prompt.
- **Capability**: The union of a Skill and the tools it declares. Instances: web-research, expenses, transit (live LTA bus arrivals + Google Maps journeys), email, reminders, recipes-groceries, memory (points/miles balances), bug-logging, daily-briefing, whiteboard-planning, composed-recipes, code-exec (kernel-gated to admins).
- **Multi-tenancy**: Every tool is user-scoped via the IdentityGuard; `admin_only_capabilities` (config) gates sensitive skills.
