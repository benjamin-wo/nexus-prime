"""Build ``src/nexus/infra/foods/usda.json`` from USDA FoodData Central (SR Legacy + Foundation).

Source: https://fdc.nal.usda.gov/download-datasets, two CSV zips at pinned releases:

* SR Legacy, April 2018: the final release of the Standard Reference series (no longer updated).
* Foundation Foods, 2026-10-29.

Licence, checked 2026-11-24 on https://fdc.nal.usda.gov/ ("Licensing"): "USDA FoodData Central
data are in the public domain and they are not copyrighted. They are published under CC0 1.0
Universal (CC0 1.0). No permission is needed for their use, but we request that users list
FoodData Central as the source of the data." The attribution is in ``NOTICE.md``. Suggested
citation: U.S. Department of Agriculture, Agricultural Research Service, Beltsville Human
Nutrition Research Center. FoodData Central. https://fdc.nal.usda.gov/

What is kept, per 100 g: energy (kcal), protein, carbohydrate, fat and fibre, and the common
portions (a household measure and its gram weight). A food missing energy, protein,
carbohydrate or fat is dropped, never filled in. Missing fibre stays missing (null). Energy is
nutrient 1008; Foundation Foods often has only Atwater energy, so 2048 (specific factors) and
then 2047 (general factors) are used when 1008 is absent. Carbohydrate is 1005 (by difference),
else 1050 (by summation), and a by-difference value between -2 and 0 g becomes 0; fibre is
1079, else 2033.

The downloaded zips are untrusted data: they are checked against a pinned SHA-256, read member
by member without extracting anything to disk, and parsed as text. Run the script in isolated
mode so nothing from the current directory is imported:

    python3 -I scripts/import_usda_fdc.py           # rewrite the file
    python3 -I scripts/import_usda_fdc.py --check   # exit 1 if the committed file differs

To update: change a ``Dataset`` below (URL, SHA-256 of the new zip, counts) and run the script.
Standard library only.
"""

import argparse
import csv
import hashlib
import io
import json
import sys
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

BASE = "https://fdc.nal.usda.gov/fdc-datasets/"
OUTPUT = Path(__file__).resolve().parent.parent / "src/nexus/infra/foods/usda.json"


@dataclass(frozen=True)
class Dataset:
    name: str
    zip_name: str
    sha256: str
    data_type: str  # the food.csv data_type to keep
    min_foods: int  # a sanity floor on the foods kept


DATASETS = (
    Dataset(
        "SR Legacy 2018-04",
        "FoodData_Central_sr_legacy_food_csv_2018-04.zip",
        "b80817294b8850530aaedf2e515c02593b1824f763a0ff356e5c2081643e6fd0",
        "sr_legacy_food",
        7000,
    ),
    Dataset(
        "Foundation Foods 2026-10-29",
        "FoodData_Central_foundation_food_csv_2026-10-29.zip",
        "c3158a5d1b758f56ef20ec76d93603d2bf872e739d51f5f3079e3ef46181351a",
        "foundation_food",
        300,
    ),
)

ENERGY = ("1008", "2048", "2047")  # kcal; first one present wins
PROTEIN = ("1003",)
FAT = ("1004",)
CARBS = ("1005", "1050")
FIBRE = ("1079", "2033")
WANTED = frozenset((*ENERGY, *PROTEIN, *FAT, *CARBS, *FIBRE))
MAX_KCAL_PER_100G = Decimal(910)  # pure fat is about 884
MAX_GRAMS_PER_100G = Decimal(100)
NEGATIVE_CARBS_TOLERANCE = Decimal(2)  # g per 100 g; carbohydrate by difference, rounded to 0
UNDETERMINED = "undetermined"  # measure_unit.csv's name for "no unit"
CSV_FIELD_LIMIT = 1 << 20


class SourceError(Exception):
    pass


