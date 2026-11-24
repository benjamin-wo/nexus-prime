"""Validate ``src/nexus/infra/foods/aliases.json``: everyday names for foods already in the
bundled USDA data ("egg", "toast", "kopi o"), so a search for what people say finds the plain food.

The file is hand-curated; this script only checks it (and, without ``--check``, rewrites it
sorted and formatted). It never adds or changes a nutrient value: an alias is a name pointing at
an existing ``usda:<fdc_id>``, and ``load_foods`` merges the names into that food's aliases.

How to choose the food for a name (the rule):

* The plain food, cooked the way it is typically eaten: rice is cooked white rice, chicken breast
  is roasted without skin, a boiled vegetable is "boiled, drained, without salt", "toast" is
  toasted white bread, "egg" is hard-boiled.
* The generic USDA entry (SR Legacy ids, 16xxxx to 17xxxx), never a brand, restaurant chain or
  a "with salt" or "fortified" variant when a plain one exists.
* A name the USDA data has no sensible food for is left out (kangkong, kopi or teh with
  condensed milk, pomelo). A closer-but-different food is not a stand-in.
* Composite hawker or restaurant dishes (chicken rice, laksa, nasi lemak...) are never aliased
  to one ingredient: they stay unresolved until a dish database (SG FoodID) is loaded. This
  script refuses the words in ``DISHES``.

Checks: every id exists in ``usda.json``; every name is lowercase, trimmed and has a letter;
no name appears twice (JSON loaders silently keep the last, so the raw text is scanned); no
name is a dish.

    python3 -I scripts/build_food_aliases.py --check   # exit 1 if the file is invalid
    python3 -I scripts/build_food_aliases.py           # validate, then rewrite it sorted

Standard library only.
"""

import argparse
import json
import sys
from pathlib import Path

FOODS = Path(__file__).resolve().parent.parent / "src/nexus/infra/foods"
ALIASES = FOODS / "aliases.json"
USDA = FOODS / "usda.json"

# Names of composite dishes: never an alias of a single food.
DISHES = (
    "chicken rice", "laksa", "nasi lemak", "char kway teow", "mee goreng", "mee rebus",
    "mee siam", "hokkien mee", "bak chor mee", "bak kut teh", "roti prata", "prata",
    "rojak", "satay", "wanton mee", "wonton mee", "carrot cake", "chwee kueh", "congee",
    "porridge", "fried rice", "nasi goreng", "nasi padang", "briyani", "biryani", "curry",
    "rendang", "pho", "ramen", "pizza", "burger", "sandwich", "kaya toast", "sushi",
    "lor mak", "popiah", "ice kacang", "chendol", "cendol", "kueh", "dim sum",
)  # fmt: skip


def check(text: str, ids: set[str]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        for key, _ in items:
            if key in seen:
                problems.append(f"{key!r}: appears twice")
            seen.add(key)
        return dict(items)

    data = json.loads(text, object_pairs_hook=pairs)
    if not isinstance(data, dict):
        return ["the file must be an object of name to food id"]
    for name, food_id in data.items():
        if name != name.strip().lower() or " " * 2 in name:
            problems.append(f"{name!r}: must be lowercase, trimmed, single-spaced")
        if not any(c.isalpha() for c in name):
            problems.append(f"{name!r}: has no letters")
        if not isinstance(food_id, str) or food_id not in ids:
            problems.append(f"{name!r}: {food_id!r} is not a food in usda.json")
        for dish in DISHES:
            if f" {dish} " in f" {name} ":
                problems.append(f"{name!r}: a dish ({dish!r}), not a single food")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="validate only; never write")
    args = parser.parse_args()
    ids = {entry["id"] for entry in json.loads(USDA.read_text(encoding="utf-8"))}
    text = ALIASES.read_text(encoding="utf-8")
    problems = check(text, ids)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    data: dict[str, str] = json.loads(text)
    body = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in sorted(data.items()))
    formatted = "{\n" + body + "\n}\n"
    if args.check:
        if text != formatted:
            print("aliases.json is not sorted and formatted: run without --check", file=sys.stderr)
            return 1
    else:
        ALIASES.write_text(formatted, encoding="utf-8")
    print(f"ok: {len(data)} names for {len(set(data.values()))} foods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
