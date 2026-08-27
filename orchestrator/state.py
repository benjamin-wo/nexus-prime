from typing import Optional, List
from langgraph.graph import MessagesState

class AssistantState(MessagesState):
    """Shared state for the LangGraph agentic orchestrator.

    Deliberately small: the old deterministic-planner era carried extra
    fields (last_decision, plan, last_route, pending_bus_stops,
    pending_confirmation, ui_actions, conversation_summary, fallback_reason)
    to spoon-feed context to narrow, single-message-blind regex plugins.
    orchestrator/agent_loop.py's agent sees the full message transcript
    (including its own prior tool calls/results) every turn, so multi-turn
    continuity ("another route", "which stop did you mean") is the agent's
    own reasoning over that transcript now, not a dedicated field.
    """
    user_id: int
    current_timezone: str
    active_domain: Optional[str]
    channel: Optional[str] = None  # "telegram" | "web" | "api" — for wishlist/bug telemetry attribution
    # Set by agent_loop.py when this turn called log_capability_gap, so
    # app/ingress.py can attach the "+ Log Feature Request" button --
    # the one piece of the old planner-era contract still needed outside
    # the agent loop itself.
    intent_type: Optional[str]
    missing_capability_tags: Optional[List[str]]
