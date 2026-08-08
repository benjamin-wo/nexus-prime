from typing import Optional, List, Dict, Any
from langgraph.graph import MessagesState

class AssistantState(MessagesState):
    """Shared state for the LangGraph multi-agent orchestrator."""
    user_id: int
    current_timezone: str
    active_domain: Optional[str]
    pending_confirmation: Optional[Dict[str, Any]]
    ui_actions: Optional[List[Dict[str, Any]]]
    conversation_summary: Optional[str]
    intent_type: Optional[str]
    missing_capability_tags: Optional[List[str]]
    fallback_reason: Optional[str]
    last_decision: Optional[Dict[str, Any]]
