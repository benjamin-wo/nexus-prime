# 01 - Core Supervisor & Capability Handoff Protocol

Status: resolved
Type: grilling

## Question

What exact message/state schema should the LangGraph Supervisor pass when delegating to domain subagents (`EmailSubagent`, `ExpenseSubagent`, `RouteSubagent`, `RecipeSubagent`), and how should multi-turn interruptions (`interrupt_before`) be handled for human-in-the-loop confirmations?

## Answer

1. **Subgraph Handoff Protocol**: Use LangGraph `Command(goto=...)` with a shared base state (`AssistantState` extending `MessagesState` with `user_id`, `current_timezone`, and `active_domain`).
2. **Human-in-the-Loop Interruption Protocol**: Use LangGraph `interrupt()` combined with Telegram 1-tap Inline Keyboard buttons (`[✅ Confirm]` / `[❌ Cancel]`). Telegram callback queries trigger `graph.invoke(Command(resume=True), config=...)`.
3. **Session & Thread Management**: Use persistent Telegram chat threads (`thread_id = str(chat_id)`) backed by PostgreSQL (`PostgresSaver`), with an automatic summarization/pruning hook when threads exceed ~20-30 messages to prevent token overflow.
