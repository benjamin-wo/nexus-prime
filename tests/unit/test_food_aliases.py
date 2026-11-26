"""Everyday names for the bundled USDA foods: the file is valid, loading merges it into the foods'
aliases without touching a nutrient, and a name ranks with exact names."""

import importlib.util
import json
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.nutrition import Food, FoodSource, Nutrients, search
from nexus.infra.foods import FOODS_DIR, load_aliases, load_foods, with_aliases

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_food_aliases.py"


def checker() -> Any:
    spec = importlib.util.spec_from_file_location("build_food_aliases", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def food(food_id: str, name: str, *aliases: str) -> Food:
    return Food(
        f"usda:{food_id}",
        FoodSource.USDA,
        name,
        aliases,
        Nutrients(D(100), D(1), D(1), D(1), None),
        (),
    )


def test_the_committed_file_passes_its_own_check() -> None:
    script = checker()
    text = (FOODS_DIR / "aliases.json").read_text(encoding="utf-8")
    ids = {f.id for f in load_foods() if f.source is FoodSource.USDA}
    assert script.check(text, ids) == []
    assert 150 <= len(set(json.loads(text).values())) <= 300


def test_the_check_finds_a_missing_id_a_duplicate_a_capital_and_a_dish() -> None:
    script = checker()
    ids = {"usda:1"}
    assert script.check('{"egg": "usda:2"}', ids)
    assert any("twice" in p for p in script.check('{"egg": "usda:1", "egg": "usda:1"}', ids))
    assert script.check('{"Egg": "usda:1"}', ids)
    assert any("dish" in p for p in script.check('{"chicken rice": "usda:1"}', ids))
    assert script.check('{"egg": "usda:1"}', ids) == []


def test_loading_adds_names_to_the_foods_and_changes_no_nutrient() -> None:
    aliases = load_aliases(FOODS_DIR / "aliases.json")
    by_id = {f.id: f for f in load_foods()}
    raw = {e["id"]: e for e in json.loads((FOODS_DIR / "usda.json").read_text(encoding="utf-8"))}
    assert "egg" in by_id["usda:173424"].aliases and "toast" in by_id["usda:174925"].aliases
    for name, food_id in aliases.items():
        assert name in by_id[food_id].aliases
        assert by_id[food_id].per_100g.kcal == D(str(raw[food_id]["kcal"]))
    assert "chicken rice" not in aliases and "laksa" not in aliases
    assert len(by_id) == len(raw)


def test_an_alias_to_a_missing_food_is_an_error() -> None:
    with pytest.raises(InvalidInput):
        with_aliases([food("1", "Egg, whole")], {"egg": "usda:2"})


def test_a_name_ranks_with_the_exact_names_whatever_the_foods_name_is() -> None:
    long = replace(food("1", "Egg, whole, cooked, hard-boiled"), aliases=("egg",))
    short = food("2", "Egg tart")
    found = search([short, long, food("3", "Egg, white, dried")], "egg")
    assert found[0].id == "usda:1"
