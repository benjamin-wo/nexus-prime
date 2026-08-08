import pytest

from capabilities.registry import Manifest, load_registry
from capabilities.retrieval import BM25Index
from capabilities.synthetic_registry import build_synthetic_manifests


def _manifest(mid: str, description: str) -> Manifest:
    return Manifest(
        id=mid,
        description=description,
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        side_effect="read",
        tags=(),
        managers=(),
        preconditions=(),
        cost_hint="low",
        source="test",
    )


def test_c2_probe2_rank9_triggers_recovery_not_wrong_execution():
    real = load_registry()
    email = real["email"]
    # 8 synthetic manifests tie for first with identical high-scoring text.
    syn = [
        _manifest(f"tie_{i:02d}", "zzq zzq zzq zzq zzq zzq zzq zzq")
        for i in range(8)
    ]
    filler = [_manifest(f"f_{i:02d}", "totally unrelated vocabulary here") for i in range(12)]
    index = BM25Index(syn + [email] + filler)

    result = index.retrieve_with_recovery("zzq zzq zzq zzq zzq zzq", k=5)
    top_ids = [h.id for h in result.top]

    assert "email" not in top_ids  # true rank > 5
    assert all(h.score == result.top[0].score for h in result.top[:8])  # flat
    assert result.recovered is True
    assert "email" in [h.id for h in result.expanded]
    # Recovery means the caller re-plans; no wrong execution is committed.
    assert result.recovered and result.expanded


def test_retrieve_k5_returns_expected_shortlist():
    registry = load_registry()
    index = BM25Index(list(registry.values()) + build_synthetic_manifests())
    hits = index.retrieve("when is my next bus from Tampines", k=5)
    assert hits[0].id == "routes"
    assert len(hits) == 5
