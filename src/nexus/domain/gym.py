"""The exercise catalogue: what a movement is, and how to find one. Pure rules, no I/O.

The catalogue is shared by every user. It comes from free-exercise-db (public domain);
``scripts/import_free_exercise_db.py`` turns it into ``infra/exercises/catalogue.json``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from nexus.domain.errors import InvalidInput

MAX_RESULTS = 200


class Muscle(StrEnum):
    ABDOMINALS = "abdominals"
    ABDUCTORS = "abductors"
    ADDUCTORS = "adductors"
    BICEPS = "biceps"
    CALVES = "calves"
    CHEST = "chest"
    FOREARMS = "forearms"
    GLUTES = "glutes"
    HAMSTRINGS = "hamstrings"
    LATS = "lats"
    LOWER_BACK = "lower back"
    MIDDLE_BACK = "middle back"
    NECK = "neck"
    QUADRICEPS = "quadriceps"
    SHOULDERS = "shoulders"
    TRAPS = "traps"
    TRICEPS = "triceps"


class Equipment(StrEnum):
    BANDS = "bands"
    BARBELL = "barbell"
    BODY_ONLY = "body only"
    CABLE = "cable"
    DUMBBELL = "dumbbell"
    EZ_CURL_BAR = "e-z curl bar"
    EXERCISE_BALL = "exercise ball"
    FOAM_ROLL = "foam roll"
    KETTLEBELLS = "kettlebells"
    MACHINE = "machine"
    MEDICINE_BALL = "medicine ball"
    OTHER = "other"


class Level(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"


class Category(StrEnum):
    CARDIO = "cardio"
    OLYMPIC_WEIGHTLIFTING = "olympic weightlifting"
    PLYOMETRICS = "plyometrics"
    POWERLIFTING = "powerlifting"
    STRENGTH = "strength"
    STRETCHING = "stretching"
    STRONGMAN = "strongman"


class Force(StrEnum):
    PULL = "pull"
    PUSH = "push"
    STATIC = "static"


class Mechanic(StrEnum):
    COMPOUND = "compound"
    ISOLATION = "isolation"


@dataclass(frozen=True, slots=True)
class Exercise:
    """One movement. ``id`` is the source's own (``Barbell_Bench_Press_-_Medium_Grip``);
    ``images`` are paths relative to the image folder (``<Folder>/0.jpg``)."""

    id: str
    name: str
    category: Category
    level: Level
    equipment: Equipment | None
    force: Force | None
    mechanic: Mechanic | None
    primary: tuple[Muscle, ...]
    secondary: tuple[Muscle, ...]
    instructions: tuple[str, ...]
    images: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise InvalidInput("an exercise needs an id and a name")
        if not self.primary:
            raise InvalidInput(f"{self.id}: an exercise works at least one muscle")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Exercise":
        """From a catalogue.json entry; an unknown value is an ``InvalidInput``."""
        try:
            return cls(
                id=data["id"],
                name=data["name"],
                category=Category(data["category"]),
                level=Level(data["level"]),
                equipment=Equipment(data["equipment"]) if data.get("equipment") else None,
                force=Force(data["force"]) if data.get("force") else None,
                mechanic=Mechanic(data["mechanic"]) if data.get("mechanic") else None,
                primary=tuple(Muscle(m) for m in data["primary"]),
                secondary=tuple(Muscle(m) for m in data["secondary"]),
                instructions=tuple(data["instructions"]),
                images=tuple(data["images"]),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise InvalidInput(f"bad exercise {data.get('id')!r}: {exc}") from exc


def words(text: str) -> list[str]:
    """Lower-case alphanumeric runs: how names and search text are compared."""
    cleaned = "".join(c if c.isalnum() else " " for c in text.casefold())
    return cleaned.split()


def _text_rank(exercise: Exercise, query: str, tokens: Sequence[str]) -> int | None:
    """0 exact name, 1 name starts with the query, 2 every word of the query starts a word
    of the name, 3 every word of the query appears inside the name; else None."""
    name = " ".join(words(exercise.name))
    if name == query:
        return 0
    if name.startswith(query):
        return 1
    name_words = name.split()
    if all(any(w.startswith(t) for w in name_words) for t in tokens):
        return 2
    if all(t in name for t in tokens):
        return 3
    return None


def search(
    exercises: Iterable[Exercise],
    *,
    text: str | None = None,
    muscle: Muscle | None = None,
    equipment: Equipment | None = None,
    level: Level | None = None,
    limit: int = 50,
) -> list[Exercise]:
    """Exercises matching every filter given, best first.

    ``text`` matches the name (case and punctuation ignored); exact, then prefix, then
    word-start matches come first. ``muscle`` matches a primary or secondary muscle, and
    among equals the ones that train it primarily come first. Ties go to the shorter name.
    """
    if not 1 <= limit <= MAX_RESULTS:
        raise InvalidInput(f"limit must be between 1 and {MAX_RESULTS}")
    tokens = words(text) if text else []
    query = " ".join(tokens)
    ranked: list[tuple[int, int, int, str, Exercise]] = []
    for e in exercises:
        if equipment is not None and e.equipment != equipment:
            continue
        if level is not None and e.level != level:
            continue
        if muscle is not None and muscle not in e.primary and muscle not in e.secondary:
            continue
        rank = _text_rank(e, query, tokens) if tokens else 0
        if rank is None:
            continue
        primary = 0 if muscle is None or muscle in e.primary else 1
        ranked.append((rank, primary, len(e.name), e.name.casefold(), e))
    ranked.sort(key=lambda r: r[:4])
    return [r[4] for r in ranked[:limit]]
