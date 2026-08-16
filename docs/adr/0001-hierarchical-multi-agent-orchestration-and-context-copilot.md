# 1. Hierarchical Multi-Agent Orchestration & Context-Aware Page Copilots

Date: 2026-08-16

## Status

Accepted

## Context

Nexus Prime serves as a personal life cockpit managing diverse domains: expense tracking, transit routing, email triage, grocery management, and scheduled reminders.

We needed an architectural pattern for how user conversations are handled across these capabilities:
1. Should the user interact with multiple disjointed specialist chatbots, or a single cohesive Personal Assistant?
2. How should specialist domain logic (prompts, tools, and schemas) be organized without polluting the top-level orchestrator?
3. How should interactive chat work when a user is navigating specific functional pages on the web dashboard (e.g. Transactions vs. Reminders vs. Groceries)?

## Decision

1. **Dual-Surface Interface Architecture**:
   - **Telegram (Ambient & Conversational Gateway)**: The dedicated, always-on mobile channel. Handles mobile receipt photos, quick conversational logs, asynchronous push notifications (daily spend sweeps, scheduled reminders), and inline button confirmations.
   - **Web Dashboard (Visual Control Center & Copilot)**: The visual management plane for high-density analysis (tables, sorting, filtering, batch edits, undo, charts), equipped with an on-demand collapsible Copilot Drawer for live conversational steering.

2. **Hierarchical Hub-and-Spoke Orchestration (`PersonalAssistantSupervisor`)**:
   - The user always interacts with the **Main Personal Assistant** as the unified conversational persona across both Telegram and Web.
   - The supervisor plans task decomposition and delegates domain sub-tasks to **Specialist Agents** (`ExpenseSpecialist`, `EmailSpecialist`, `CommuteSpecialist`, `ReminderSpecialist`, `RecipeSpecialist`).
   - Specialist agents operate statelessly on domain tools, returning structured `SpecialistOutput` contracts back to the supervisor to compile into the final response.

3. **Context-Aware Page Copilot**:
   - Rather than spinning up separate restricted chat endpoints for each page, page-level chat surfaces (e.g., floating/drawer copilot on the Transactions page) talk to the unified Personal Assistant API while providing ambient page metadata (`current_view: "transactions"`, active ledger filters).
   - The assistant biases suggestions and immediate context toward the active page, but can still answer cross-domain queries without hitting dead ends.

4. **Reactive UI State Synchronization (`ReactiveUIEvents`)**:
   - When actions modify state (e.g. logging an expense, deleting a reminder, toggling a grocery), the API emits structured `ReactiveUIEvents` alongside conversational text.
   - The client-side dashboard consumes these events to trigger immediate, targeted re-renders (updating tables, KPI cards, and charts) without full page refreshes.

## Consequences

### Positive
- **Cohesive User Experience**: One consistent, highly capable AI assistant across Telegram and the Web Cockpit.
- **Deep Domain Specialization**: Each specialist retains tight, focused prompts and schemas without leaking implementation details across domain boundaries.
- **Real-Time Synergy**: Conversational actions instantly reflect on the visual UI.

### Trade-offs / Mitigations
- **Orchestration Overhead**: Multi-turn cross-domain queries require structured schema extraction before synthesis (mitigated by fast deterministic routing for single-domain queries).
- **Client Event Handling**: Frontend requires an event listener dispatcher to map `ReactiveUIEvents` to component reload hooks.
