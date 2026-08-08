import json
from pathlib import Path

from orchestrator.promotion import promote_draft, rollback, validate_draft

C7_DIR = Path(__file__).resolve().parent.parent / "gauntlet" / "c7"


def test_c7_probe1_malicious_draft_blocked_before_approval_asked(tmp_path):
    draft = json.loads((C7_DIR / "draft-malicious.json").read_text())
    result = promote_draft(draft, approval="owner-approval", manifest_dir=tmp_path / "m", lock_path=tmp_path / "lock.json")
    assert result["status"] == "blocked"
    assert result["approval_asked"] is False
    assert result["manifest_written"] is False
    assert any("credential vault" in r for r in result["reasons"])
    assert not (tmp_path / "m" / "evil_helper.yaml").exists()


def test_c7_probe2_provenance_in_skills_lock(tmp_path):
    draft = json.loads((C7_DIR / "draft-good.json").read_text())
    lock = tmp_path / "lock.json"
    result = promote_draft(
        draft, approval="reviewer-1", manifest_dir=tmp_path / "m", lock_path=lock, source_gap_id="gap-42"
    )
    assert result["status"] == "promoted"
    lock_data = json.loads(lock.read_text())
    entry = lock_data["promoted_capabilities"]["budget"]
    assert entry["sha256"] == result["sha256"]
    assert entry["source_gap_id"] == "gap-42"
    assert entry["promoted_at"]
    assert entry["status"] == "promoted"


def test_c7_probe3_rollback_restores_previous_content(tmp_path):
    draft = json.loads((C7_DIR / "draft-good.json").read_text())
    lock = tmp_path / "lock.json"
    manifest_dir = tmp_path / "m"
    manifest_dir.mkdir()
    # v1
    promote_draft(draft, approval="a", manifest_dir=manifest_dir, lock_path=lock)
    v1 = (manifest_dir / "budget.yaml").read_text()
    # v2
    draft2 = dict(draft, description="Changed description for the second version.")
    promote_draft(draft2, approval="a", manifest_dir=manifest_dir, lock_path=lock)
    assert (manifest_dir / "budget.yaml").read_text() != v1
    result = rollback("budget", manifest_dir=manifest_dir, lock_path=lock)
    assert result["status"] == "rolled_back"
    assert (manifest_dir / "budget.yaml").read_text() == v1
    lock_data = json.loads(lock.read_text())
    assert lock_data["promoted_capabilities"]["budget"]["status"] == "rolled_back"


def test_c7_probe4_approval_mandatory(tmp_path):
    draft = json.loads((C7_DIR / "draft-good.json").read_text())
    manifest_dir = tmp_path / "m"
    lock = tmp_path / "lock.json"
    pending = promote_draft(draft, approval=None, manifest_dir=manifest_dir, lock_path=lock)
    assert pending["status"] == "awaiting_approval"
    assert pending["manifest_written"] is False
    assert not (manifest_dir / "budget.yaml").exists()
    promoted = promote_draft(draft, approval="owner", manifest_dir=manifest_dir, lock_path=lock)
    assert promoted["status"] == "promoted"
    assert (manifest_dir / "budget.yaml").exists()