def _rows(archive: zipfile.ZipFile, name: str) -> Any:
    """Rows of one CSV in the zip, found by its file name wherever it sits."""
    matches = [n for n in archive.namelist() if n.rsplit("/", 1)[-1] == name]
    if len(matches) != 1:
        raise SourceError(f"expected exactly one {name} in the zip, found {len(matches)}")
    with archive.open(matches[0]) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def _decimal(value: str, what: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise SourceError(f"{what}: {value!r} is not a number") from exc
    if not number.is_finite():
        raise SourceError(f"{what}: {value!r} is not finite")
    return number


def _number(value: Decimal) -> float:
    return float(round(value, 2))


def _first(values: dict[str, Decimal], ids: tuple[str, ...]) -> Decimal | None:
    for nutrient_id in ids:
        if nutrient_id in values:
            return values[nutrient_id]
    return None


def _quantity(amount: Decimal) -> str:
    return str(int(amount)) if amount == amount.to_integral_value() else f"{amount.normalize():f}"


def _portion_label(row: dict[str, str], units: dict[str, str]) -> str | None:
    amount = _decimal(row["amount"] or "1", "portion amount")
    unit = units.get(row["measure_unit_id"], UNDETERMINED)
    parts = [
        _quantity(amount),
        "" if unit == UNDETERMINED else unit,
        row["portion_description"].strip(),
        row["modifier"].strip(),
    ]
    label = " ".join(" ".join(p for p in parts if p).split())
    return label or None


def read_dataset(path: Path, dataset: Dataset) -> list[dict[str, Any]]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != dataset.sha256:
        raise SourceError(f"{dataset.zip_name}: SHA-256 is {digest}, expected {dataset.sha256}")
    with zipfile.ZipFile(path) as archive:
        names = {
            r["fdc_id"]: " ".join(r["description"].split())
            for r in _rows(archive, "food.csv")
            if r["data_type"] == dataset.data_type
        }
        nutrients = defaultdict(dict)
        for r in _rows(archive, "food_nutrient.csv"):
            if r["nutrient_id"] in WANTED and r["fdc_id"] in names and r["amount"]:
                nutrients[r["fdc_id"]][r["nutrient_id"]] = _decimal(r["amount"], "nutrient amount")
        units = {r["id"]: r["name"].strip() for r in _rows(archive, "measure_unit.csv")}
        portions = defaultdict(dict)  # fdc id -> label -> grams, so repeats collapse
        for r in _rows(archive, "food_portion.csv"):
            if r["fdc_id"] not in names or not r["gram_weight"]:
                continue
            grams = _decimal(r["gram_weight"], "portion grams")
            label = _portion_label(r, units)
            if label is not None and grams > 0:
                portions[r["fdc_id"]].setdefault(label, grams)
    foods = []
    for fdc_id, name in names.items():
        found = nutrients.get(fdc_id, {})
        kcal, protein = _first(found, ENERGY), _first(found, PROTEIN)
        carbs, fat = _first(found, CARBS), _first(found, FAT)
        if kcal is None or protein is None or carbs is None or fat is None or not name:
            continue
        if -NEGATIVE_CARBS_TOLERANCE <= carbs < 0:
            carbs = Decimal(0)  # "by difference" can come out a hair below zero
        fibre = _first(found, FIBRE)
        values = [v for v in (protein, carbs, fat, fibre) if v is not None]
        if not 0 <= kcal <= MAX_KCAL_PER_100G or any(
            not 0 <= v <= MAX_GRAMS_PER_100G for v in values
        ):
            raise SourceError(f"fdc {fdc_id} ({name}): implausible values {found}")
        foods.append(
            {
                "id": f"usda:{fdc_id}",
                "source": "usda",
                "name": name,
                "aliases": [],
                "kcal": _number(kcal),
                "protein_g": _number(protein),
                "carbs_g": _number(carbs),
                "fat_g": _number(fat),
                "fibre_g": None if fibre is None else _number(fibre),
                "portions": [
                    {"label": label, "grams": _number(grams)}
                    for label, grams in sorted(portions.get(fdc_id, {}).items())
                ],
            }
        )
    if len(foods) < dataset.min_foods:
        raise SourceError(f"{dataset.name}: only {len(foods)} foods; expected {dataset.min_foods}+")
    return foods


def build(paths: dict[str, Path]) -> list[dict[str, Any]]:
    foods = [f for d in DATASETS for f in read_dataset(paths[d.zip_name], d)]
    ids = [f["id"] for f in foods]
    if len(set(ids)) != len(ids):
        raise SourceError("duplicate food ids across datasets")
    return sorted(foods, key=lambda f: int(f["id"].split(":", 1)[1]))


def render(foods: list[dict[str, Any]]) -> str:
    """One food per line, keys sorted: small, and a change shows as a line in a diff."""
    lines = (
        json.dumps(f, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for f in foods
    )
    return "[\n" + ",\n".join(lines) + "\n]\n"


def download(into: Path) -> dict[str, Path]:
    paths = {}
    for dataset in DATASETS:
        target = into / dataset.zip_name
        url = BASE + dataset.zip_name  # an https constant
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
            target.write_bytes(response.read())
        paths[dataset.zip_name] = target
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="fail if the file would change")
    parser.add_argument(
        "--from-dir", type=Path, help="use the zips already in this directory instead of fetching"
    )
    args = parser.parse_args(argv)
    csv.field_size_limit(CSV_FIELD_LIMIT)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            paths = (
                {d.zip_name: args.from_dir / d.zip_name for d in DATASETS}
                if args.from_dir
                else download(Path(tmp))
            )
            foods = build(paths)
    except (SourceError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    wanted = render(foods)
    have = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    if args.check:
        if have != wanted:
            print(f"{OUTPUT} is out of date: run scripts/import_usda_fdc.py", file=sys.stderr)
            return 1
        print("usda.json is up to date")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(wanted, encoding="utf-8")
    size = len(wanted.encode("utf-8"))
    print(f"wrote {OUTPUT}: {len(foods)} foods, {size / 1_000_000:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
