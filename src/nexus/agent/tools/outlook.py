"""Tools for cash flow, the month outlook, money history, sums and updates."""

from datetime import time, timedelta

from pydantic import Field

from nexus.agent.outlook_text import (
    describe_calculation,
    describe_money_history,
    describe_outlook,
)
from nexus.agent.tools.core import Args, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.fx import rates
from nexus.application import cashflow as cashflow_cases
from nexus.application import money_history as history_cases
from nexus.application import month_outlook as outlook_cases
from nexus.application import notifications as notify_cases
from nexus.domain.calc import calculate
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
)
from nexus.domain.notifications import Frequency


class CashFlowArgs(Args):
    days: int = Field(30, ge=1, le=60, description="How many days ahead, from today")


async def _cash_flow(ctx: ToolContext, a: CashFlowArgs) -> ToolResult:
    today = ctx.today()
    flow = await cashflow_cases.cash_flow(
        ctx.uow, rates(ctx), ctx.user, today, today + timedelta(days=a.days - 1), now=ctx.now
    )
    lines = []
    for d in flow.days:
        for e in d.expected:
            sign = "+" if e.direction is Direction.IN else "-"
            amount = f"{sign}{e.amount}" if e.amount else "amount not set"
            lines.append(f"{d.day:%a %-d %b}: {e.name} ({e.kind.value}) {amount}")
    if not lines:
        return ToolResult(
            f"Nothing expected in the next {a.days} days: no bills, tracked subscriptions "
            "or payday fall in it."
        )
    net = flow.expected_in - flow.expected_out
    lines.append(
        f"Expected in the next {a.days} days: in {flow.expected_in}, out {flow.expected_out}, "
        f"net {net}. Only bills, tracked subscriptions and payday; not everyday spending, "
        "and not a balance."
    )
    if flow.unknown_amounts:
        lines.append(f"{flow.unknown_amounts} item(s) have no amount set, so aren't counted.")
    return ToolResult("\n".join(lines))


class AdjustmentArgs(Args):
    amount: str = Field(
        description='Signed, in the home currency: "+2,308.42" or "4000" for money the user '
        'has or expects, "-500" for something they are thinking of spending. A written sum '
        'like "4000 + 798" is fine.'
    )
    label: str = Field(
        "", description="What it is, in the user's words (carried over from October)"
    )


class MonthOutlookArgs(Args):
    month: str | None = Field(
        None,
        description="YYYY-MM; this month when left out. A month that is over gives what "
        "happened, with no projection.",
    )
    adjustments: list[AdjustmentArgs] = Field(
        default_factory=list,
        description="Every amount the user mentioned that isn't in their data yet: a "
        "carry-over from last month, money they expect, or a purchase they are considering "
        "(negative). Code adds them to the month's figure. Pass them all, again, whenever "
        "you re-run this after a correction.",
    )


async def _month_outlook(ctx: ToolContext, a: MonthOutlookArgs) -> ToolResult:
    outlook = await outlook_cases.month_outlook(
        ctx.uow,
        rates(ctx),
        ctx.user,
        now=ctx.now,
        month=a.month,
        adjustments=[(x.amount, x.label) for x in a.adjustments],
    )
    return ToolResult(describe_outlook(outlook))


class MoneyHistoryArgs(Args):
    months: int = Field(
        history_cases.DEFAULT_MONTHS,
        description="How many full months back to show (default 6, at most 12). The current "
        "month so far is always added, marked as not over.",
    )


async def _money_history(ctx: ToolContext, a: MoneyHistoryArgs) -> ToolResult:
    history = await history_cases.money_history(
        ctx.uow, rates(ctx), ctx.user, now=ctx.now, months=a.months
    )
    return ToolResult(describe_money_history(history))


class CalculateArgs(Args):
    expression: str = Field(
        description="Numbers with + - * / and brackets, e.g. 1,234.50 + 987.25 - 42 or "
        "186.40 / 3. Commas and a currency code are fine. A percentage is a decimal: 18% "
        "of 2350 is 0.18 * 2350."
    )


