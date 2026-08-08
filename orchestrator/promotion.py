"""Gap -> draft -> approval promotion pipeline with provenance and rollback.

Security model: validation is the gate. Approval is the human decision on an
already-validated draft; a blocked draft never reaches the approval step.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = ROOT / "capabilities" / "manifests"
SKILLS_LOCK = ROOT / "skills-lock.json"

MALICIOUS_PATTERNS = [
    (r"core\.vault", "credential vault reference"),
    (r"\bvault\b", "credential vault reference"),
    (r"\bimport os\b", "system module"),
    (r"\bimport subprocess\b", "process execution"),
    (r"\beval\s*\(", "dynamic code execution"),
    (r"\bexec\s*\(", "dynamic code execution"),
    (r"__import__", "dynamic import"),
    (r"\bsocket\b", "network access"),
    (r"\brequests\b", "network access"),
    (r"\bhttpx\b", "network access"),
    (r"\burllib\b", "network access"),
    (r"rm\s+-rf", "destructive command"),
    (r"\.\./", "path traversal"),
    (r"api[_-]?key\s*=", "secret embedding"),
    (r"secret\s*=", "secret embedding"),
    (r"token\s*=", "secret embedding"),
]


def draft_sha256(draft: dict[str, Any]) -> str:
    canonical = json.dumps(draft, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Validate a draft. Returns {'status': 'valid'|'blocked', 'reasons': [...]}."""
    reasons: list[str] = []
    cap_id = str(draft.get("id") or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", cap_id):
        reasons.append("id must be lowercase snake_case")

    blob = json.dumps(draft, ensure_ascii=False).lower()
    for pattern, label in MALICIOUS_PATTERNS:
        if re.search(pattern, blob):
            reasons.append(f"malicious pattern: {label}")

    side_effect = draft.get("side_effect")
    if side_effect not in {"read", "write", "spend", "irreversible"}:
        reasons.append("invalid side_effect")
    if side_effect in {"spend", "irreversible"} and not draft.get("requires_human"):
        reasons.append("spend/irreversible drafts must declare requires_human=true")

    # Structural schema check through the locked manifest loader.
    if not reasons:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{cap_id}.yaml"
                path.write_text(yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
                from capabilities.registry import load_manifest

                load_manifest(path)
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"manifest schema invalid: {exc}")

    if reasons:
        return {"status": "blocked", "reasons": reasons}
    return {"status": "valid", "reasons": []}


def _load_lock(lock_path: Path) -> dict[str, Any]:
    if lock_path.exists():
        return json.loads(lock_path.read_text(encoding="utf-8"))
    return {"version": 1, "skills": {}, "promoted_capabilities": {}}


def _write_lock(lock_path: Path, lock: dict[str, Any]) -> None:
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def promote_draft(
    draft: dict[str, Any],
    approval: Optional[str] = None,
    manifest_dir: Path | None = None,
    lock_path: Path | None = None,
    source_gap_id: str = "gap-record",
) -> dict[str, Any]:
    """Validate, then require approval, then promote. Blocked drafts never ask."""
    manifest_dir = manifest_dir or MANIFEST_DIR
    lock_path = lock_path or SKILLS_LOCK
    validation = validate_draft(draft)
    if validation["status"] == "blocked":
        return {
            "status": "blocked",
            "reasons": validation["reasons"],
            "approval_asked": False,
            "manifest_written": False,
        }
    if not approval:
        return {
            "status": "awaiting_approval",
            "approval_asked": True,
            "manifest_written": False,
            "draft_sha256": draft_sha256(draft),
        }

    cap_id = str(draft["id"])
    manifest_dir.mkdir(parents=True, exist_ok=True)
    yaml_text = yaml.safe_dump(draft, sort_keys=False)
    manifest_path = manifest_dir / f"{cap_id}.yaml"
    lock = _load_lock(lock_path)
    promoted = lock.setdefault("promoted_capabilities", {})
    previous = promoted.get(cap_id, {}).get("content")
    entry = {
        "source_gap_id": source_gap_id,
        "sha256": draft_sha256(draft),
        "content": base64.b64encode(yaml_text.encode("utf-8")).decode("ascii"),
        "previous_content": previous,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": approval,
        "status": "promoted",
    }
    promoted[cap_id] = entry
    manifest_path.write_text(yaml_text, encoding="utf-8")
    _write_lock(lock_path, lock)
    return {
        "status": "promoted",
        "manifest_written": True,
        "manifest_path": str(manifest_path),
        "sha256": entry["sha256"],
    }


def rollback(
    capability_id: str,
    manifest_dir: Path | None = None,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    manifest_dir = manifest_dir or MANIFEST_DIR
    lock_path = lock_path or SKILLS_LOCK
    lock = _load_lock(lock_path)
    promoted = lock.get("promoted_capabilities", {})
    entry = promoted.get(capability_id)
    if not entry:
        return {"status": "no_entry", "message": f"no promotion record for {capability_id}"}
    manifest_path = manifest_dir / f"{capability_id}.yaml"
    previous = entry.get("previous_content")
    if previous:
        manifest_path.write_text(
            base64.b64decode(previous).decode("utf-8"), encoding="utf-8"
        )
    else:
        manifest_path.unlink(missing_ok=True)
    entry["status"] = "rolled_back"
    entry["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    _write_lock(lock_path, lock)
    return {"status": "rolled_back", "restored_previous": previous is not None}


def _cli() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command == "validate" and len(sys.argv) >= 3:
        draft = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(validate_draft(draft), indent=2))
        sys.exit(0 if validate_draft(draft)["status"] == "valid" else 1)
    if command == "promote" and len(sys.argv) >= 3:
        draft = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        approval = None
        if "--approval" in sys.argv:
            approval = sys.argv[sys.argv.index("--approval") + 1]
        print(json.dumps(promote_draft(draft, approval=approval), indent=2))
        return
    if command == "rollback" and len(sys.argv) >= 3:
        print(json.dumps(rollback(sys.argv[2]), indent=2))
        return
    print("usage: python -m orchestrator.promotion validate|promote|rollback ...")


if __name__ == "__main__":
    _cli()
