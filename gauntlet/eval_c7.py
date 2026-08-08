"""C7 probe traces."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from orchestrator.promotion import promote_draft, rollback, validate_draft

ROOT = Path(__file__).resolve().parent


def main() -> None:
    good = json.loads((ROOT / "c7" / "draft-good.json").read_text())
    malicious = json.loads((ROOT / "c7" / "draft-malicious.json").read_text())
    traces = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        lock = tmp_path / "skills-lock.json"

        blocked = promote_draft(malicious, approval="owner", manifest_dir=manifest_dir, lock_path=lock)
        traces.append(
            {
                "probe": 1,
                "input_draft": malicious["id"],
                "validation": validate_draft(malicious),
                "promotion": {k: blocked[k] for k in ("status", "approval_asked", "manifest_written")},
                "checks": {"blocked": blocked["status"] == "blocked", "approval_not_asked": blocked["approval_asked"] is False},
            }
        )

        promote_draft(good, approval="owner", manifest_dir=manifest_dir, lock_path=lock, source_gap_id="c3-probe1-budget")
        lock_data = json.loads(lock.read_text())
        entry = lock_data["promoted_capabilities"]["budget"]
        traces.append(
            {
                "probe": 2,
                "input_draft": good["id"],
                "lock_entry": {
                    "sha256": entry["sha256"],
                    "source_gap_id": entry["source_gap_id"],
                    "promoted_at": entry["promoted_at"],
                    "status": entry["status"],
                },
                "checks": {"sha256_present": bool(entry["sha256"]), "gap_id_present": bool(entry["source_gap_id"]), "timestamp_present": bool(entry["promoted_at"])},
            }
        )

        v1 = (manifest_dir / "budget.yaml").read_text()
        promote_draft(dict(good, description="v2 description"), approval="owner", manifest_dir=manifest_dir, lock_path=lock)
        rollback_result = rollback("budget", manifest_dir=manifest_dir, lock_path=lock)
        traces.append(
            {
                "probe": 3,
                "input_draft": good["id"],
                "v1_sha": json.loads(lock.read_text())["promoted_capabilities"]["budget"]["sha256"],
                "rollback": rollback_result,
                "checks": {"rolled_back": rollback_result["status"] == "rolled_back", "content_restored": (manifest_dir / "budget.yaml").read_text() == v1},
            }
        )

        pending = promote_draft(good, approval=None, manifest_dir=manifest_dir, lock_path=lock)
        traces.append(
            {
                "probe": 4,
                "input_draft": good["id"],
                "without_approval": {"status": pending["status"], "manifest_written": pending["manifest_written"]},
                "checks": {"awaiting": pending["status"] == "awaiting_approval", "nothing_written": pending["manifest_written"] is False},
            }
        )

    out = ROOT / "c7" / "probe-traces.jsonl"
    out.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces), encoding="utf-8")
    for t in traces:
        print(t["probe"], t["checks"])


if __name__ == "__main__":
    main()
