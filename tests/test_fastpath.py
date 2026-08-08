from capabilities.registry import load_registry
from capabilities.retrieval import BM25Index
from orchestrator.fastpath import should_take_fast_path


def _retrieval(message: str):
    return BM25Index(list(load_registry().values())).retrieve_with_recovery(message, k=5)


def test_c4_probe3_fast_path_allowed_for_next_bus():
    ok, skipped = should_take_fast_path("when's my next bus?", load_registry(), _retrieval("when's my next bus?"))
    assert ok is True
    assert "llm planner" in skipped
    assert "hitl review" in skipped


def test_c4_probe3_spend_request_excluded():
    ok, skipped = should_take_fast_path("transfer $100 to Alice", load_registry(), _retrieval("transfer $100 to Alice"))
    assert ok is False
    assert any("insufficiency" in s for s in skipped)


def test_c4_probe3_cross_capability_request_excluded():
    ok, skipped = should_take_fast_path(
        "check my email and remind me about the bill",
        load_registry(),
        _retrieval("check my email and remind me about the bill"),
    )
    assert ok is False
    assert any("multi-capability" in s for s in skipped)
