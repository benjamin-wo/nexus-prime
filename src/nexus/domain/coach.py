"""The Gym coach's rules: what a drafted plan must satisfy, and what a log of past sessions
suggests changing. Pure and table-driven, with no I/O and no model: the model fills a plan, code
decides whether it may be shown, and every number in a proposal is worked out here (ADR 0004).

Wellness only. Nothing here diagnoses, treats or programs around pain or an injury: a message
that mentions either is a referral to a professional (``mentions_pain``), and nobody under 18
is given a drafted plan (``application/coach.py`` checks the age).

The limits below are **conservative design choices, not sourced guidance**. The research report
("Nexus Health wearables nutrition agent", section D) says the "RPE/RIR and volume citations
still need to be sourced before the rules sheet ships"; until they are, these numbers are kept
inside the range the common coaching literature agrees is unremarkable, and each is a named
constant so one change updates the checks, the card and the tests together.
"""

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from fractions import Fraction
from itertools import pairwise
from typing import Any
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.gym import Equipment, Exercise, Muscle
from nexus.domain.gym_training import (
    SetEntry,
    Slot,
    e1rm_kg,
    progress,
    week_start,
)

# --- the user's training inputs -------------------------------------------------------------

MIN_DAYS = 1
MAX_DAYS = 7
MIN_SESSION_MINUTES = 10
MAX_SESSION_MINUTES = 240


