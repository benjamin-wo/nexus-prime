# 08 - Design Supervisor Fallback & Intent Protocol

Status: resolved
Label: wayfinder:grilling
Parent: 06-capability-gap-handling-map.md
Blocked by: 07-research-agentic-capability-gap-patterns.md

## Question

How should `AssistantState` in `orchestrator/state.py` and the routing logic in `orchestrator/supervisor.py` be extended to support explicit intent classification (`in_scope`, `informational_fallback`, `unsupported_transaction`), so that unsupported transactional actions receive a structured refusal while general informational questions route to a generalist fallback subagent?

## Answer & Specification

1. **State Schema (`AssistantState` in `orchestrator/state.py`)**:
   - Add optional intent tracking fields without breaking existing state contracts:
     - `intent_type: Optional[str]` — Valid values: `"in_scope"`, `"informational_fallback"`, `"unsupported_transaction"`.
     - `missing_capability_tags: Optional[List[str]]` — e.g., `["calendar", "smart_home"]`.
     - `fallback_reason: Optional[str]` — Natural language rationale for the routing decision.
2. **Supervisor Refusal & Auto-Log Guardrail (`orchestrator/supervisor.py`)**:
   - When the supervisor classifies a prompt as `unsupported_transaction`, it must:
     - Route to `goto="FINISH"`.
     - Output an immediate, polite refusal message: *"I don't currently have a capability plugin for [task]. I have logged [tags] as a feature request for future releases."*
     - Automatically invoke the telemetry logger (`log_capability_request`) to persist an entry in `CapabilityRequestLog`.
   - When classified as `informational_fallback`, it routes to `goto="general_subagent"` to answer via general reasoning/search.
