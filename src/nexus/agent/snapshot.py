"""A short picture of the user's money, given to the model at the start of each turn.

So "how am I doing?", "anything due this week?" or "move the last one to
Transport" need no lookups first. Everything comes from the user's own data;
each part is built on its own, so one failing leaves the rest, and the whole is
capped in size.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from nexus.agent.tools import ToolContext
from nexus.agent.tools.fx import rates
from nexus.application import budgets as budget_cases
from nexus.application import cashflow as cashflow_cases
from nexus.application import email as email_cases
from nexus.application import ledger_questions as question_cases
from nexus.application import month_outlook as outlook_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.cashflow import ExpectedKind
from nexus.application.categories import list_categories
from nexus.application.ports import LedgerQuery
from nexus.application.wallet_figures import month_figures
from nexus.application.wallets import list_wallets
from nexus.domain.ledger import Direction, Wallet, WalletKind
from nexus.domain.money import Money
from nexus.domain.planning import next_month_start

log = logging.getLogger(__name__)

MAX_CHARS = 2000
TOP_CATEGORIES = 3
RECENT = 5
AHEAD_DAYS = 7
# The month-end line names at most this many items (payday first); the cap never cuts it.
MONTH_END_ITEMS = 5
# The history line gives the net of at most this many full months before this one.
HISTORY_MONTHS = 3


async def money_snapshot(ctx: ToolContext) -> str:
    """The snapshot as plain lines, or "" if nothing could be read."""
    parts: list[tuple[str, bool]] = []
    # In this order. The month-end line is kept whole when the cap cuts: without it the model
    # can't see a payday more than a week away, and works out "left this month" without it. So
    # is the history line: without it the model takes the month above for all the user's data
    # and says there is no history.
    for build in (
        _cards,
        _emails,
        _month,
        _history,
        _month_end,
        _wallets,
        _budgets,
        _ahead,
        _ious,
        _recent,
    ):
        try:
            text = await build(ctx)
        except Exception:
            log.exception("snapshot part failed: %s", build.__name__)
            continue
        if text:
            parts.append((text, build in _KEPT))
    return _fit(parts)


def _fit(parts: list[tuple[str, bool]]) -> str:
    """The parts as lines, cut from the end to MAX_CHARS, but never a part that is kept."""
    over = sum(len(t) for t, _ in parts) + len(parts) - 1 - MAX_CHARS
    kept: list[str] = []
    for text, keep in reversed(parts):
        if over > 0 and not keep:
            if len(text) <= over:  # all of it goes, with its line break
                over -= len(text) + 1
                continue
            text, over = text[: len(text) - over - 1] + "…", 0
        kept.append(text)
    return "\n".join(reversed(kept))


def _money(amount: Money) -> str:
    return str(amount)


async def _month(ctx: ToolContext) -> str:
    today = ctx.now.astimezone(ctx.tz).date()
    start = datetime.combine(today.replace(day=1), time(), tzinfo=ctx.tz)
    end = datetime.combine(today + timedelta(days=1), time(), tzinfo=ctx.tz)
    summary = await tx_cases.summarize_in_home(ctx.uow(), rates(ctx), ctx.user, start, end)
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


async def _history(ctx: ToolContext) -> str:
    """How far the ledger goes back, and the net (money in less money out) of the last few
    full months, from the same totals as the month line, so "how much do I save per month"
    is not answered from this month alone. Months before the first transaction are left out."""
    span = await question_cases.ledger_span(ctx.uow(), ctx.user)
    if span is None:
        return ""
    this_month = ctx.today().replace(day=1)
    first_month = span.first.replace(day=1)
    months: list[date] = []
    month = this_month
    while len(months) < HISTORY_MONTHS:
        month = (month - timedelta(days=1)).replace(day=1)
        if month < first_month:
            break
        months.append(month)
    line = f"History: from {span.first:%-d %b %Y}"
    if not months:
        return line + " (nothing before this month)."
    nets, unconverted = [], False
    for month in reversed(months):
        start = datetime.combine(month, time(), tzinfo=ctx.tz)
        end = datetime.combine(next_month_start(month), time(), tzinfo=ctx.tz)
        summary = await tx_cases.summarize_in_home(ctx.uow(), rates(ctx), ctx.user, start, end)
        net = summary.income.total - summary.out.total
        # A month with nothing logged is a gap in the ledger, not a month that saved nothing
        # (money_history says the same).
        if not (summary.income.count or summary.out.count):
            shown = "nothing logged"
        else:
            shown = "0.00" if not net.amount else outlook_cases.plain(net, signed=True)
        nets.append(f"{month:%b} {shown}")
        unconverted = unconverted or bool(summary.out.unconverted or summary.income.unconverted)
    line += f". Net by month (in minus out, {ctx.user.home_currency}): {', '.join(nets)}."
    if months[-1] > first_month:
        line += " Earlier months: query_ledger by month."
    if unconverted:
        line += " Amounts with no rate are left out."
    return line


async def _month_end(ctx: ToolContext) -> str:
    """What is still expected from today to month end, so a payday a fortnight away is seen
    (the 7-day line below only shows the next week). Payday first, then by date."""
    today = ctx.today()
    last = next_month_start(today) - timedelta(days=1)
    found = await cashflow_cases.expected_between(
        ctx.uow, rates(ctx), ctx.user, today, last, now=ctx.now
    )
    items = outlook_cases.items_of(found)
    if not items:
        return f"Expected by month end ({last:%-d %b}): nothing, no bills, subscriptions or payday."
    sums = outlook_cases.sum_expected(items, ctx.user.home_currency)
    ranked = sorted(items, key=lambda i: (i.kind is not ExpectedKind.SALARY, i.day, i.name))
    named = []
    for i in ranked[:MONTH_END_ITEMS]:
        if i.amount is None:
            amount = " no amount"
        else:
            amount = (
                f" {'+' if i.direction is Direction.IN else '-'}{outlook_cases.plain(i.amount)}"
            )
        what = "payday" if i.kind is ExpectedKind.SALARY else i.name
        named.append(f"{what} {i.day:%-d %b}{amount}")
    if len(ranked) > MONTH_END_ITEMS:
        named.append(f"+{len(ranked) - MONTH_END_ITEMS} more")
    return (
        f"Expected by month end ({ctx.user.home_currency}; bills, subscriptions and payday only, "
        f"not everyday spending): in {outlook_cases.plain(sums.money_in)}, "
        f"out {outlook_cases.plain(sums.money_out)} ({', '.join(named)})."
    )


# Never cut by the size cap (see money_snapshot).
_KEPT = frozenset({_month_end, _history})


async def _cards(ctx: ToolContext) -> str:
    """Simple mode: the user doesn't track which card paid. Said first, so the size cap
    never cuts it. Paying a card's bill is a move and is not affected."""
    if ctx.user.track_cards:
        return ""
    return (
        "Card tracking is off: don't ask which card paid an expense, and don't pass paid_with "
        "or set a usual card. Paying a card bill is a transfer and works as always."
    )


