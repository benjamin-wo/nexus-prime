"""The subscriptions tool."""

from nexus.agent.tools.core import NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.application import subscriptions as subscription_cases


async def _subscriptions(ctx: ToolContext, _: NoArgs) -> ToolResult:
    found = await subscription_cases.overview(ctx.uow(), ctx.user.id)
    if not found.tracked and not found.proposed:
        return ToolResult(
            "No subscriptions are tracked. When the same merchant charges a similar amount "
            "on a regular schedule three times in a row, I'll offer to track it."
        )
    lines = [subscription_cases.describe(v) for v in found.tracked]
    if found.monthly_totals:
        lines.append(
            "About " + " + ".join(str(m) for m in found.monthly_totals) + " a month in all."
        )
    if found.proposed:
        lines.append(
            "Waiting for the user's answer: "
            + ", ".join(v.subscription.name for v in found.proposed)
            + " (Track it / No on the Budgets page)."
        )
    lines.append("To stop tracking one, use the Budgets page.")
    return ToolResult("\n".join(lines))


SPECS: list[ToolSpec] = [
    ToolSpec(
        "list_subscriptions",
        "The user's tracked subscriptions and recurring payments: amount, how often, "
        "the next expected charge, price changes and the monthly total.",
        NoArgs,
        _subscriptions,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"list_subscriptions"})
