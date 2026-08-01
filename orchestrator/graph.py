from langgraph.graph import StateGraph, START, END
from orchestrator.state import AssistantState
from orchestrator.supervisor import supervisor
from orchestrator.subagents import (
    email_subagent,
    expense_subagent,
    route_subagent,
    recipe_subagent,
    general_subagent,
)
from orchestrator.checkpointer import checkpointer

# Create LangGraph StateGraph with AssistantState
builder = StateGraph(AssistantState)

# Add supervisor and capability subagent nodes
builder.add_node("supervisor", supervisor)
builder.add_node("email_subagent", email_subagent)
builder.add_node("expense_subagent", expense_subagent)
builder.add_node("route_subagent", route_subagent)
builder.add_node("recipe_subagent", recipe_subagent)
builder.add_node("general_subagent", general_subagent)

# Set entry point to supervisor
builder.add_edge(START, "supervisor")

# Compile graph with memory checkpointer
assistant_graph = builder.compile(checkpointer=checkpointer)

