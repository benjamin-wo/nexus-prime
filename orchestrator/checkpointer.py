from typing import List, Tuple
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from core.config import settings

# By default, use MemorySaver for zero-config local testing and development
# In full PostgreSQL Railway deployment, PostgresSaver from langgraph.checkpoint.postgres can be swapped in
checkpointer = MemorySaver()

def prune_and_summarize_messages(messages: List[BaseMessage], threshold: int = 25) -> Tuple[List[BaseMessage], str]:
    """
    Automatic summarization/pruning hook: when message history exceeds `threshold`,
    compress older turns into a concise summary string to keep prompt tokens low.
    Returns (pruned_messages, summary_string).
    """
    if len(messages) <= threshold:
        return messages, ""

    # Retain the most recent 10 messages for immediate dialogue context
    recent_messages = messages[-10:]
    older_messages = messages[:-10]

    # Summarize older turns compactly
    summary_lines = []
    for msg in older_messages:
        role = getattr(msg, "type", "user")
        content = str(msg.content)[:100]
        summary_lines.append(f"{role}: {content}")

    summary_str = "Prior Conversation Summary:\n" + "\n".join(summary_lines[:15])

    # Prepend a SystemMessage note with the summary
    system_note = SystemMessage(content=f"[SYSTEM: {summary_str}]")
    return [system_note] + recent_messages, summary_str
