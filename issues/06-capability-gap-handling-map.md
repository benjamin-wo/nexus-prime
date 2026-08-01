# 06 - Wayfinder Map: Capability-Gap & Open-World Task Handling

Status: resolved
Label: wayfinder:map

## Destination

An engineered Capability-Gap & Open-World Task Handling System for the Telegram Personal Assistant Bot that combines:
1. **Hybrid Generalist Fallback**: Answers informational questions via general web/reasoning while safely rejecting unsupported transactional actions.
2. **Capability Demand Telemetry Loop (`CapabilityRequestLog`)**: Automatically logs missing capability requests (user prompt, missing tags, intent type) into PostgreSQL/SQLite to drive data-informed engineering roadmaps for future version releases.

## Notes

- Domain: Multi-agent orchestration, LangGraph supervisor routing, LLM safety guardrails, open-world tool calling, telemetry & product discovery.
- Skills: `/research`, `/grilling`, `/prototype`.
- Standing preferences: Maintain 100% test suite pass rate; avoid hallucinating capabilities; prefer explicit intent classification.

## Child Tickets & Frontier (Dependency Graph)

*(All child tickets resolved — map complete!)*

## Decisions so far

- [07-research-agentic-capability-gap-patterns.md](file:///Users/benjaminwo/Documents/agent-learn/issues/07-research-agentic-capability-gap-patterns.md) — Use Structured Routing Protocol (`in_scope`, `informational_fallback`, `unsupported_transaction`) with strict refusal guardrails for unsupported actions and dynamic MCP-style registry discovery.
- [08-design-supervisor-fallback-intent-protocol.md](file:///Users/benjaminwo/Documents/agent-learn/issues/08-design-supervisor-fallback-intent-protocol.md) — Add optional `intent_type`, `missing_capability_tags`, and `fallback_reason` to `AssistantState`; route `unsupported_transaction` to `FINISH` with guardrail refusal and auto-log to telemetry.
- [10-design-capability-demand-telemetry.md](file:///Users/benjaminwo/Documents/agent-learn/issues/10-design-capability-demand-telemetry.md) — Define `CapabilityRequestLog` table in `core/models.py` and `log_capability_request` helper in `core/audit.py`; access via `/missing_capabilities` command in chat or Railway DB Data Explorer.
- [09-prototype-generalist-fallback-subagent.md](file:///Users/benjaminwo/Documents/agent-learn/issues/09-prototype-generalist-fallback-subagent.md) — Equip `general_subagent` with web search & timezone calculator for factual queries; provide 1-tap inline Telegram button `[ + Log Feature Request (#tag) ]` for unsupported transactional refusals.

## Not yet specified

- How to dynamically register third-party external webhooks or user-defined scheduler jobs without changing core code.
- How to rate-limit or sandbox a generalist web-research subagent against abuse or excessive API usage.

## Out of scope

- Autonomous execution of high-risk financial or system-control actions without explicit Human-in-the-Loop (HITL) confirmation.
