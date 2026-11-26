"""Tools that summarise spending and answer questions about the ledger."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from nexus.agent.tools.core import Args, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.fx import rates
from nexus.agent.tools.helpers import (
    category_map,
    day_start,
    describe,
    resolve_category,
    resolve_wallet,
    wallet_map,
)
from nexus.application import ledger_questions as question_cases
from nexus.application import transactions as tx_cases
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
    Source,
)
from nexus.domain.money import Money


class SummaryArgs(Args):
    start_date: str | None = Field(
        None,
        description="YYYY-MM-DD. Default: the 1st of this month, or with group_by month the "
        "start of the ledger (at most 12 months back). A default is not the whole history: "
        "set it for anything earlier, and the result says how far the ledger goes back",
    )
    end_date: str | None = Field(None, description="YYYY-MM-DD inclusive; default: today")


async def _summary(ctx: ToolContext, a: SummaryArgs) -> ToolResult:
    start = (
        day_start(ctx, a.start_date)
        if a.start_date
        else datetime.combine(ctx.today().replace(day=1), time(), tzinfo=ctx.tz)
    )
    end = day_start(ctx, a.end_date or ctx.today().isoformat()) + timedelta(days=1)
    summary = await tx_cases.summarize_in_home(ctx.uow(), rates(ctx), ctx.user, start, end)
    period = f"{start.date().isoformat()} to {(end - timedelta(days=1)).date().isoformat()}"
    if not any(t.count or t.unconverted for t in summary.totals):
        return ToolResult(f"Nothing recorded from {period}.")
    lines = [f"From {period}, in {summary.currency}:"]
    for t in summary.totals:
        if not t.count and not t.unconverted:
            continue
        line = f"money {t.direction.value}: {t.total} ({t.count})"
        if t.converted:
            line += ", including " + ", ".join(str(m) for m in t.converted) + " converted"
        if t.unconverted:
            line += "; not included (no exchange rate): " + ", ".join(str(m) for m in t.unconverted)
        lines.append(line)
    lines += [
        f"  {c.category_name or 'Uncategorised'}: {c.total}" for c in summary.spending_by_category
    ]
    return ToolResult("\n".join(lines))


_DAY_NAMES = {name.lower(): i for i, name in enumerate(question_cases.WEEKDAYS)}


_RECURRING_GROUPS = {
    question_cases.GroupBy.CATEGORY,
    question_cases.GroupBy.MERCHANT,
    question_cases.GroupBy.WEEKDAY,
}


_DAY_SETS = {"weekdays": range(5), "weekends": range(5, 7)}


type DayName = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun", "weekdays", "weekends"]


class QueryArgs(Args):
    start_date: str | None = Field(
        None,
        description="YYYY-MM-DD. Default: the 1st of this month, or with group_by month the "
        "start of the ledger (at most 12 months back). A default is not the whole history: "
        "set it for anything earlier, and the result says how far the ledger goes back",
    )
    end_date: str | None = Field(None, description="YYYY-MM-DD inclusive; default: today")
    direction: Literal["out", "in", "move"] = Field(
        "out",
        description="out: spending; in: money received; move: a transfer between the "
        "user's own wallets (never spending or income)",
    )
    wallet: str | None = Field(
        None, description="With direction move: only transfers into or out of this wallet"
    )
    wallet_side: Literal["into", "out_of", "either"] = Field(
        "into",
        description='With wallet: into counts money transferred into it ("how much did I put '
        'into IBKR"), out_of money transferred out of it, either both',
    )
    merchant: str | None = Field(None, description="Text found in the merchant or notes")
    category: str | None = Field(None, description="A category name, or 'uncategorised'")
    source: Literal["text", "photo", "email", "import", "manual"] | None = None
    min_amount: str | None = Field(None, description="In the home currency, inclusive")
    max_amount: str | None = Field(None, description="In the home currency, inclusive")
    days: list[DayName] | None = Field(None, description="Only these days of the week")
    group_by: Literal["category", "merchant", "day", "week", "month", "weekday"] | None = None
    measure: Literal["total", "count", "average", "largest"] = Field(
        "total", description="What ranks the groups; 'largest' also lists the biggest items"
    )
    top: int = Field(10, ge=1, le=question_cases.MAX_TOP, description="How many groups or items")
    compare_previous: bool = Field(
        False, description="Also the period just before (the previous month for a month)"
    )


def _bound(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise InvalidInput(f"not an amount: {value!r}") from exc


# With group_by month and no start_date, the months shown go back at most this far.
HISTORY_MONTHS = 12


def _default_start(ctx: ToolContext, a: QueryArgs, span: question_cases.LedgerSpan | None) -> date:
    """The start when none was given: the 1st of this month, or for months the 1st of the
    ledger's first month, at most HISTORY_MONTHS months (this one included) back."""
    this_month = ctx.today().replace(day=1)
    if a.group_by != "month" or span is None:
        return this_month
    index = min(span.first.year * 12 + span.first.month, this_month.year * 12 + this_month.month)
    floor = this_month.year * 12 + this_month.month - (HISTORY_MONTHS - 1)
    index = max(index, floor) - 1
    return date(index // 12, index % 12 + 1, 1)


def _default_note(start: date, group_by: str | None, span: question_cases.LedgerSpan | None) -> str:
    """One line for a start the model did not choose, so a default window never reads as the
    whole history: where the ledger really begins."""
    months = group_by == "month"
    if span is None:
        return f"Period defaulted to {_window(months)}. The ledger is empty."
    first = f"{span.first:%-d %b %Y}"
    if span.first >= start:  # the window reaches the first transaction
        whole = "the whole ledger" if months else "this month"
        return f"Period defaulted to {whole}. The ledger begins {first}, so that is all of it."
    return (
        f"Period defaulted to {_window(months)}. "
        f"The ledger goes back to {first}: pass start_date for earlier."
    )


def _window(months: bool) -> str:
    return f"the last {HISTORY_MONTHS} months" if months else "this month"


async def _question(
    ctx: ToolContext, a: QueryArgs, span: question_cases.LedgerSpan | None = None
) -> question_cases.LedgerQuestion:
    start = (
        day_start(ctx, a.start_date)
        if a.start_date
        else datetime.combine(_default_start(ctx, a, span), time(), tzinfo=ctx.tz)
    )
    end = day_start(ctx, a.end_date or ctx.today().isoformat()) + timedelta(days=1)
    uncategorised = a.category is not None and a.category.casefold() in {
        "uncategorised",
        "uncategorized",
    }
    weekdays = None
    if a.days:
        weekdays = frozenset(i for d in a.days for i in (_DAY_SETS.get(d) or (_DAY_NAMES[d],)))
    wallet = await resolve_wallet(ctx, a.wallet) if a.wallet else None
    return question_cases.LedgerQuestion(
        start=start,
        end=end,
        direction=Direction(a.direction),
        wallet_id=wallet.id if wallet and a.wallet_side == "either" else None,
        from_wallet_id=wallet.id if wallet and a.wallet_side == "out_of" else None,
        to_wallet_id=wallet.id if wallet and a.wallet_side == "into" else None,
        search=a.merchant,
        category_id=None if uncategorised else await resolve_category(ctx, a.category),
        uncategorised=uncategorised,
        source=Source(a.source) if a.source else None,
        min_amount=_bound(a.min_amount),
        max_amount=_bound(a.max_amount),
        weekdays=weekdays,
        group_by=question_cases.GroupBy(a.group_by) if a.group_by else None,
        measure=question_cases.Measure(a.measure),
        # Months are listed oldest first and ``top`` cuts the newest: never cut the default window.
        top=max(a.top, HISTORY_MONTHS) if a.group_by == "month" and not a.start_date else a.top,
        compare_previous=a.compare_previous,
    )


def _period(f: question_cases.Figures, tz: ZoneInfo) -> str:
    last = (f.end - timedelta(days=1)).astimezone(tz).date()
    return f"{f.start.astimezone(tz).date().isoformat()} to {last.isoformat()}"


def _change(now: Money, before: Money) -> str:
    diff = now - before
    sign = "+" if diff.amount >= 0 else ""
    if not before.amount:
        return f"{sign}{diff}"
    pct = (diff.amount / before.amount * 100).quantize(Decimal(1))
    return f"{sign}{diff}, {sign}{pct}%"


def _figure_lines(f: question_cases.Figures, tz: ZoneInfo) -> list[str]:
    lines = [
        f"{_period(f, tz)}: {f.total} over {f.count} transaction{'s' * (f.count != 1)}"
        + (f", average {f.average}" if f.count else "")
    ]
    if f.converted:
        lines.append("includes " + ", ".join(str(m) for m in f.converted) + " converted")
    if f.unconverted:
        lines.append("not included (no exchange rate): " + ", ".join(map(str, f.unconverted)))
    if f.truncated:
        lines.append(f"only the latest {question_cases.MAX_ROWS} transactions were counted")
    return lines


def _group_line(g: question_cases.Group, measure: question_cases.Measure) -> str:
    extra = {
        question_cases.Measure.AVERAGE: f", average {g.average}",
        question_cases.Measure.LARGEST: f", largest {g.largest}",
    }.get(measure, "")
    return f"  {g.key}: {g.total} ({g.count}{extra})"


async def _query_ledger(ctx: ToolContext, a: QueryArgs) -> ToolResult:
    span = None if a.start_date else await question_cases.ledger_span(ctx.uow(), ctx.user)
    q = await _question(ctx, a, span)
    answer = await question_cases.ask_ledger(ctx.uow, rates(ctx), ctx.user, q)
    cats = await category_map(ctx)
    wallets = await wallet_map(ctx) if q.direction is Direction.MOVE else None
    now, before = answer.current, answer.previous
    word = {Direction.OUT: "Spent", Direction.IN: "Received", Direction.MOVE: "Transferred"}[
        q.direction
    ]
    head, *notes = _figure_lines(now, ctx.tz)
    lines = [f"{word}, in {answer.currency}, {head}", *notes]
    if not a.start_date:
        lines.append(_default_note(q.start.date(), a.group_by, span))
    if q.direction is Direction.MOVE:
        lines.append("These are transfers between the user's own wallets, not spending or income.")
    if q.group_by:
        lines.append(f"By {q.group_by.value}:")
        lines += [_group_line(g, q.measure) for g in now.groups]
        if now.more_groups:
            lines.append(f"  ({now.more_groups} more not shown)")
    if now.largest and (q.measure is question_cases.Measure.LARGEST or not q.group_by):
        shown = now.largest if q.measure is question_cases.Measure.LARGEST else now.largest[:3]
        lines.append("Largest:")
        for item in shown:
            tx = item.transaction
            home = f" = {item.home}" if item.home.currency != tx.amount.currency else ""
            lines.append(f"  {describe(tx, cats, ctx.tz, wallets)}{home}")
    if before is not None:
        head, *notes = _figure_lines(before, ctx.tz)
        lines += [f"Period before, {head}; change {_change(now.total, before.total)}", *notes]
        # Groups that recur across periods; a day, week or month never does.
        if q.group_by in _RECURRING_GROUPS:
            earlier = {g.key.casefold(): g.total for g in before.groups}
            zero = Money.zero(answer.currency)
            for g in now.groups:
                was = earlier.get(g.key.casefold(), zero)
                lines.append(f"  {g.key}: {was} before, {_change(g.total, was)}")
    return ToolResult("\n".join(lines))


SPECS: list[ToolSpec] = [
    ToolSpec("spending_summary", "Totals for a period, by category.", SummaryArgs, _summary),
    ToolSpec(
        "query_ledger",
        "Answer questions about the user's money in or out, in the home currency: filter "
        "by dates, merchant, category, amount or day of the week; group by category, "
        "merchant, day, week, month or weekday; rank by total, count, average or largest; "
        "compare with the period before. Read-only. Prefer it for any 'how much', "
        "'how often', 'biggest' or 'compare' question over adding up search results. "
        "Without start_date the period is only this month (the last 12 months for "
        "group_by month), not the user's whole history: the result says how far the "
        "ledger goes back, and start_date reaches earlier. For 'per month' or "
        "'previous months' use group_by month. "
        "'How much did I save' means money in minus money out for the period (net), not "
        "transfers into a savings wallet, unless the user names that wallet.",
        QueryArgs,
        _query_ledger,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"query_ledger", "spending_summary"})
