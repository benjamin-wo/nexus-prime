from langgraph.graph import StateGraph, START, END
from orchestrator.state import AssistantState
from orchestrator.router import capability_router_node
from orchestrator.checkpointer import checkpointer

# Create LangGraph StateGraph with AssistantState
builder = StateGraph(AssistantState)

# Add single deep CapabilityRouter node
builder.add_node("capability_router", capability_router_node)

# Set entry point to capability_router
builder.add_edge(START, "capability_router")

# Compile graph with memory checkpointer
assistant_graph = builder.compile(checkpointer=checkpointer)
