"""Manifest-first capability registry.

Managers are derived from manifest data and declared nowhere else: no manager
enum, no manager class, no manager node. This module owns the manifest schema,
loading, validation, and the derived manager set.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"
TAG_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "tag-policy.yaml"

SIDE_EFFECTS = {"read", "write", "spend", "irreversible"}
FORBIDDEN_PATTERNS = [
    (r"\bclass\s+[A-Za-z_]", "class-name"),
    (r"\.py\b", "module-path"),
    (r"(?:capabilities|orchestrator|core|app)/", "module-path"),
]


@dataclass(frozen=True)
class Manifest:
    id: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    side_effect: str
    tags: tuple[str, ...]
    managers: tuple[str, ...]
    preconditions: tuple[str, ...]
    cost_hint: str
    source: str

    @property
    def retrieval_text(self) -> str:
        """Everything a retrieval system may read. No keywords beyond manifest data."""
        parts = [self.description, "tags: " + ", ".join(self.tags)]
        return "\n".join(parts)


def _validate_text(text: str, manifest_id: str) -> None:
    for pattern, kind in FORBIDDEN_PATTERNS:
        if re.search(pattern, text):
            raise ValueError(
                f"manifest {manifest_id!r} contains forbidden {kind} content: {pattern!r}"
            )


def load_manifest(path: Path, allowed_tags: set[str] | None = None) -> Manifest:
    if allowed_tags is None:
        allowed_tags = load_allowed_tags()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    manifest_id = str(data.get("id") or path.stem).strip()
    description = str(data.get("description") or "").strip()
    if not description:
        raise ValueError(f"manifest {manifest_id!r} is missing description")

    _validate_text(description, manifest_id)
    for key in ("input_schema", "output_schema"):
        _validate_text(str(data.get(key) or ""), manifest_id)

    side_effect = str(data.get("side_effect") or "").strip()
    if side_effect not in SIDE_EFFECTS:
        raise ValueError(
            f"manifest {manifest_id!r} has invalid side_effect {side_effect!r}; "
            f"expected one of {sorted(SIDE_EFFECTS)}"
        )

    tags = tuple(str(t).strip() for t in (data.get("tags") or []))
    managers = tuple(str(t).strip() for t in (data.get("managers") or []))
    preconditions = tuple(str(t).strip() for t in (data.get("preconditions") or []))
    cost_hint = str(data.get("cost_hint") or "medium").strip()
    if cost_hint not in {"low", "medium", "high"}:
        raise ValueError(f"manifest {manifest_id!r} has invalid cost_hint {cost_hint!r}")

    if allowed_tags is not None:
        for tag in tags:
            if tag not in allowed_tags:
                warnings.warn(
                    f"manifest {manifest_id!r} uses tag {tag!r} which is not in "
                    "config/tag-policy.yaml allowed_tags (advisory)",
                    stacklevel=2,
                )

    return Manifest(
        id=manifest_id,
        description=description,
        input_schema=dict(data.get("input_schema") or {}),
        output_schema=dict(data.get("output_schema") or {}),
        side_effect=side_effect,
        tags=tags,
        managers=managers,
        preconditions=preconditions,
        cost_hint=cost_hint,
        source=str(path),
    )


def load_allowed_tags() -> set[str]:
    data = yaml.safe_load(TAG_POLICY_PATH.read_text(encoding="utf-8")) or {}
    return set(data.get("allowed_tags") or [])


def load_manifests(
    manifest_dir: Path | None = None,
    extra_manifests: Iterable[Path] | None = None,
) -> list[Manifest]:
    manifest_dir = manifest_dir or MANIFEST_DIR
    allowed = load_allowed_tags()
    paths = sorted(manifest_dir.glob("*.yaml")) + sorted(manifest_dir.glob("*.yml"))
    paths += [Path(p) for p in (extra_manifests or [])]
    return [load_manifest(p, allowed_tags=allowed) for p in paths]


def load_registry(
    manifest_dir: Path | None = None,
    extra_manifests: Iterable[Path] | None = None,
) -> dict[str, Manifest]:
    return {m.id: m for m in load_manifests(manifest_dir, extra_manifests)}


def derived_managers(manifests: Iterable[Manifest]) -> tuple[str, ...]:
    """The manager set is derived from manifests; declared nowhere else."""
    seen: list[str] = []
    for manifest in manifests:
        for manager in manifest.managers:
            if manager not in seen:
                seen.append(manager)
    return tuple(seen)


def demo_add_manager(manager: str, manifest_path: Path) -> tuple[str, ...]:
    """Data-only demo: append a manager tag to one manifest and show the derived set."""
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    managers = list(data.get("managers") or [])
    if manager not in managers:
        managers.append(manager)
    data["managers"] = managers
    scratch = manifest_path.with_suffix(".demo.yaml")
    scratch.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    manifests = load_manifests(extra_manifests=[scratch])
    result = derived_managers(manifests)
    scratch.unlink(missing_ok=True)
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "demo-add-manager":
        managers = demo_add_manager(sys.argv[2], Path(sys.argv[3]))
        print("derived managers:", ", ".join(managers))
    else:
        reg = load_registry()
        print("manifests:", ", ".join(sorted(reg)))
        print("derived managers:", ", ".join(derived_managers(reg.values())))
