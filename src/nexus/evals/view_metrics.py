"""How well turns open views (ADR 0005): the figures the surfacing gates are read from.

Pure functions over one record per turn, so the runner (from its own results) and
``compare`` (from a results file) score the same way. The design is the one
``docs/plans/domain-panels.md`` 0.2 and 0.3 set out:

- a turn is *scored* when it has an expected set of views (a case's ``views``, or the views
  its expected tools open); a turn with none is left out of the view figures;
- precision, recall and F1 are micro (every view of every scored turn pooled) and macro
  (per view kind, then averaged over the kinds that were expected or opened);
- exact-set match: the turn opened exactly the expected kinds;
- correct silence: of the scored turns that should open nothing, the share that didn't;
- over-surfacing: scored turns that opened a kind not expected; under-surfacing: scored
  turns that missed an expected kind;
- carry-over: of the scored follow-up turns ("and last month?"), the share that opened
  exactly the expected kinds;
- distractor: exact-set match on the turns of cases written to sit next to another domain
  ("what did I spend on gym memberships" is money, not Health).

A wrong view set never fails a case: these figures sit beside the pass rate, not in it.
With ``--repeat`` each figure is worked out per round and shown as mean, min and max.
A figure with nothing to count is None, shown "n/a".
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TurnViews:
    """One turn, as the view figures see it. Kinds are ``ViewKind`` values."""

    expected: frozenset[str] | None  # None: not scored
    actual: frozenset[str] = frozenset()
    follow_up: bool = False  # not the first turn of its case
    distractor: bool = False
    round_no: int = 1


@dataclass(frozen=True, slots=True)
class ViewScores:
    precision: float | None
    recall: float | None
    f1: float | None
    macro_precision: float | None
    macro_recall: float | None
    macro_f1: float | None
    exact: float | None
    silence: float | None
    over: float | None
    under: float | None
    carry_over: float | None
    distractor: float | None
    scored: int  # turns with an expected set
    silent: int  # of them, turns that should open nothing


# What each figure is called in the report, in the order shown.
LABELS: dict[str, str] = {
    "precision": "View precision (micro)",
    "recall": "View recall (micro)",
    "f1": "View F1 (micro)",
    "macro_precision": "View precision (macro)",
    "macro_recall": "View recall (macro)",
    "macro_f1": "View F1 (macro)",
    "exact": "Exact-set match",
    "silence": "Correct silence",
    "over": "Over-surfacing (lower is better)",
    "under": "Under-surfacing (lower is better)",
    "carry_over": "Follow-up carry-over (exact set)",
    "distractor": "Distractor cases (exact set)",
}


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None and r is None:
        return None
    if not p or not r:  # one undefined or zero: nothing was both expected and opened
        return 0.0
    return 2 * p * r / (p + r)


def score(turns: Sequence[TurnViews]) -> ViewScores:
    """The figures for one round of turns."""
    scored = [t for t in turns if t.expected is not None]
    pairs = [(t.expected or frozenset(), t.actual) for t in scored]
    hits = sum(len(e & a) for e, a in pairs)
    opened = sum(len(a) for _, a in pairs)
    wanted = sum(len(e) for e, _ in pairs)
    precision, recall = _share(hits, opened), _share(hits, wanted)

    # Per kind, with an undefined share counted as 0 (a kind never opened has precision 0),
    # over the kinds that were expected or opened anywhere.
    kinds = sorted({k for e, a in pairs for k in e | a})
    per_kind = []
    for kind in kinds:
        tp = sum(kind in e and kind in a for e, a in pairs)
        fp = sum(kind in a and kind not in e for e, a in pairs)
        fn = sum(kind in e and kind not in a for e, a in pairs)
        p, r = (_share(tp, tp + fp) or 0.0), (_share(tp, tp + fn) or 0.0)
        per_kind.append((p, r, _f1(p, r) or 0.0))

    def macro(i: int) -> float | None:
        return sum(k[i] for k in per_kind) / len(per_kind) if per_kind else None

    silent = [a for e, a in pairs if not e]
    follow = [(t.expected, t.actual) for t in scored if t.follow_up]
    distract = [(t.expected, t.actual) for t in scored if t.distractor]
    return ViewScores(
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        macro_precision=macro(0),
        macro_recall=macro(1),
        macro_f1=macro(2),
        exact=_share(sum(e == a for e, a in pairs), len(pairs)),
        silence=_share(sum(not a for a in silent), len(silent)),
        over=_share(sum(bool(a - e) for e, a in pairs), len(pairs)),
        under=_share(sum(bool(e - a) for e, a in pairs), len(pairs)),
        carry_over=_share(sum(e == a for e, a in follow), len(follow)),
        distractor=_share(sum(e == a for e, a in distract), len(distract)),
        scored=len(pairs),
        silent=len(silent),
    )


def by_round(turns: Sequence[TurnViews]) -> list[ViewScores]:
    """The figures for each round, in round order."""
    rounds = sorted({t.round_no for t in turns})
    return [score([t for t in turns if t.round_no == n]) for n in rounds]


@dataclass(frozen=True, slots=True)
class Spread:
    mean: float
    low: float
    high: float


def spread(rounds: Sequence[ViewScores]) -> dict[str, Spread | None]:
    """Each figure's mean, min and max over the rounds where it was defined."""
    out: dict[str, Spread | None] = {}
    for name in LABELS:
        values = [v for r in rounds if (v := getattr(r, name)) is not None]
        out[name] = Spread(sum(values) / len(values), min(values), max(values)) if values else None
    return out


def counted(turns: Sequence[TurnViews]) -> bool:
    """Whether there is anything to report: a scored turn."""
    return any(t.expected is not None for t in turns)


def show(value: Spread | None, repeat: int) -> str:
    """A figure as the report shows it: "83%", or "83% (75-92%)" over several rounds."""
    if value is None:
        return "n/a"
    if repeat > 1:
        return f"{value.mean:.0%} ({value.low:.0%}-{value.high:.0%})"
    return f"{value.mean:.0%}"


def section(turns: Sequence[TurnViews]) -> list[str]:
    """The "Views" part of the Markdown report; empty when there's nothing."""
    if not counted(turns):
        return []
    rounds = by_round(turns)
    figures = spread(rounds)
    first = rounds[0]
    repeat = len(rounds)
    lines = [
        "",
        "Views"
        + (f" (mean, min-max over {repeat} rounds)" if repeat > 1 else "")
        + f": {first.scored} scored turns a round, {first.silent} of them should open nothing",
        "",
        "| Figure | Value |",
        "|---|---|",
    ]
    lines += [f"| {label} | {show(figures[name], repeat)} |" for name, label in LABELS.items()]
    return lines


def as_json(turns: Sequence[TurnViews]) -> dict[str, object]:
    """The figures per round and their spread, for the results file."""
    rounds = by_round(turns)
    return {
        "rounds": [asdict(r) for r in rounds],
        "spread": {k: (asdict(v) if v else None) for k, v in spread(rounds).items()},
    }


def from_json(turn: dict[str, Any], round_no: int) -> TurnViews | None:
    """A turn from a results file; None for a file written before views were recorded."""
    if "views" not in turn:
        return None
    expected = turn.get("expected_views")
    return TurnViews(
        expected=None if expected is None else frozenset(map(str, expected)),
        actual=frozenset(str(v["view"]) for v in turn["views"]),
        follow_up=bool(turn.get("follow_up")),
        distractor=bool(turn.get("distractor")),
        round_no=round_no,
    )
