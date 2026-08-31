from typing import List, Tuple
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
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
        # DB-level hang bound (live incident, chat=149917165): a dead/stale
        # pooled connection made checkpoint I/O hang forever and silently --
        # the turn held the per-chat lock, every later message starved, and
        # nothing printed. statement_timeout makes the SERVER kill a wedged
        # statement after 30s so the pool surfaces an error instead. Delivered
        # via the libpq `options` parameter because from_conn_string in the
        # installed langgraph version accepts only a conninfo string.
        bounded_conn_string = _with_statement_timeout(conn_string, CHECKPOINT_STATEMENT_TIMEOUT_MS)
        iterator = AsyncPostgresSaver.from_conn_string(bounded_conn_string, pipeline=True)
        saver = await iterator.__aenter__()
        await _run_postgres_migrations(conn_string)
        _postgres_iterator = iterator
        _checkpointer = saver
        print("[CHECKPOINTER] PostgresSaver ready — conversation memory is durable.")
    except Exception as exc:  # noqa: BLE001
        print(f"[CHECKPOINTER] PostgresSaver unavailable, using MemorySaver: {exc}")
        _checkpointer = MemorySaver()


CHECKPOINT_STATEMENT_TIMEOUT_MS = 30_000


def _with_statement_timeout(conn_string: str, timeout_ms: int) -> str:
    separator = "&" if "?" in conn_string else "?"
    return f"{conn_string}{separator}options=-c%20statement_timeout%3D{timeout_ms}"


async def reset_checkpointer() -> None:
    """Rebuild the Postgres checkpointer from scratch.

    Incident-driven: a wedged checkpoint connection hung every turn silently.
    statement_timeout now bounds each statement, but a pool that already
    handed out dead connections can keep doing so; rebuilding the saver gives
    the next turn a fresh pool. Turns running during the rebuild fall back to
    the in-memory checkpointer instead of hanging. Best-effort and bounded:
    tearing down the old pool must never hang the heal itself.
    """
    global _checkpointer, _postgres_iterator
    from core.tool_safety import bounded_call

    old_iterator = _postgres_iterator
    _checkpointer = MemorySaver()
    _postgres_iterator = None
    if old_iterator is not None:
        try:
            await bounded_call(
                old_iterator.__aexit__(None, None, None), 10.0, "checkpointer teardown"
            )
        except Exception as exc:  # noqa: BLE001 - the old pool is the patient
            print(f"[CHECKPOINTER] old pool teardown abandoned: {exc}")
    await setup_checkpointer()


async def _run_postgres_migrations(conn_string: str) -> None:
    """
    Apply the checkpointer DDL statement-by-statement on an autocommit connection.
    The stock saver.setup() runs the whole migration as one transaction, which
    breaks CREATE INDEX CONCURRENTLY.
    """
    from langgraph.checkpoint.postgres.base import MIGRATIONS
    from psycopg import AsyncConnection

    conn = await AsyncConnection.connect(conn_string, autocommit=True)
    try:
        for migration in MIGRATIONS:
            for statement in migration.split(";"):
                if statement.strip():
                    await conn.execute(statement)
    finally:
        await conn.close()


async def close_checkpointer():
    """Release the Postgres checkpointer connection pool on shutdown."""
    global _postgres_iterator, _checkpointer
    if _postgres_iterator is not None:
        try:
            await _postgres_iterator.__aexit__(None, None, None)
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


def recent_turns(messages: List[BaseMessage], n: int = 3, exclude_last: bool = True) -> str:
    """Compact "User: ...\\nAssistant: ..." formatting of the last `n` human/AI
    turn pairs, for threading into a domain plugin's own LLM extraction call
    as follow-up context (#35) -- without changing what triggers that call in
    the first place. Every plugin's deterministic fast-path/regex checks keep
    operating on the single latest message exactly as before; this is purely
    additional context for the LLM fallback path, so a reactive follow-up
    ("make that $20 instead", "and that one too") can be resolved against
    what was actually just discussed instead of landing as an isolated,
    context-free request.

    Excludes the current/latest message by default, since callers already
    extract that separately as their primary input -- passing it again here
    would just duplicate it in the prompt. Returns "" for an empty/single-
    message history, so callers can safely omit an empty context block.
    """
    tail = messages[:-1] if exclude_last and messages else list(messages)
    tail = tail[-(n * 2):]
    lines = []
    for m in tail:
        if isinstance(m, HumanMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            lines.append(f"User: {content[:300]}")
        elif isinstance(m, AIMessage):
            lines.append(f"Assistant: {str(m.content)[:300]}")
    return "\n".join(lines)
