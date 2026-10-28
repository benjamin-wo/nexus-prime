"""The owner's cost page: what the AI models cost, from the stored daily rows.

Pure arithmetic over rows read by ``infra.cost_store``. Money is exact: US dollars as decimal
strings (4 places for amounts spent, 2 for projections). Everything is by UTC day. The
window (``days``) is the last ``days`` days up to and including today; ``month`` is the
current calendar month to date, whatever the window is.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

CURRENCY = "USD"
SYSTEM = "System"
_CENTS = Decimal("0.01")
_PARTS = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class Row:
    """One stored row: a day's calls for one user, feature and model."""

    day: date
    user_id: UUID | None
    feature: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost: Decimal
    cached_tokens: int = 0  # part of input_tokens


def amount(value: Decimal) -> str:
    return str(value.quantize(_PARTS, rounding=ROUND_HALF_UP))


def rounded(value: Decimal) -> str:
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def user_label(user_id: UUID, display_name: str | None) -> str:
    """A name for the owner to recognise: their display name, else a short id."""
    name = " ".join((display_name or "").split())
    return name[:60] if name else f"User {str(user_id)[:8]}"


@dataclass(slots=True)
class _Total:
    cost: Decimal = Decimal(0)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def cached_share(self) -> float:
        """The part of the input tokens that came from the provider's cache, 0 to 1."""
        if not self.input_tokens:
            return 0.0
        return float(round(Decimal(self.cached_tokens) / self.input_tokens, 4))

    def add(self, row: Row) -> None:
        self.cost += row.cost
        self.calls += row.calls
        self.input_tokens += row.input_tokens
        self.output_tokens += row.output_tokens
        self.cached_tokens += row.cached_tokens


def _totals[K](rows: list[Row], key: Any) -> dict[K, _Total]:
    found: defaultdict[K, _Total] = defaultdict(_Total)
    for row in rows:
        found[key(row)].add(row)
    return dict(found)


def _by_cost[K](totals: dict[K, _Total], label: Any) -> list[tuple[K, _Total]]:
    """Most expensive first; ties by calls, then by name, so the order never shuffles."""
    return sorted(totals.items(), key=lambda kv: (-kv[1].cost, -kv[1].calls, str(label(kv[0]))))


def month_figures(rows: list[Row], today: date) -> dict[str, Any]:
    """This month to date: spent, and spent so far / days so far x days in the month. Today
    counts as a day, so the first of the month projects from one day of spend. Also the share
    of this month's input tokens that came from the providers' prompt cache."""
    start = today.replace(day=1)
    so_far = _Total()
    for r in rows:
        if start <= r.day <= today:
            so_far.add(r)
    spent = so_far.cost
    in_month = calendar.monthrange(today.year, today.month)[1]
    projected = spent / today.day * in_month
    return {
        "start": start.isoformat(),
        "spent": amount(spent),
        "projected": rounded(projected),
        "days_elapsed": today.day,
        "days_in_month": in_month,
        "cached_share": so_far.cached_share,
    }


def per_active_user_month(rows: list[Row], today: date) -> str:
    """This month's cost that belongs to users, over the users who used a model this month,
    projected to the full month. Work for no one in particular is left out."""
    start = today.replace(day=1)
    mine = [r for r in rows if start <= r.day <= today and r.user_id is not None]
    people = {r.user_id for r in mine}
    if not people:
        return rounded(Decimal(0))
    in_month = calendar.monthrange(today.year, today.month)[1]
    spent = sum((r.cost for r in mine), Decimal(0))
    return rounded(spent / len(people) / today.day * in_month)


def build(rows: list[Row], names: dict[UUID, str | None], today: date, days: int) -> dict[str, Any]:
    """The API's answer. ``rows`` may reach back further than the window (the month can start
    before it); each part reads only what it covers."""
    first = today - timedelta(days=days - 1)
    window = [r for r in rows if first <= r.day <= today]

    per_day: dict[date, _Total] = _totals(window, lambda r: r.day)
    daily = []
    for n in range(days):
        day = first + timedelta(days=n)
        total = per_day.get(day, _Total())
        daily.append({"day": day.isoformat(), "cost": amount(total.cost), "calls": total.calls})

    spent = sum((t.cost for t in per_day.values()), Decimal(0))

    features: dict[str, _Total] = _totals(window, lambda r: r.feature)
    by_feature = [
        {
            "feature": feature,
            "cost": amount(t.cost),
            "calls": t.calls,
            "share": float(round(t.cost / spent, 4)) if spent else 0.0,
        }
        for feature, t in _by_cost(features, lambda f: f)
    ]

    people: dict[UUID | None, _Total] = _totals(window, lambda r: r.user_id)

    def who(user_id: UUID | None) -> str:
        return SYSTEM if user_id is None else user_label(user_id, names.get(user_id))

    by_user = [
        {
            "user_id": None if user_id is None else str(user_id),
            "name": who(user_id),
            "cost": amount(t.cost),
            "calls": t.calls,
        }
        for user_id, t in _by_cost(people, who)
    ]

    models: dict[str, _Total] = _totals(window, lambda r: r.model)
    by_model = [
        {
            "model": model,
            "cost": amount(t.cost),
            "calls": t.calls,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "cached_tokens": t.cached_tokens,
            "cached_share": t.cached_share,
        }
        for model, t in _by_cost(models, lambda m: m)
    ]

    return {
        "currency": CURRENCY,
        "month": month_figures(rows, today),
        "days": daily,
        "by_feature": by_feature,
        "by_user": by_user,
        "by_model": by_model,
        "per_active_user_month": per_active_user_month(rows, today),
    }


def markdown(report: dict[str, Any]) -> str:
    """The same figures as readable text, for pasting into a chat or a ticket."""
    month = report["month"]
    lines = [
        "# Nexus model costs",
        "",
        f"All amounts in {report['currency']}, by UTC day.",
        "",
        f"- This month (from {month['start']}): **{month['spent']}** spent in "
        f"{month['days_elapsed']} of {month['days_in_month']} days, "
        f"projected **{month['projected']}**",
        f"- Per active user, projected for the month: {report['per_active_user_month']}",
        f"- Input tokens served from the cache this month: {month['cached_share']:.1%}",
        "",
        f"## Last {len(report['days'])} days",
        "",
        "| Day | Cost | Calls |",
        "| --- | ---: | ---: |",
        *(f"| {d['day']} | {d['cost']} | {d['calls']} |" for d in report["days"]),
        "",
        "## By feature",
        "",
        "| Feature | Cost | Calls | Share |",
        "| --- | ---: | ---: | ---: |",
        *(
            f"| {f['feature']} | {f['cost']} | {f['calls']} | {f['share']:.1%} |"
            for f in report["by_feature"]
        ),
        "",
        "## By user",
        "",
        "| User | Cost | Calls |",
        "| --- | ---: | ---: |",
        *(f"| {_cell(u['name'])} | {u['cost']} | {u['calls']} |" for u in report["by_user"]),
        "",
        "## By model",
        "",
        "| Model | Cost | Calls | Tokens in | Cached in | Tokens out |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *(
            f"| {_cell(m['model'])} | {m['cost']} | {m['calls']} | {m['input_tokens']} "
            f"| {m['cached_share']:.1%} | {m['output_tokens']} |"
            for m in report["by_model"]
        ),
        "",
    ]
    return "\n".join(lines)


def _cell(text: str) -> str:
    """Text for a table cell: a name can't break out of its column."""
    return text.replace("|", "/").replace("\n", " ")
