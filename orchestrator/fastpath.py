"""Fast-path gate: known, read-only, single-capability requests skip expensive stages."""

from __future__ import annotations

import re

from capabilities.registry import Manifest
from capabilities.retrieval import RetrievalResult
from orchestrator.planner import _candidate_selections, missing_policy

# Read-only single-capability patterns that are safe to fast-path. The pattern set is data
# (patterns in code are still code; documented here as the optimization gate's allowlist).
FAST_PATH_PATTERNS: dict[str, list[str]] = {
    "routes": [
        "next bus", "bus from", "bus to", "eta", "drive to", "route from",
        "fastest way", "how long is the drive",
    ],
}


def should_take_fast_path(
    text: str,
    registry: dict[str, Manifest],
    retrieval: RetrievalResult | None = None,
) -> tuple[bool, list[str]]:
    """Return (take_fast_path, stages_skipped)."""
    skipped: list[str] = []
    lowered = text.strip().lower()

    missing = missing_policy(lowered)
    if missing:
        return False, ["insufficiency analysis required"]

    candidates = _candidate_selections(lowered, missing)
    if len(candidates) != 1:
        if len(candidates) > 1:
            return False, ["multi-capability composition required"]
        return False, ["no unambiguous single capability"]

    cap = candidates[0].id
    manifest = registry.get(cap)
    if manifest is None:
        return False, ["capability not in manifest registry"]
    if manifest.side_effect != "read":
        return False, [f"{cap} is not read-only"]
    patterns = FAST_PATH_PATTERNS.get(cap, [])
    if not any(pattern in lowered for pattern in patterns):
        return False, ["request not in fast-path pattern set"]
    if retrieval is not None and (not retrieval.top or retrieval.top[0].id != cap):
        return False, ["retrieval top-1 disagrees with fast-path candidate"]
    if retrieval is not None and retrieval.recovered:
        return False, ["retrieval recovery pending"]

    return True, [
        "llm planner",
        "insufficiency analysis",
        "multi-capability composition",
        "hitl review",
    ]
