"""Compare two result files, to tell a regression from a case that was already flaky.

    python -m nexus.evals compare main.json branch.json
    python -m nexus.evals.compare main.json branch.json

Reads the JSON that ``python -m nexus.evals`` writes (a single run or ``--repeat``) and
prints each case's pass rate in both, side by side. A case is flagged when its rates differ
by 2 or more out of N, N being the larger number of runs (so one run each never flags).
Cases that passed every time in both files are left out unless ``--all`` is given.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path

DIFFERENCE = 2  # out of N runs

Rates = dict[str, tuple[int, int]]  # case id -> (passes, runs)


def load_rates(path: Path) -> Rates:
    """Passes and runs per case, from a results file of either shape."""
    data = json.loads(path.read_text())
    runs = data["runs"] if isinstance(data, dict) else data
    rates: Rates = {}
    for run in runs:
        passed, total = rates.get(run["id"], (0, 0))
        rates[run["id"]] = (passed + bool(run["passed"]), total + 1)
    return rates


def differs(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Whether two rates are 2 or more apart out of N, the larger number of runs."""
    n = max(a[1], b[1])
    return abs(Fraction(a[0], a[1]) - Fraction(b[0], b[1])) * n >= DIFFERENCE


def _show(rate: tuple[int, int] | None) -> str:
    return "-" if rate is None else f"{rate[0]}/{rate[1]}"


def report(a: Rates, b: Rates, names: tuple[str, str], *, show_all: bool = False) -> str:
    ids = [*a, *(k for k in b if k not in a)]
    both = [k for k in ids if k in a and k in b]
    flagged = [k for k in both if differs(a[k], b[k])]

    def steady(rate: tuple[int, int] | None) -> bool:
        return rate is not None and rate[0] == rate[1]

    rows = [
        k for k in ids if show_all or k in flagged or not (steady(a.get(k)) and steady(b.get(k)))
    ]
    width = max([len(k) for k in rows] + [len("case")])
    cols = [max(len(n), 5) for n in names]
    lines = [
        f"{'case':<{width}}  {names[0]:>{cols[0]}}  {names[1]:>{cols[1]}}",
        *(
            f"{k:<{width}}  {_show(a.get(k)):>{cols[0]}}  {_show(b.get(k)):>{cols[1]}}"
            + ("  <-" if k in flagged else "")
            for k in rows
        ),
    ]
    if len(rows) < len(ids):
        lines.append(
            f"({len(ids) - len(rows)} cases passed every run in both files; --all shows them)"
        )
    totals = [sum(w for w, _ in r.values()) for r in (a, b)]
    runs = [sum(t for _, t in r.values()) for r in (a, b)]
    lines += [
        "",
        f"Passed overall: {names[0]} {totals[0]}/{runs[0]}, {names[1]} {totals[1]}/{runs[1]}",
        f"Rates differing by {DIFFERENCE} or more out of N: {len(flagged)}",
    ]
    for k in flagged:
        better = names[0] if a[k][0] / a[k][1] > b[k][0] / b[k][1] else names[1]
        lines.append(f"- {k}: {_show(a[k])} vs {_show(b[k])}, better in {better}")
    only = [k for k in ids if k not in a or k not in b]
    if only:
        lines.append(f"In only one file: {', '.join(only)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m nexus.evals compare", description="Compare two eval result files."
    )
    parser.add_argument("first", type=Path, help="results JSON, e.g. from main")
    parser.add_argument("second", type=Path, help="results JSON, e.g. from the branch")
    parser.add_argument("--all", action="store_true", help="list cases that always passed too")
    args = parser.parse_args(argv)
    try:
        rates = [load_rates(p) for p in (args.first, args.second)]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"can't read the results: {type(exc).__name__}: {exc}")
    print(report(rates[0], rates[1], (args.first.stem, args.second.stem), show_all=args.all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
