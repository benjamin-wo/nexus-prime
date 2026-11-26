"""Tools for budgets."""

from uuid import UUID

from pydantic import Field

from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.fx import rates
from nexus.agent.tools.helpers import parse_money, resolve_category
from nexus.application import budgets as budget_cases
from nexus.domain.errors import NotFound


class BudgetArgs(Args):
    amount: str = Field(description="Monthly limit, in the user's home currency")
    category: str | None = Field(
        None, description="Category name; leave out for the overall budget"
    )


class BudgetTargetArgs(Args):
    category: str | None = Field(
        None, description="Category name; leave out for the overall budget"
    )


def _budget_name(category: str | None) -> str:
    return f"{category} budget" if category else "overall budget"


async def _set_budget(ctx: ToolContext, a: BudgetArgs) -> ToolResult:
    category_id = await resolve_category(ctx, a.category)
    limit = parse_money(ctx, a.amount, None)
    await budget_cases.set_budget(ctx.uow(), ctx.user, category_id, limit, now=ctx.now)
    return ToolResult(f"Your {_budget_name(a.category)} is now {limit} a month.", wrote=True)


async def _budgets(ctx: ToolContext, _: NoArgs) -> ToolResult:
    statuses = await budget_cases.budget_statuses(ctx.uow, rates(ctx), ctx.user, now=ctx.now)
    if not statuses:
        return ToolResult("No budgets set.")
    lines = []
    for s in statuses:
        line = f"{s.name}: {s.spent} of {s.budget.limit} this month ({s.percent}%)"
        if s.unconverted:
            line += f"; not counted, no exchange rate: {', '.join(map(str, s.unconverted))}"
        lines.append(line)
    return ToolResult("\n".join(lines))


async def _find_budget(ctx: ToolContext, category: str | None) -> UUID:
    category_id = await resolve_category(ctx, category)
    async with ctx.uow() as tx:
        budgets = await tx.planning.list_budgets(ctx.user.id)
    for b in budgets:
        if b.category_id == category_id:
            return b.id
    raise NotFound(f"there is no {_budget_name(category)}")


async def _describe_remove_budget(ctx: ToolContext, a: BudgetTargetArgs) -> str:
    await _find_budget(ctx, a.category)
    return f"Remove your {_budget_name(a.category)}?"


async def _remove_budget(ctx: ToolContext, a: BudgetTargetArgs) -> ToolResult:
    await budget_cases.remove_budget(ctx.uow(), ctx.user.id, await _find_budget(ctx, a.category))
    return ToolResult(f"Removed your {_budget_name(a.category)}.", wrote=True)


SPECS: list[ToolSpec] = [
    ToolSpec(
        "set_budget",
        "Set or change a monthly budget, overall or for one category.",
        BudgetArgs,
        _set_budget,
    ),
    ToolSpec("list_budgets", "Budgets and how much of each is used this month.", NoArgs, _budgets),
    ToolSpec(
        "remove_budget",
        "Remove a budget. Asks the user to confirm.",
        BudgetTargetArgs,
        _remove_budget,
        confirm=_describe_remove_budget,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"list_budgets"})
