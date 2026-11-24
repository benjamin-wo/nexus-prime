"""Words for gym figures. The numbers come from the application layer; this only writes them
down, so the model quotes them and never works them out."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from nexus.domain.gym_training import PrKind, SetKind, WeightUnit

PR_WORDS = {
    PrKind.HEAVIEST_WEIGHT: "heaviest weight",
    PrKind.BEST_E1RM: "best estimated one-rep max",
    PrKind.MOST_REPS: "most reps at a weight you've lifted before",
}


class SetLike(Protocol):
    @property
    def kind(self) -> SetKind: ...
    @property
    def reps(self) -> int | None: ...
    @property
    def seconds(self) -> int | None: ...
    @property
    def weight(self) -> Decimal | None: ...
    @property
    def unit(self) -> WeightUnit | None: ...
    @property
    def rpe(self) -> Decimal | None: ...


def num(value: Decimal, places: int = 2) -> str:
    """ "80", "82.5", "1,234.5": at most ``places`` decimals, none when whole."""
    shown = value.quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    text = f"{shown:,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def kg_text(kg: Decimal) -> str:
    return f"{num(kg, 1)} kg"


def weight_text(weight: Decimal, unit: WeightUnit | None) -> str:
    return f"{num(weight)} {(unit or WeightUnit.KG).value}"


def _key(s: SetLike) -> tuple[object, ...]:
    return (s.kind, s.reps, s.seconds, s.weight, s.unit or WeightUnit.KG, s.rpe)


def describe_sets(sets: Iterable[SetLike]) -> str:
    """ "3 sets of 5 at 80 kg, 1 set of 3 at 85 kg (RPE 9)": runs of identical sets are one."""
    runs: list[tuple[SetLike, int]] = []
    for s in sets:
        if runs and _key(runs[-1][0]) == _key(s):
            runs[-1] = (s, runs[-1][1] + 1)
        else:
            runs.append((s, 1))
    parts = []
    for s, n in runs:
        what = "warm-up set" if s.kind is SetKind.WARMUP else "set"
        text = f"{n} {what}{'' if n == 1 else 's'} of "
        text += f"{s.reps}" if s.reps is not None else f"{s.seconds} s"
        if s.weight:
            text += f" at {weight_text(s.weight, s.unit)}"
        if s.rpe is not None:
            text += f" (RPE {num(s.rpe, 1)})"
        parts.append(text)
    return ", ".join(parts)


def duration_text(span: timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    if minutes < 1:
        return "under a minute"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def day_text(day: date, today: date) -> str:
    """ "Mon 21 Sep", with the year when it isn't this year."""
    return f"{day:%a %-d %b}" if day.year == today.year else f"{day:%a %-d %b %Y}"


def pr_text(prs: Mapping[str, Sequence[PrKind]], names: Mapping[str, str]) -> str:
    return "; ".join(
        f"{names.get(e, e)} ({', '.join(PR_WORDS[k] for k in kinds)})" for e, kinds in prs.items()
    )
