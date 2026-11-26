"""The exercise catalogue: parsing, enums and search. No database."""

import importlib.util
import json
from pathlib import Path

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.gym import (
    Category,
    Equipment,
    Exercise,
    Force,
    Level,
    Mechanic,
    Muscle,
    search,
)
from nexus.infra.exercises import CATALOGUE, load_catalogue

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_free_exercise_db.py"


def make(
    name: str,
    *,
    primary: tuple[Muscle, ...] = (Muscle.CHEST,),
    secondary: tuple[Muscle, ...] = (),
    equipment: Equipment | None = Equipment.BARBELL,
    level: Level = Level.BEGINNER,
) -> Exercise:
    return Exercise(
        id=name.replace(" ", "_"),
        name=name,
        category=Category.STRENGTH,
        level=level,
        equipment=equipment,
        force=Force.PUSH,
        mechanic=Mechanic.COMPOUND,
        primary=primary,
        secondary=secondary,
        instructions=("Lift.",),
        images=(f"{name.replace(' ', '_')}/0.jpg",),
    )


def names(found: list[Exercise]) -> list[str]:
    return [e.name for e in found]


def test_from_dict_maps_values_to_enums() -> None:
    e = Exercise.from_dict(
        {
            "id": "Bench",
            "name": "Bench",
            "category": "olympic weightlifting",
            "level": "expert",
            "equipment": "e-z curl bar",
            "force": None,
            "mechanic": "isolation",
            "primary": ["lower back"],
            "secondary": ["middle back", "triceps"],
            "instructions": ["a", "b"],
            "images": ["Bench/0.jpg"],
        }
    )
    assert e.category is Category.OLYMPIC_WEIGHTLIFTING
    assert e.equipment is Equipment.EZ_CURL_BAR
    assert e.force is None and e.mechanic is Mechanic.ISOLATION
    assert e.primary == (Muscle.LOWER_BACK,)
    assert e.secondary == (Muscle.MIDDLE_BACK, Muscle.TRICEPS)
    assert e.instructions == ("a", "b")


@pytest.mark.parametrize(
    "change",
    [{"level": "godlike"}, {"primary": ["wings"]}, {"primary": []}, {"id": " "}, {"name": None}],
)
def test_from_dict_refuses_bad_data(change: dict[str, object]) -> None:
    data: dict[str, object] = {
        "id": "X",
        "name": "X",
        "category": "strength",
        "level": "beginner",
        "equipment": None,
        "force": None,
        "mechanic": None,
        "primary": ["chest"],
        "secondary": [],
        "instructions": [],
        "images": [],
    }
    with pytest.raises(InvalidInput):
        Exercise.from_dict({**data, **change})


def test_there_are_seventeen_muscles() -> None:
    assert len(Muscle) == 17


def test_search_ranks_exact_then_prefix_then_word_start_then_contained() -> None:
    pool = [
        make("Incline Bench Press"),
        make("Benchmark Squat"),
        make("Bench Press - Powerlifting"),
        make("Bench"),
        make("Close Bench"),
    ]
    assert names(search(pool, text="bench")) == [
        "Bench",
        "Benchmark Squat",  # a prefix too, but the shorter name wins
        "Bench Press - Powerlifting",
        "Close Bench",
        "Incline Bench Press",
    ]
    assert names(search(pool, text="ench"))[0] == "Bench"  # inside a word, not the start


def test_search_ignores_case_and_punctuation_and_needs_every_word() -> None:
    pool = [make("Bench Press - Powerlifting"), make("Bench Dip"), make("Leg Press")]
    assert names(search(pool, text="PRESS bench")) == ["Bench Press - Powerlifting"]
    assert names(search(pool, text="bench-press")) == ["Bench Press - Powerlifting"]
    assert search(pool, text="squat") == []


def test_search_filters() -> None:
    pool = [
        make("A", primary=(Muscle.CHEST,), secondary=(Muscle.TRICEPS,)),
        make("B", primary=(Muscle.TRICEPS,), equipment=Equipment.CABLE),
        make("C", primary=(Muscle.LATS,), level=Level.EXPERT, equipment=None),
    ]
    assert names(search(pool, muscle=Muscle.TRICEPS)) == ["B", "A"]  # primary first
    assert names(search(pool, equipment=Equipment.CABLE)) == ["B"]
    assert names(search(pool, level=Level.EXPERT)) == ["C"]
    assert names(search(pool, muscle=Muscle.TRICEPS, equipment=Equipment.BARBELL)) == ["A"]
    assert names(search(pool)) == ["A", "B", "C"]


def test_search_limit() -> None:
    pool = [make(f"Row {i}") for i in range(10)]
    assert len(search(pool, text="row", limit=3)) == 3
    for bad in (0, 201):
        with pytest.raises(InvalidInput):
            search(pool, limit=bad)


def test_the_bundled_catalogue_is_valid() -> None:
    loaded = load_catalogue()
    assert len(loaded) > 800
    ids = [e.id for e in loaded]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)
    assert all(e.primary and e.instructions is not None for e in loaded)
    bench = next(e for e in loaded if e.id == "Barbell_Bench_Press_-_Medium_Grip")
    assert bench.primary == (Muscle.CHEST,)
    assert bench.equipment is Equipment.BARBELL
    assert bench.images == (
        "Barbell_Bench_Press_-_Medium_Grip/0.jpg",
        "Barbell_Bench_Press_-_Medium_Grip/1.jpg",
    )
    assert all(not i.startswith("/") and "://" not in i for e in loaded for i in e.images)


def test_the_bundled_catalogue_finds_bench_press_first() -> None:
    found = search(load_catalogue(), text="barbell bench press", limit=3)
    assert found and "bench press" in found[0].name.lower()
    assert search(load_catalogue(), muscle=Muscle.NECK)


def test_import_script_vocabulary_matches_the_domain() -> None:
    spec = importlib.util.spec_from_file_location("importer", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    namespace = vars(module)
    assert namespace["MUSCLES"] == {m.value for m in Muscle}
    assert namespace["EQUIPMENT"] == {e.value for e in Equipment}
    assert namespace["LEVELS"] == {e.value for e in Level}
    assert namespace["CATEGORIES"] == {e.value for e in Category}
    assert namespace["FORCES"] == {e.value for e in Force}
    assert namespace["MECHANICS"] == {e.value for e in Mechanic}


def test_catalogue_file_is_stable_json() -> None:
    text = CATALOGUE.read_text(encoding="utf-8")
    assert text.endswith("]\n")
    assert json.dumps(json.loads(text), indent=1, ensure_ascii=False) + "\n" == text