async def _calculate(_: ToolContext, a: CalculateArgs) -> ToolResult:
    return ToolResult(describe_calculation(calculate(a.expression)))


class UpdatesArgs(Args):
    frequency: Frequency | None = Field(
        None,
        description="instant: each transaction as it happens; hourly (8am-9pm); "
        "thrice_daily (9am, 2pm, 8pm); daily: one summary a day, at 9pm unless the user "
        "picks a time (the default); off. Leave empty to only say what it is now.",
    )
    at: str | None = Field(
        None,
        description="For daily only: the time the user wants it, 24-hour HH:MM in their "
        'own timezone ("11:59pm" is 23:59, "7am" is 07:00)',
    )


async def _updates(ctx: ToolContext, a: UpdatesArgs) -> ToolResult:
    if a.frequency is None and a.at is None:
        current = await notify_cases.get_settings(ctx.uow(), ctx.user.id)
        return ToolResult(notify_cases.describe(current))
    daily_at = None
    if a.at is not None:
        try:
            daily_at = time.fromisoformat(a.at.strip())
        except ValueError as exc:
            raise InvalidInput("give the time as HH:MM, 24-hour, e.g. 23:59") from exc
    updated = await notify_cases.set_frequency(
        ctx.uow(), ctx.user.id, a.frequency or Frequency.DAILY, now=ctx.now, daily_at=daily_at
    )
    return ToolResult("Done. " + notify_cases.describe(updated), wrote=True)


SPECS: list[ToolSpec] = [
    ToolSpec(
        "cash_flow",
        "What's expected to come in and go out over the next days: bills, tracked "
        "subscriptions and payday, with the net. Not a balance.",
        CashFlowArgs,
        _cash_flow,
    ),
    ToolSpec(
        "month_outlook",
        "Where a month ends up, worked out exactly in code: received, spent and net so "
        "far, what is still expected by month end (bills, tracked subscriptions, payday, "
        "scheduled moves), the projected month-end net and the headroom: how much more "
        "everyday spending keeps it at zero or above. Use it for can I afford, how much "
        "is left to spend, leeway, will I end the month positive, net by month end, "
        "budget left. Pass amounts the user mentions (a carry-over, money they expect, a "
        "purchase they are considering) as adjustments. With a budget, it opens with the "
        "budget room line: that is the answer to how much can I spend / afford / left to "
        "spend, never the month-end net, which counts pay not yet received (never money "
        "to spend). Say plainly when the budget is tight or over. It also gives days left, "
        "the room per day and the pace of everyday spending so far, and how they compare: "
        "use it for how much is that per day, daily, days left, my pace, how does that "
        "compare to my usual. Not an account balance.",
        MonthOutlookArgs,
        _month_outlook,
    ),
    ToolSpec(
        "money_history",
        "What the user saves, month by month, worked out exactly in code: for each of the "
        "last full months (6 by default) received, spent, net (received less spent, which "
        "is what saved means), what moved to their own savings or investment wallets and "
        "the saving rate, plus this month so far; then the average net and saving rate, "
        "the best and worst month, and the figures to ground a suggestion in (average "
        "spent, usual salary, 20% of it, their average net as a share of it). Use it for "
        "how much do I save (per month), savings for previous months, savings rate, how "
        "much should or could I save, am I saving more than before. Not an account "
        "balance.",
        MoneyHistoryArgs,
        _money_history,
    ),
    ToolSpec(
        "calculate",
        "Exact arithmetic on money figures: + - * / and brackets. Use it for every sum, "
        "difference, product, share or comparison of amounts; never do them yourself.",
        CalculateArgs,
        _calculate,
    ),
    ToolSpec(
        "transaction_updates",
        "How often the user gets Telegram messages about their transactions: each "
        "one as it happens, or a summary hourly, 3 times a day or at the end of the "
        "day (the default), or off. Shows or changes the setting.",
        UpdatesArgs,
        _updates,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"calculate", "cash_flow", "money_history", "month_outlook"})
