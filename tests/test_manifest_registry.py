import pytest
import yaml

from capabilities.registry import (
    derived_managers,
    load_manifest,
    load_registry,
    demo_add_manager,
)


def _write_manifest(path, overrides=None):
    data = {
        "id": path.stem,
        "description": "A temporary capability for testing.",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {}},
        "side_effect": "read",
        "tags": ["test"],
        "managers": ["life"],
        "preconditions": [],
        "cost_hint": "low",
    }
    if overrides:
        data.update(overrides)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_c1_probe1_four_manifests_complete():
    registry = load_registry()
    for cap in ("email", "expenses", "routes", "recipes"):
        m = registry[cap]
        assert m.id == cap
        assert m.description
        assert m.input_schema
        assert m.output_schema
        assert m.side_effect in {"read", "write", "spend", "irreversible"}
        assert m.tags
        assert "preconditions" in m.__dataclass_fields__
        assert m.cost_hint in {"low", "medium", "high"}


def test_c1_probe3_no_class_names_or_module_paths():
    registry = load_registry()
    forbidden = ["class ", ".py", "capabilities/", "orchestrator/", "core/", "app/"]
    for m in registry.values():
        blob = m.description + " " + str(m.input_schema) + " " + str(m.output_schema)
        assert not any(f in blob for f in forbidden), m.id


def test_c1_probe4_adding_manager_home_is_data_only(tmp_path):
    manifest = tmp_path / "demo.yaml"
    _write_manifest(manifest)
    managers = demo_add_manager("home", manifest)
    assert "home" in managers
    # No enum/class/node change is involved; the derived set is recomputed from data.
    assert isinstance(managers, tuple)


def test_c1_probe5_life_finance_accepted_without_arbitration(tmp_path):
    manifest = tmp_path / "dual.yaml"
    _write_manifest(manifest, {"managers": ["life", "finance"]})
    loaded = load_manifest(manifest)
    assert loaded.managers == ("life", "finance")
    assert "life" in derived_managers([loaded])
    assert "finance" in derived_managers([loaded])


def test_c1_probe6_unknown_tag_warns_at_load(tmp_path):
    manifest = tmp_path / "typo.yaml"
    _write_manifest(manifest, {"tags": ["calandar"]})
    with pytest.warns(UserWarning, match="calandar"):
        load_manifest(manifest)


def test_load_registry_is_admin_gating():
    admin_reg = load_registry(is_admin=True)
    assert "whiteboard" in admin_reg

    friend_reg = load_registry(is_admin=False)
    assert "whiteboard" not in friend_reg
    assert "expenses" in friend_reg
    assert "reminders" in friend_reg

