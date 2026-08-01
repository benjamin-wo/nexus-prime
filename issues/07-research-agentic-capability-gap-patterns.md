# 07 - Research Agentic Capability-Gap & Open-World Handling Patterns

Status: resolved
Label: wayfinder:research
Parent: 06-capability-gap-handling-map.md
Blocked by: none

## Question

What are the industry best practices in modern multi-agent systems (e.g., LangGraph supervisor routing, OpenAI Tool/Function calling guardrails, and Model Context Protocol MCP) for handling user prompts that fall outside an assistant's pre-configured capability plugins without hallucinating or breaking conversational flow?

## Answer & Industry Findings

### 1. LangGraph Supervisor Out-of-Distribution Intent Routing
- **Pattern**: Instead of forcing a supervisor LLM to pick only from built-in domain subagents (`email`, `expenses`, `routes`, `recipes`), modern LangGraph supervisors use a **Structured Routing Protocol** that returns both a destination (`goto`) and an intent metadata object:
  ```python
  class SupervisorRoutingDecision(TypedDict):
      goto: Literal["email", "expenses", "routes", "recipes", "general_subagent", "FINISH"]
      intent_type: Literal["in_scope", "informational_fallback", "unsupported_transaction"]
      missing_tags: List[str]  # e.g., ["calendar", "smart_home"]
  ```
- **Behavior**:
  - `in_scope`: Routes directly to the specialized domain subagent (`email`, etc.).
  - `informational_fallback`: Routes to `general_subagent` (equipped with web search / general reasoning).
  - `unsupported_transaction`: Routes to `FINISH` with an explicit guardrail refusal message and triggers an asynchronous write to `CapabilityRequestLog`.

### 2. Transactional vs. Informational Discrimination (Guardrail Best Practice)
- **Informational Intents (Safe for General Fallback)**: Read-only, factual, or reasoning tasks (e.g., *"What is the weather in Tokyo?"*, *"How many ounces in a liter?"*, *"Explain this concept"*). These carry **zero side-effects** and should be handled smoothly by `general_subagent`.
- **Transactional Intents (Strict Refusal Guardrail)**: Requests that attempt to modify external state, spend money, send communications, or control hardware (e.g., *"Book a flight to Paris"*, *"Transfer $100 to Alice"*, *"Turn off my living room lights"*).
  - **Rule**: If a transactional request is unsupported, an AI assistant **MUST NEVER** attempt to answer via general search or hallucinate a tool execution. It must refuse cleanly: *"I don't currently have a capability plugin for [task]. I've logged [tags] as a feature request for future releases."*

### 3. Extensible Registry Specs (Model Context Protocol / OpenAPI)
- **Runtime Capability Discovery**: To allow adding custom tools without core code modifications, modern systems use an `ExternalCapabilityRegistry` (inspired by MCP / OpenAI Custom Actions).
- **Schema**:
  - Each dynamic tool defines: `name`, `description`, `input_schema` (JSONSchema), and `webhook_url`.
  - At compilation or supervisor evaluation time, the supervisor system prompt dynamically injects the descriptions of both built-in plugins (`capabilities/`) and active external capabilities.