def _wallet_facts(w: Wallet, usual: bool) -> list[str]:
    facts = [w.kind.value]
    if w.last4:
        facts.append(f"ending {w.last4}")
    facts += [f"also {m}" for m in w.match_words]
    if usual:
        facts.append("the usual card")
    return facts


async def _wallets(ctx: ToolContext) -> str:
    """The user's wallets, so a transfer's wallet can be named, and what they saved this
    month, and which card is the usual one. Only once they have a wallet besides the main
    account and Cash, which everyone has."""
    wallets = await list_wallets(ctx.uow(), ctx.user.id)
    others = [w for w in wallets if w.kind is not WalletKind.SPENDING]
    if all(w.kind is WalletKind.CASH for w in others):
        return ""
    usual_id = ctx.user.usual_card_wallet_id if ctx.user.track_cards else None
    names = ", ".join(f"{w.name} ({', '.join(_wallet_facts(w, w.id == usual_id))})" for w in others)
    line = f"Wallets besides the main account: {names}."
    figures = await month_figures(ctx.uow, rates(ctx), ctx.user, now=ctx.now)
    away = f"Saved this month: {_money(figures.put_away)}"
    if figures.saving_rate is not None:
        away += f" ({(figures.saving_rate * 100).quantize(Decimal(1))}% of income)"
    return f"{line} {away}."


async def _budgets(ctx: ToolContext) -> str:
    statuses = await budget_cases.budget_statuses(ctx.uow, rates(ctx), ctx.user, now=ctx.now)
    if not statuses:
        return ""
    items = [
        f"{s.name} {_money(s.spent)} of {_money(s.budget.limit)} ({s.percent}%, "
        f"{_money(s.remaining)} left)"
        for s in statuses
    ]
    text = "Budgets this month: " + "; ".join(items) + "."
    if any(s.budget.is_overall for s in statuses):
        text += " (Left is before bills still due; month_outlook has it after them.)"
    return text


async def _ahead(ctx: ToolContext) -> str:
    today = ctx.now.astimezone(ctx.tz).date()
    flow = await cashflow_cases.cash_flow(
        ctx.uow, rates(ctx), ctx.user, today, today + timedelta(days=AHEAD_DAYS), now=ctx.now
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
    names = {c.id: c.name for c in await list_categories(ctx.uow(), ctx.user.id)}
    wallets = {w.id: w.name for w in await list_wallets(ctx.uow(), ctx.user.id)}
    lines = []
    for t in page.items:
        when = t.occurred_at.astimezone(ctx.tz)
        if t.direction is Direction.MOVE:
            to = wallets.get(t.to_wallet_id, "another wallet") if t.to_wallet_id else "?"
            lines.append(f"{when:%a %-d %b}: {_money(t.amount)} → {to} (transfer)")
            continue
        sign = "-" if t.direction is Direction.OUT else "+"
        who = t.counterparty or t.notes or "?"
        category = names.get(t.category_id, "Uncategorised") if t.category_id else "Uncategorised"
        lines.append(f"{when:%a %-d %b}: {sign}{_money(t.amount)} {who} ({category})")
    return "Latest transactions, newest first: " + "; ".join(lines) + "."
