"""A short picture of the user's money, given to the model at the start of each turn.

So "how am I doing?", "anything due this week?" or "move the last one to
Transport" need no lookups first. Everything comes from the user's own data;
each part is built on its own, so one failing leaves the rest, and the whole is
capped in size.
"""

import logging
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from nexus.agent.tools import ToolContext, _rates
from nexus.application import budgets as budget_cases
from nexus.application import cashflow as cashflow_cases
from nexus.application import email as email_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.categories import list_categories
from nexus.application.ports import LedgerQuery
from nexus.domain.ledger import Direction
from nexus.domain.money import Money

log = logging.getLogger(__name__)

MAX_CHARS = 2000
TOP_CATEGORIES = 3
RECENT = 5
AHEAD_DAYS = 7


async def money_snapshot(ctx: ToolContext) -> str:
    """The snapshot as plain lines, or "" if nothing could be read."""
    parts: list[str] = []
    for build in (_emails, _month, _budgets, _ahead, _ious, _recent):
        try:
            text = await build(ctx)
        except Exception:
            log.exception("snapshot part failed: %s", build.__name__)
            continue
        if text:
            parts.append(text)
    text = "\n".join(parts)
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"


def _money(amount: Money) -> str:
    return str(amount)


async def _month(ctx: ToolContext) -> str:
    today = ctx.now.astimezone(ctx.tz).date()
    start = datetime.combine(today.replace(day=1), time(), tzinfo=ctx.tz)
    end = datetime.combine(today + timedelta(days=1), time(), tzinfo=ctx.tz)
    summary = await tx_cases.summarize_in_home(ctx.uow(), _rates(ctx), ctx.user, start, end)
    totals = {t.direction: t for t in summary.totals}
    spent, received = totals[Direction.OUT], totals[Direction.IN]
    line = (
        f"This month so far ({start:%-d %b} to {today:%-d %b}): spent {_money(spent.total)} "
        f"in {spent.count} transactions, received {_money(received.total)}."
    )
    top = [
        f"{c.category_name or 'Uncategorised'} {_money(c.total)}"
        for c in summary.spending_by_category[:TOP_CATEGORIES]
    ]
    if top:
        line += " Top categories: " + ", ".join(top) + "."
    unconverted = spent.unconverted + received.unconverted
    if unconverted:
        line += " Not converted (no rate): " + ", ".join(map(_money, unconverted)) + "."
    return line


async def _budgets(ctx: ToolContext) -> str:
    statuses = await budget_cases.budget_statuses(ctx.uow, _rates(ctx), ctx.user, now=ctx.now)
    if not statuses:
        return ""
    items = [
        f"{s.name} {_money(s.spent)} of {_money(s.budget.limit)} ({s.percent}%, "
        f"{_money(s.remaining)} left)"
        for s in statuses
    ]
    return "Budgets this month: " + "; ".join(items) + "."


async def _ahead(ctx: ToolContext) -> str:
    today = ctx.now.astimezone(ctx.tz).date()
    flow = await cashflow_cases.cash_flow(
        ctx.uow, _rates(ctx), ctx.user, today, today + timedelta(days=AHEAD_DAYS), now=ctx.now
    )
    items = []
    for day in flow.days:
        for e in day.expected:
            amount = f" {_money(e.amount)}" if e.amount is not None else ""
            items.append(f"{day.day:%a %-d %b} {e.kind.value} {e.name}{amount}")
    if not items:
        return f"Next {AHEAD_DAYS} days: no bills, subscriptions or payday due."
    return f"Next {AHEAD_DAYS} days: " + "; ".join(items) + "."


async def _ious(ctx: ToolContext) -> str:
    owed: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for iou in await split_cases.list_open_ious(ctx.uow(), ctx.user.id):
        owed[iou.split.participant_name][iou.outstanding.currency] += iou.outstanding.amount
    if not owed:
        return ""
    items = [
        f"{name} {' + '.join(str(Money(v, c)) for c, v in amounts.items())}"
        for name, amounts in sorted(owed.items())
    ]
    return "Owed to the user: " + ", ".join(items) + "."


async def _emails(ctx: ToolContext) -> str:
    """Emails waiting for an answer, newest first and numbered for answer_email, so
    "log that transfer just now" has something to point at. First, because it's what
    the user is most likely asking about right after a notification."""
    waiting = await email_cases.waiting(ctx.uow(), ctx.user.id, now=ctx.now)
    if not waiting:
        return ""
    lines = [f"{n}) {email_cases.describe(e, ctx.tz)}" for n, e in enumerate(waiting, 1)]
    return "From email, waiting for the user's answer, newest first: " + "; ".join(lines) + "."


async def _recent(ctx: ToolContext) -> str:
    page = await tx_cases.list_ledger(ctx.uow(), ctx.user.id, LedgerQuery(limit=RECENT))
    if not page.items:
        return ""
    names = {
        c.id: c.name for c in await list_categories(ctx.uow(), ctx.user.id, include_inactive=True)
    }
    lines = []
    for t in page.items:
        sign = "-" if t.direction is Direction.OUT else "+"
        who = t.counterparty or t.notes or "?"
        category = names.get(t.category_id, "Uncategorised") if t.category_id else "Uncategorised"
        when = t.occurred_at.astimezone(ctx.tz)
        lines.append(f"{when:%a %-d %b}: {sign}{_money(t.amount)} {who} ({category})")
    return "Latest transactions, newest first: " + "; ".join(lines) + "."
