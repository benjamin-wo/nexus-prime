"""Build ``src/nexus/infra/exercises/catalogue.json`` from yuhonas/free-exercise-db.

Source: https://github.com/yuhonas/free-exercise-db (Unlicense, public domain), read at a
pinned commit so the output only changes when someone moves the pin. Standard library only.

    python scripts/import_free_exercise_db.py           # rewrite the catalogue
    python scripts/import_free_exercise_db.py --check   # exit 1 if the committed file differs

To update: set ``COMMIT`` to a newer commit (``gh api repos/yuhonas/free-exercise-db/commits/main
--jq .sha``), run the script, and also change the default of ``EXERCISE_IMAGE_BASE_URL`` in
``nexus/settings.py`` so image links match the data.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

# Pinned: 2026-11-24 main.
COMMIT = "f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5"
SOURCE = f"https://raw.githubusercontent.com/yuhonas/free-exercise-db/{COMMIT}/dist/exercises.json"
OUTPUT = Path(__file__).resolve().parent.parent / "src/nexus/infra/exercises/catalogue.json"
MIN_EXERCISES = 800

MUSCLES = frozenset(
    {
        "abdominals", "abductors", "adductors", "biceps", "calves", "chest", "forearms",
        "glutes", "hamstrings", "lats", "lower back", "middle back", "neck", "quadriceps",
        "shoulders", "traps", "triceps",
    }
)  # fmt: skip
EQUIPMENT = frozenset(
    {
        "bands", "barbell", "body only", "cable", "dumbbell", "e-z curl bar", "exercise ball",
        "foam roll", "kettlebells", "machine", "medicine ball", "other",
    }
)  # fmt: skip
LEVELS = frozenset({"beginner", "intermediate", "expert"})
CATEGORIES = frozenset(
    {
        "cardio", "olympic weightlifting", "plyometrics", "powerlifting", "strength",
        "stretching", "strongman",
    }
)  # fmt: skip
FORCES = frozenset({"pull", "push", "static"})
MECHANICS = frozenset({"compound", "isolation"})


class SourceError(Exception):
    pass


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourceError(f"{raw.get('id')!r}: {key} must be a non-empty string")
    return value.strip()


def _choice(
    raw: dict[str, Any], key: str, allowed: frozenset[str], *, optional: bool
) -> str | None:
    value = raw.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise SourceError(f"{raw.get('id')!r}: unknown {key} {value!r}")
    return value


def _strings(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SourceError(f"{raw.get('id')!r}: {key} must be a list of strings")
    return [v.strip() for v in value if v.strip()]


def _muscles(raw: dict[str, Any], key: str) -> list[str]:
    found = _strings(raw, key)
    unknown = sorted(set(found) - MUSCLES)
    if unknown:
        raise SourceError(f"{raw.get('id')!r}: unknown muscle(s) {unknown} in {key}")
    return list(dict.fromkeys(found))


def normalise(raw: dict[str, Any]) -> dict[str, Any]:
    exercise_id = _text(raw, "id")
    images = _strings(raw, "images")
    for image in images:
        folder, _, name = image.partition("/")
        if not folder or not name or ".." in image or image.startswith("/"):
            raise SourceError(f"{exercise_id!r}: odd image path {image!r}")
    primary = _muscles(raw, "primaryMuscles")
    if not primary:
        raise SourceError(f"{exercise_id!r}: no primary muscle")
    return {
        "id": exercise_id,
        "name": _text(raw, "name"),
        "category": _choice(raw, "category", CATEGORIES, optional=False),
        "level": _choice(raw, "level", LEVELS, optional=False),
        "equipment": _choice(raw, "equipment", EQUIPMENT, optional=True),
        "force": _choice(raw, "force", FORCES, optional=True),
        "mechanic": _choice(raw, "mechanic", MECHANICS, optional=True),
        "primary": primary,
        "secondary": _muscles(raw, "secondaryMuscles"),
        "instructions": _strings(raw, "instructions"),
        "images": images,
    }


def build(source: list[Any]) -> list[dict[str, Any]]:
    if not isinstance(source, list) or not all(isinstance(r, dict) for r in source):
        raise SourceError("expected a JSON list of objects")
    rows = sorted((normalise(r) for r in source), key=lambda r: str(r["id"]))
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise SourceError("duplicate exercise ids")
    if len(rows) < MIN_EXERCISES:
        raise SourceError(f"only {len(rows)} exercises; expected at least {MIN_EXERCISES}")
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=1, ensure_ascii=False) + "\n"


def download() -> list[Any]:
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        data: list[Any] = json.load(response)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="fail if the file would change")
    args = parser.parse_args(argv)
    try:
        wanted = render(build(download()))
    except (SourceError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    have = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    if args.check:
        if have != wanted:
            print(
                f"{OUTPUT} is out of date: run scripts/import_free_exercise_db.py", file=sys.stderr
            )
            return 1
        print("catalogue is up to date")
        return 0
    OUTPUT.write_text(wanted, encoding="utf-8")
    print(f"wrote {OUTPUT} ({wanted.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
