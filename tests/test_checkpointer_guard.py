"""The checkpoint-wedge guard: statement_timeout on checkpointer connections,
a bounded graph turn, and a checkpointer heal."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.main import app
from orchestrator.checkpointer import (
    CHECKPOINT_STATEMENT_TIMEOUT_MS,
    _with_statement_timeout,
    get_checkpointer,
    reset_checkpointer,
)

client = TestClient(app)


def test_statement_timeout_is_appended_to_conn_string():
    bounded = _with_statement_timeout("postgresql://u:p@h:5432/db", CHECKPOINT_STATEMENT_TIMEOUT_MS)
    assert f"options=-c%20statement_timeout%3D{CHECKPOINT_STATEMENT_TIMEOUT_MS}" in bounded

    # a conn_string that already has query params must get '&' not '?'
    bounded2 = _with_statement_timeout("postgresql://u:p@h:5432/db?sslmode=require", 30_000)
    assert "sslmode=require&options=-c" in bounded2


def test_reset_checkpointer_falls_back_and_recovers():
    """reset_checkpointer must always leave a working checkpointer behind --
    MemorySaver when Postgres is not configured (local/dev), PostgresSaver
    after a successful re-setup in production."""
    asyncio.run(reset_checkpointer())
    assert get_checkpointer() is not None


def test_hung_graph_turn_returns_honest_fallback(monkeypatch):
    """Live incident (chat=149917165, 'Hi'): a wedged checkpoint layer hung
    the turn forever -- no error, no reply, and the held lock starved every
    later message. The graph invocation is now bounded; a hung turn produces
    an honest reply instead of silence."""
    import app.chat_api as chat_api
    from core.config import settings

    class _HangingGraph:
        async def ainvoke(self, state, config=None):
            await asyncio.sleep(30)

    monkeypatch.setattr(chat_api, "get_assistant_graph", lambda: _HangingGraph())
    monkeypatch.setattr(settings, "graph_turn_timeout_seconds", 0.2)

    resp = client.post(
        "/api/chat",
        json={"message": "hi", "session_id": "diag-hang-test", "user_id": 999999},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "took me way too long" in body["reply"]


def test_graph_turn_timeout_is_generous_not_zero():
    """The bound is an incident backstop, not a reasoning limit: default 600s
    so legitimate multi-tool turns (email sweeps, transit chains) survive."""
    from core.config import settings

    assert settings.graph_turn_timeout_seconds >= 300.0
