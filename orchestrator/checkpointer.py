from typing import List, Tuple
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from core.config import settings


_checkpointer = None
_postgres_iterator = None


def get_checkpointer():
    """Return the active checkpointer (PostgresSaver in production, MemorySaver otherwise)."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
    return _checkpointer


async def setup_checkpointer():
    """
    Initialize the durable Postgres checkpointer when a Postgres database is
    configured. Falls back to MemorySaver on any failure so the app still boots.
    """
    global _checkpointer, _postgres_iterator

    if not settings.database_url.startswith("postgresql"):
        return
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        conn_string = settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        iterator = AsyncPostgresSaver.from_conn_string(conn_string, pipeline=True)
        saver = await anext(iterator)
        await saver.setup()
        _postgres_iterator = iterator
        _checkpointer = saver
        print("[CHECKPOINTER] PostgresSaver ready — conversation memory is durable.")
    except Exception as exc:  # noqa: BLE001
        print(f"[CHECKPOINTER] PostgresSaver unavailable, using MemorySaver: {exc}")
        _checkpointer = MemorySaver()


async def close_checkpointer():
    """Release the Postgres checkpointer connection pool on shutdown."""
    global _postgres_iterator, _checkpointer
    if _postgres_iterator is not None:
        try:
            await _postgres_iterator.aclose()
        except Exception:  # noqa: BLE001
            pass
        _postgres_iterator = None
    _checkpointer = MemorySaver()


def prune_and_summarize_messages(
    messages: List[BaseMessage], threshold: int = 25
) -> Tuple[List[BaseMessage], str]:
    """
    Automatic summarization/pruning hook: when message history exceeds `threshold`,
    compress older turns into a concise summary string to keep prompt tokens low.
    Returns (pruned_messages, summary_string).
    """
    if len(messages) <= threshold:
        return messages, ""

    recent_messages = messages[-10:]
    older_messages = messages[:-10]

    summary_lines = []
    for msg in older_messages:
        role = getattr(msg, "type", "user")
        content = str(msg.content)[:100]
        summary_lines.append(f"{role}: {content}")

    summary_str = "Prior Conversation Summary:\n" + "\n".join(summary_lines[:15])
    system_note = SystemMessage(content=f"[SYSTEM: {summary_str}]")
    return [system_note] + recent_messages, summary_str
