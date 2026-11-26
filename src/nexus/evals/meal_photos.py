"""Scoring the meal photo flow against weighed meals (see ``meals/README.md``).

The model names items and portions; this turns them into a kcal range with the same code as a
logged meal, then compares the range with the weighed reference: MAPE of the point value, and
coverage (the share of references inside the range). No photos yet: it says so and succeeds.
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from nexus.agent.meal_reader import LlmMealReader, MealDraft, MealReader
from nexus.domain.nutrition import (
    EstimateKind,
    Food,
    make_item,
    meal_totals,
    portion_grams,
    search,
)
from nexus.infra.foods import load_foods

MEALS = Path(__file__).parent / "meals"
NO_PHOTOS = "no photos yet"


@dataclass(frozen=True, slots=True)
class Reference:
    file: str
    items: tuple[str, ...]
    grams: tuple[float, ...]
    kcal_reference: float
    source: str


@dataclass(frozen=True, slots=True)
class Prediction:
    point: float
    low: float
    high: float
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Report:
    scored: int
    skipped: int
    mape: float | None  # a fraction, 0.25 is 25%
    coverage: float | None  # a fraction in 0..1

    def text(self) -> str:
        if not self.scored and not self.skipped:
            return NO_PHOTOS
        if self.mape is None or self.coverage is None:
            return f"0 photos scored, {self.skipped} skipped (item not in the food database)"
        return (
            f"{self.scored} photos scored ({self.skipped} skipped): "
            f"MAPE {self.mape:.1%}, coverage {self.coverage:.1%}"
        )


def load_manifest(directory: Path = MEALS) -> list[Reference]:
    """The entries of ``manifest.json``; a malformed one is a ``ValueError`` naming the entry."""
    data: Any = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("manifest.json must be a list of entries")
    found: list[Reference] = []
    for n, entry in enumerate(data):
        try:
            items = tuple(str(i) for i in entry["items"])
            grams = tuple(float(g) for g in entry["grams"])
            reference = float(entry["kcal_reference"])
            if len(items) != len(grams) or not items or reference <= 0:
                raise ValueError("items and grams must match, and kcal_reference be positive")
            found.append(
                Reference(str(entry["file"]), items, grams, reference, str(entry["source"]))
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"manifest entry {n}: {exc}") from exc
    return found


def predict(draft: MealDraft, foods: list[Food]) -> Prediction:
    """The kcal range for what the reader saw: each item's first database match, its estimated
    weight (or a known portion's), as a photo estimate. Items without a match or an amount are
    listed in ``unresolved``."""
    items = []
    unresolved: list[str] = []
    for seen in draft.items:
        found = search(foods, seen.name, limit=1)
        if not found:
            unresolved.append(seen.name)
            continue
        grams = Decimal(str(seen.grams_estimate)) if seen.grams_estimate else None
        if grams is None and seen.portion_text:
            matched = portion_grams(found[0], seen.portion_text)
            grams = matched[1] if matched else None
        if grams is None:
            unresolved.append(seen.name)
            continue
        label = seen.portion_text or f"{grams.normalize():f} g"
        items.append(
            make_item(found[0], grams, label, EstimateKind.ESTIMATED, cooking=seen.cooking.domain())
        )
    if not items:
        return Prediction(0.0, 0.0, 0.0, tuple(unresolved))
    totals = meal_totals(items)
    return Prediction(
        float(totals.point.kcal), float(totals.low.kcal), float(totals.high.kcal), tuple(unresolved)
    )


def score(pairs: list[tuple[Reference, Prediction]]) -> Report:
    """MAPE of the point kcal and coverage of the range, over the photos where every item was
    found; the others are counted as skipped."""
    usable = [(r, p) for r, p in pairs if not p.unresolved and p.point > 0]
    skipped = len(pairs) - len(usable)
    if not usable:
        return Report(0, skipped, None, None)
    errors = [abs(p.point - r.kcal_reference) / r.kcal_reference for r, p in usable]
    inside = [p.low <= r.kcal_reference <= p.high for r, p in usable]
    return Report(len(usable), skipped, sum(errors) / len(errors), sum(inside) / len(inside))


async def run(reader: MealReader, directory: Path = MEALS) -> Report:
    refs = load_manifest(directory)
    if not refs:
        return Report(0, 0, None, None)
    foods = load_foods()
    pairs: list[tuple[Reference, Prediction]] = []
    for ref in refs:
        image = await asyncio.to_thread((directory / ref.file).read_bytes)
        media = "image/png" if ref.file.lower().endswith(".png") else "image/jpeg"
        draft = await reader.read(image, media, None)
        pairs.append((ref, predict(draft, foods)))
    return score(pairs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the meal photo flow on weighed meals")
    parser.add_argument("--check", action="store_true", help="only validate the manifest")
    parser.add_argument("--model", default=os.environ.get("OPENROUTER_VISION_MODEL"))
    args = parser.parse_args(argv)
    refs = load_manifest()
    missing = [r.file for r in refs if not (MEALS / r.file).exists()]
    if missing:
        print(f"photos listed but not found in {MEALS}: {', '.join(missing)}", file=sys.stderr)
        return 1
    if args.check or not refs:
        print(f"{len(refs)} photos listed" if refs else NO_PHOTOS)
        return 0
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key or not args.model:
        print("set OPENROUTER_API_KEY and --model (or OPENROUTER_VISION_MODEL)", file=sys.stderr)
        return 1
    from nexus.evals.__main__ import openrouter_model

    reader = LlmMealReader(openrouter_model(args.model, key))
    print(asyncio.run(run(reader)).text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