class Experience(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class Focus(StrEnum):
    STRENGTH = "strength"
    HYPERTROPHY = "hypertrophy"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class TrainingProfile:
    """What the coach plans around. Equipment is a list of the catalogue's equipment values;
    body-weight exercises never need to be listed."""

    days_per_week: int
    session_minutes: int
    equipment: tuple[Equipment, ...]
    experience: Experience
    focus: Focus

    def __post_init__(self) -> None:
        for value, low, high, what in (
            (self.days_per_week, MIN_DAYS, MAX_DAYS, "days a week"),
            (self.session_minutes, MIN_SESSION_MINUTES, MAX_SESSION_MINUTES, "session minutes"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise InvalidInput(f"{what} must be a whole number from {low} to {high}")
        object.__setattr__(self, "equipment", tuple(dict.fromkeys(self.equipment)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "days_per_week": self.days_per_week,
            "session_minutes": self.session_minutes,
            "equipment": [e.value for e in self.equipment],
            "experience": self.experience.value,
            "focus": self.focus.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TrainingProfile":
        try:
            return cls(
                days_per_week=data["days_per_week"],
                session_minutes=data["session_minutes"],
                equipment=tuple(Equipment(e) for e in data["equipment"]),
                experience=Experience(data["experience"]),
                focus=Focus(data["focus"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidInput(f"bad training profile: {exc}") from exc


# --- plan limits ----------------------------------------------------------------------------

MIN_WEEKLY_SETS = 4  # working sets a week for a muscle the plan trains on purpose
MAX_WEEKLY_SETS = 25  # and the most, counting a secondary muscle's sets as half
SECONDARY_WEIGHT = Fraction(1, 2)  # the same half ``volume_by_muscle`` gives secondary muscles
REP_SECONDS = 4  # time under tension of one rep, for the session length estimate
SESSION_SLACK = Fraction(115, 100)  # a session may run 15% over the time the user has
MAX_ROUTINES = 7
MAX_SLOTS_PER_ROUTINE = 12

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_ALIASES = {
    **{name: i for i, name in enumerate(DAY_NAMES)},
    **{
        full: i
        for i, full in enumerate(
            ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        )
    },
}


def weekday_of(text: str) -> int | None:
    """Monday is 0; None for something that isn't a day name."""
    return _DAY_ALIASES.get(text.strip().casefold())


@dataclass(frozen=True, slots=True)
class PlannedSlot:
    """One line of a drafted routine, its exercise already found in the catalogue."""

    exercise: Exercise
    sets: int
    reps: int | None
    seconds: int | None
    rest_seconds: int = 90

    def slot(self) -> Slot:
        """The stored form; ``InvalidInput`` if the numbers are outside ``Slot``'s bounds."""
        return Slot(self.exercise.id, self.sets, self.reps, self.seconds, self.rest_seconds)

    def seconds_per_set(self) -> int:
        work = self.seconds if self.seconds is not None else (self.reps or 0) * REP_SECONDS
        return work + self.rest_seconds


@dataclass(frozen=True, slots=True)
class PlannedRoutine:
    name: str
    slots: tuple[PlannedSlot, ...]


@dataclass(frozen=True, slots=True)
class PlannedSchedule:
    """Either a routine per weekday (Monday is 0) or routines in turn, by routine name."""

    weekly: tuple[tuple[int, str], ...] = ()
    rotation: tuple[str, ...] = ()


def session_minutes(routine: PlannedRoutine) -> int:
    """The routine's estimated length: sets x (work + rest), rounded up to whole minutes."""
    seconds = sum(s.sets * s.seconds_per_set() for s in routine.slots)
    return math.ceil(seconds / 60)


def _sessions_a_week(schedule: PlannedSchedule, profile: TrainingProfile) -> dict[str, Fraction]:
    """How often each routine runs in a week. A rotation runs ``days_per_week`` sessions."""
    sessions: dict[str, Fraction] = defaultdict(Fraction)
    for _, name in schedule.weekly:
        sessions[name.casefold()] += 1
    if schedule.rotation:
        each = Fraction(profile.days_per_week, len(schedule.rotation))
        for name in schedule.rotation:
            sessions[name.casefold()] += each
    return sessions


def weekly_sets(
    routines: Sequence[PlannedRoutine], schedule: PlannedSchedule, profile: TrainingProfile
) -> tuple[dict[Muscle, Fraction], set[Muscle]]:
    """Working sets a week per muscle (a secondary muscle's count as half), and the muscles
    some set trains as a primary one."""
    sessions = _sessions_a_week(schedule, profile)
    totals: dict[Muscle, Fraction] = defaultdict(Fraction)
    direct: set[Muscle] = set()
    for routine in routines:
        times = sessions.get(routine.name.casefold(), Fraction(0))
        for slot in routine.slots:
            for muscle in slot.exercise.primary:
                totals[muscle] += slot.sets * times
                direct.add(muscle)
            for muscle in slot.exercise.secondary:
                if muscle not in slot.exercise.primary:
                    totals[muscle] += slot.sets * times * SECONDARY_WEIGHT
    return dict(totals), direct


def _shown(value: Fraction) -> str:
    return str(int(value)) if value.denominator == 1 else f"{float(value):.1f}"


def validate_plan(
    routines: Sequence[PlannedRoutine], schedule: PlannedSchedule, profile: TrainingProfile
) -> list[str]:
    """Everything wrong with a drafted plan, in words for the model; empty when it is fine.

    Exercises are already resolved to the catalogue (an unknown or ambiguous one never gets
    here). Checked: routine names, slot numbers inside ``Slot``'s bounds, equipment the user has
    (body weight always counts), no exercise twice in a routine, session length within
    ``session_minutes`` + 15%, the schedule's days within ``days_per_week``, every routine
    scheduled, and weekly sets per muscle between ``MIN_WEEKLY_SETS`` and ``MAX_WEEKLY_SETS``."""
    problems: list[str] = []
    if not routines:
        return ["the plan has no routines"]
    if len(routines) > MAX_ROUTINES:
        problems.append(f"at most {MAX_ROUTINES} routines")
    names = [r.name.strip().casefold() for r in routines]
    if "" in names:
        problems.append("every routine needs a name")
    for name in {n for n in names if names.count(n) > 1}:
        problems.append(f"two routines are called {name!r}: give each its own name")

    have = set(profile.equipment) | {Equipment.BODY_ONLY}
    have_text = ", ".join(e.value for e in profile.equipment) or "body weight only"
    for routine in routines:
        label = f"routine {routine.name!r}"
        if not routine.slots:
            problems.append(f"{label} has no exercises")
            continue
        if len(routine.slots) > MAX_SLOTS_PER_ROUTINE:
            problems.append(f"{label} has more than {MAX_SLOTS_PER_ROUTINE} exercises")
        seen: set[str] = set()
        for slot in routine.slots:
            name = slot.exercise.name
            if slot.exercise.id in seen:
                problems.append(f"{label} has {name} twice")
            seen.add(slot.exercise.id)
            try:
                slot.slot()
            except InvalidInput as exc:
                problems.append(f"{label}, {name}: {exc}")
            equipment = slot.exercise.equipment
            if equipment is not None and equipment not in have:
                problems.append(
                    f"{label}, {name} needs {equipment.value}, which the user doesn't have "
                    f"(they have: {have_text})"
                )
        limit = math.floor(profile.session_minutes * SESSION_SLACK)
        minutes = session_minutes(routine)
        if minutes > limit:
            problems.append(
                f"{label} would take about {minutes} minutes, over the {limit} minutes allowed "
                f"for a {profile.session_minutes}-minute session: fewer sets or exercises, or "
                "shorter rests"
            )

    problems += _schedule_problems(routines, schedule, profile)
    if schedule.weekly or schedule.rotation:
        totals, direct = weekly_sets(routines, schedule, profile)
        for muscle in sorted(totals, key=lambda m: m.value):
            sets = totals[muscle]
            if sets > MAX_WEEKLY_SETS:
                problems.append(
                    f"{muscle.value} would get {_shown(sets)} sets a week, over the "
                    f"{MAX_WEEKLY_SETS} allowed"
                )
            elif muscle in direct and sets < MIN_WEEKLY_SETS:
                problems.append(
                    f"{muscle.value} would get only {_shown(sets)} sets a week: at least "
                    f"{MIN_WEEKLY_SETS}, or leave it out"
                )
    return problems


def _schedule_problems(
    routines: Sequence[PlannedRoutine], schedule: PlannedSchedule, profile: TrainingProfile
) -> list[str]:
    problems: list[str] = []
    known = {r.name.strip().casefold() for r in routines}
    if bool(schedule.weekly) == bool(schedule.rotation):
        return ["give the schedule either days of the week or a rotation, not both and not neither"]
    days = [d for d, _ in schedule.weekly]
    if len(set(days)) != len(days):
        problems.append("a weekday appears twice in the schedule")
    if len(set(days)) > profile.days_per_week:
        problems.append(
            f"the schedule trains on {len(set(days))} days, but the user trains "
            f"{profile.days_per_week} days a week"
        )
    named = [n for _, n in schedule.weekly] + list(schedule.rotation)
    for name in dict.fromkeys(named):
        if name.strip().casefold() not in known:
            problems.append(f"the schedule names {name!r}, which isn't one of the routines")
    for routine in routines:
        if routine.name.strip().casefold() not in {n.strip().casefold() for n in named}:
            problems.append(f"routine {routine.name!r} isn't in the schedule")
    return problems


# --- pain and injury ------------------------------------------------------------------------

_PAIN = re.compile(
    r"\b(?:pain\w*|hurts?|hurting|ach(?:e|es|ing)|injur\w+|sprain\w*|strain(?:ed)?|torn|tore|tear|"
    r"tendon\w*|tendin\w+|ligament\w*|herniat\w+|slipped disc|sciatica|dislocat\w+|fractur\w+|"
    r"broke(?:n)? my|surgery|rehab\w*|physio\w*|twinge\w*|pinch(?:ed|ing)|"
    r"(?:knee|shoulder|back|hip|elbow|wrist|ankle|neck)s? (?:is|are|has been|have been)? ?"
    r"(?:bad|sore|stiff|swollen|clicking|popping|locking|giving way))\b"
)


def mentions_pain(text: str) -> bool:
    """Whether the words mention pain or an injury. Deliberately broad: a wrong guess means
    the user is pointed to a professional, which costs nothing."""
    return bool(_PAIN.search(text.casefold().replace("\u2019", "'")))


# --- proposing changes from the log --------------------------------------------------------

LOOKBACK_DAYS = 28  # the sessions that count for a slot's progression
DELOAD_LOOKBACK_DAYS = 56  # the weeks looked at for a deload
RPE_CEILING = Decimal(8)  # reps hit at this effort or easier count as a good session
SESSIONS_TO_ADD = 2  # good sessions running before the load goes up
SESSIONS_TO_HOLD = 2  # missed sessions running before it holds
SESSIONS_TO_DROP = 3  # and before it comes down
UPPER_STEP_KG = Decimal("2.5")
LOWER_STEP_KG = Decimal("5")
DROP_FRACTION = Decimal("0.9")  # minus 10%
ROUND_TO_KG = Decimal("0.5")
DELOAD_AFTER_WEEKS = 6  # training weeks running without a lighter one
FALLING_E1RM_EXERCISES = 3  # exercises whose estimated max is falling
FALLING_SESSIONS = 3  # an estimated max lower at each of this many sessions running
DELOAD_WEEK_RATIO = Fraction(3, 5)  # a week with at most this share of last week's sets is light
DELOAD_NOTE = "Deload week: usual "

LOWER_BODY = frozenset(
    {
        Muscle.QUADRICEPS,
        Muscle.HAMSTRINGS,
        Muscle.GLUTES,
        Muscle.CALVES,
        Muscle.ABDUCTORS,
        Muscle.ADDUCTORS,
        Muscle.LOWER_BACK,
    }
)


def is_lower_body(exercise: Exercise) -> bool:
    """Judged by the exercise's first (main) primary muscle."""
    return exercise.primary[0] in LOWER_BODY


class ProposalKind(StrEnum):
    INCREASE = "increase"
    HOLD = "hold"
    DECREASE = "decrease"
    DELOAD = "deload"
    RESTORE = "restore"  # end a deload: back to the usual sets


@dataclass(frozen=True, slots=True)
class SlotRef:
    """One slot of a routine in the current plan."""

    routine_id: UUID
    routine_name: str
    index: int
    slot: Slot


@dataclass(frozen=True, slots=True)
class Proposal:
    kind: ProposalKind
    reason: str  # built here, from the numbers
    routine_id: UUID | None = None
    exercise_id: str | None = None
    exercise_name: str | None = None
    from_kg: Decimal | None = None
    to_kg: Decimal | None = None

    @property
    def actionable(self) -> bool:
        return self.kind is not ProposalKind.HOLD


class Verdict(StrEnum):
    HIT = "hit"  # every set reached the target at an effort of 8 or easier
    HARD = "hard"  # the target was reached, but at a higher effort
    MISSED = "missed"


@dataclass(frozen=True, slots=True)
class Session:
    workout_id: UUID
    at: datetime
    sets: tuple[SetEntry, ...]  # the working sets of one exercise in one workout


def sessions_of(sets: Iterable[SetEntry]) -> list[Session]:
    """The working sets of an exercise grouped by workout, oldest session first."""
    by_workout: dict[UUID, list[SetEntry]] = defaultdict(list)
    for s in sets:
        if s.counts:
            by_workout[s.workout_id].append(s)
    found = [
        Session(w, max(s.done_at for s in group), tuple(sorted(group, key=lambda s: s.position)))
        for w, group in by_workout.items()
    ]
    return sorted(found, key=lambda s: (s.at, str(s.workout_id)))


def verdict(session: Session, slot: Slot) -> Verdict:
    """How a session went against the slot's target: all the prescribed sets, each reaching the
    reps (or seconds). An effort over RPE 8 makes a reached target ``HARD``; no recorded effort
    counts as fine."""
    if len(session.sets) < slot.sets:
        return Verdict.MISSED
    for s in session.sets:
        if slot.reps is not None and (s.reps or 0) < slot.reps:
            return Verdict.MISSED
        if slot.seconds is not None and (s.seconds or 0) < slot.seconds:
            return Verdict.MISSED
    if any(s.rpe is not None and s.rpe > RPE_CEILING for s in session.sets):
        return Verdict.HARD
    return Verdict.HIT


def _rounded(kg: Decimal) -> Decimal:
    return (kg / ROUND_TO_KG).quantize(Decimal(1), ROUND_HALF_UP) * ROUND_TO_KG


def _top_weight_kg(session: Session) -> Decimal | None:
    weights = [w for s in session.sets if (w := s.weight_kg) is not None and w > 0]
    return max(weights) if weights else None


def plain_kg(value: Decimal) -> str:
    text = f"{value.quantize(Decimal('0.01'), ROUND_HALF_UP):f}"
    return text.rstrip("0").rstrip(".")


def _progression(ref: SlotRef, exercise: Exercise, sessions: Sequence[Session]) -> Proposal | None:
    """The proposal for one slot from its recent sessions (oldest first), or None."""
    if len(sessions) < SESSIONS_TO_HOLD:
        return None
    verdicts = [verdict(s, ref.slot) for s in sessions]
    name = exercise.name
    last = _top_weight_kg(sessions[-1])
    if len(verdicts) >= SESSIONS_TO_DROP and all(
        v is Verdict.MISSED for v in verdicts[-SESSIONS_TO_DROP:]
    ):
        if last is None:
            return None
        to = _rounded(last * DROP_FRACTION)
        return Proposal(
            ProposalKind.DECREASE,
            f"{name}: the target was missed in the last {SESSIONS_TO_DROP} sessions, so try "
            f"{plain_kg(to)} kg (10% under {plain_kg(last)} kg)",
            from_kg=last,
            to_kg=to,
            routine_id=ref.routine_id,
            exercise_id=exercise.id,
            exercise_name=name,
        )
    if all(v is Verdict.MISSED for v in verdicts[-SESSIONS_TO_HOLD:]):
        return Proposal(
            ProposalKind.HOLD,
            f"{name}: the target was missed in the last {SESSIONS_TO_HOLD} sessions, so stay at "
            "the same load",
            routine_id=ref.routine_id,
            exercise_id=exercise.id,
            exercise_name=name,
        )
    if all(v is Verdict.HIT for v in verdicts[-SESSIONS_TO_ADD:]):
        if last is None:
            return None
        step = LOWER_STEP_KG if is_lower_body(exercise) else UPPER_STEP_KG
        return Proposal(
            ProposalKind.INCREASE,
            f"{name}: every target rep was reached at RPE {plain_kg(RPE_CEILING)} or easier "
            f"in the last {SESSIONS_TO_ADD} sessions, so add {plain_kg(step)} kg: "
            f"{plain_kg(last + step)} kg (from {plain_kg(last)} kg)",
            from_kg=last,
            to_kg=last + step,
            routine_id=ref.routine_id,
            exercise_id=exercise.id,
            exercise_name=name,
        )
    return None


def _week_counts(sets: Iterable[SetEntry], tz: tzinfo) -> dict[date, int]:
    counts: dict[date, int] = defaultdict(int)
    for s in sets:
        if s.counts:
            counts[week_start(s.done_at.astimezone(tz).date())] += 1
    return dict(counts)


def _light(counts: Mapping[date, int], week: date) -> bool:
    before = counts.get(week - timedelta(days=7), 0)
    return before > 0 and Fraction(counts.get(week, 0), before) <= DELOAD_WEEK_RATIO


def weeks_without_deload(counts: Mapping[date, int], this_week: date) -> int:
    """Finished training weeks running, newest first, up to a week with no sets or a light one.
    The week in progress doesn't count."""
    weeks = 0
    week = this_week - timedelta(days=7)
    while counts.get(week, 0) > 0 and not _light(counts, week):
        weeks += 1
        week -= timedelta(days=7)
    return weeks


def _falling(sets: Sequence[SetEntry]) -> bool:
    points = [p.e1rm_kg for p in progress(sets)][-FALLING_SESSIONS:]
    return len(points) == FALLING_SESSIONS and all(a > b for a, b in pairwise(points))


def _deload_noted(refs: Sequence[SlotRef]) -> bool:
    return any((r.slot.note or "").startswith(DELOAD_NOTE) for r in refs)


def usual_sets(note: str | None) -> int | None:
    """The sets a deloaded slot normally has, from its note."""
    match = re.match(rf"{re.escape(DELOAD_NOTE)}(\d+) sets?", note or "")
    return int(match.group(1)) if match else None


def deloaded_slot(slot: Slot) -> Slot:
    """The slot with its sets halved (rounded up, so never none) and the usual ones in its note."""
    if (slot.note or "").startswith(DELOAD_NOTE):
        return slot
    return replace(slot, sets=math.ceil(slot.sets / 2), note=f"{DELOAD_NOTE}{slot.sets} sets")


def restored_slot(slot: Slot) -> Slot:
    usual = usual_sets(slot.note)
    return slot if usual is None else replace(slot, sets=usual, note=None)


def suggest_progression(
    refs: Sequence[SlotRef],
    history: Mapping[str, Sequence[SetEntry]],
    catalogue: Mapping[str, Exercise],
    *,
    now: datetime,
    tz: tzinfo = UTC,
) -> list[Proposal]:
    """What to change in the current plan, from the sets logged (``history``: every set of the
    plan's exercises over the last ``DELOAD_LOOKBACK_DAYS``, by exercise id).

    Per slot, over its sessions in the last ``LOOKBACK_DAYS`` (the latest first below):
    - the last 3 missed the target: -10% load (``DECREASE``);
    - the last 2 missed it: hold the load (``HOLD``);
    - the last 2 reached every target rep at RPE 8 or easier: +2.5 kg for an upper-body
      exercise, +5 kg for a lower-body one (``INCREASE``); the exercise's first primary muscle
      decides which. An exercise without a weight has nothing to add to.
    For the plan as a whole, after ``DELOAD_AFTER_WEEKS`` training weeks without a light one,
    or when the estimated one-rep max has fallen across the last 3 sessions of
    ``FALLING_E1RM_EXERCISES`` exercises: a deload (every slot's sets halved), which then
    stands in for the per-slot proposals. When a deload has been applied and the last finished
    week was a light one, the usual sets come back (``RESTORE``).
    """
    if not refs:
        return []
    all_sets = [s for sets in history.values() for s in sets]
    counts = _week_counts(all_sets, tz)
    this_week = week_start(now.astimezone(tz).date())
    if _deload_noted(refs):
        last_week = this_week - timedelta(days=7)
        if _light(counts, last_week):
            return [
                Proposal(
                    ProposalKind.RESTORE,
                    "last week's training was light, so go back to the usual sets",
                )
            ]
        return []

    streak = weeks_without_deload(counts, this_week)
    falling = sorted(
        {r.slot.exercise_id for r in refs if _falling(history.get(r.slot.exercise_id, ()))}
    )
    if streak >= DELOAD_AFTER_WEEKS or len(falling) >= FALLING_E1RM_EXERCISES:
        why = (
            f"{streak} training weeks in a row without a lighter one"
            if streak >= DELOAD_AFTER_WEEKS
            else f"the estimated one-rep max has fallen over the last {FALLING_SESSIONS} "
            f"sessions on {len(falling)} exercises"
        )
        return [
            Proposal(
                ProposalKind.DELOAD,
                f"{why}: a deload week, with the sets of every exercise halved",
            )
        ]

    since = now - timedelta(days=LOOKBACK_DAYS)
    out: list[Proposal] = []
    for ref in refs:
        exercise = catalogue.get(ref.slot.exercise_id)
        if exercise is None:
            continue
        sessions = [s for s in sessions_of(history.get(ref.slot.exercise_id, ())) if s.at >= since]
        if (found := _progression(ref, exercise, sessions)) is not None:
            out.append(found)
    return out


def e1rm_of_session(session: Session) -> Decimal | None:
    """The best estimated one-rep max in a session, for display."""
    values = [v for s in session.sets if (v := e1rm_kg(s)) is not None]
    return max(values) if values else None


def describe_proposals(proposals: Sequence[Proposal]) -> str:
    """The proposals as a numbered list (only the ones that change something are numbered, so
    a number is what ``apply_adjustments`` takes), then the ones that stay as they are."""
    if not proposals:
        return "Nothing to change: no slot has two sessions that point to a change yet."
    lines: list[str] = []
    n = 0
    for p in proposals:
        if p.actionable:
            n += 1
            lines.append(f"{n}. {p.reason}")
    keep = [p.reason for p in proposals if not p.actionable]
    if keep:
        lines += ["No change:", *(f"- {r}" for r in keep)]
    return "\n".join(lines)


def actionable(proposals: Sequence[Proposal]) -> list[Proposal]:
    return [p for p in proposals if p.actionable]


# --- the confirm card -----------------------------------------------------------------------


def _reps_text(slot: PlannedSlot) -> str:
    target = f"{slot.reps}" if slot.reps is not None else f"{slot.seconds} s"
    return f"{slot.sets} x {target}, rest {slot.rest_seconds} s"


def draft_card(
    routines: Sequence[PlannedRoutine], schedule: PlannedSchedule, profile: TrainingProfile
) -> str:
    """The drafted plan in words, for the user to confirm. Every figure is worked out here."""
    lines = ["Save this training plan? It replaces your current plan.", ""]
    for routine in routines:
        lines.append(f"{routine.name} (about {session_minutes(routine)} min)")
        lines += [f"- {s.exercise.name}: {_reps_text(s)}" for s in routine.slots]
        lines.append("")
    if schedule.weekly:
        days = sorted(schedule.weekly)
        lines.append("Schedule: " + ", ".join(f"{DAY_NAMES[d].title()} {n}" for d, n in days))
    else:
        lines.append("Rotation: " + ", ".join(schedule.rotation))
    totals, direct = weekly_sets(routines, schedule, profile)
    trained = sorted(direct, key=lambda m: m.value)
    lines.append("Sets a week: " + ", ".join(f"{m.value} {_shown(totals[m])}" for m in trained))
    lines.append(
        f"Built for {profile.days_per_week} days a week, {profile.session_minutes}-minute "
        f"sessions, {profile.experience.value}, focus {profile.focus.value}."
    )
    return "\n".join(lines)
