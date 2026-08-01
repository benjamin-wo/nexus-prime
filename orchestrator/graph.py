from langgraph.graph import StateGraph, START, END
from orchestrator.state import AssistantState
from orchestrator.router import capability_router_node
from orchestrator.checkpointer import get_checkpointer


_assistant_graph = None


def get_assistant_graph():
    """
    Lazily build and compile the LangGraph StateGraph with the active checkpointer.
    The Postgres checkpointer is initialized at app startup, so the graph must be
    compiled after that — this factory guarantees it.
    """
    global _assistant_graph
    if _assistant_graph is None:
        builder = StateGraph(AssistantState)
        builder.add_node("capability_router", capability_router_node)
        builder.add_edge(START, "capability_router")
        _assistant_graph = builder.compile(checkpointer=get_checkpointer())
    return _assistant_graph
