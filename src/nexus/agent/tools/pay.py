"""Tools for the pay schedule and usual salary."""

from typing import Literal

from pydantic import Field

from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import parse_day, parse_money
from nexus.application import salary as salary_cases
from nexus.application import transactions as tx_cases
from nexus.domain.errors import InvalidInput
from nexus.domain.planning import PayRule


class PayScheduleArgs(Args):
    rule: Literal["day_of_month", "last_weekday", "every_two_weeks"] | None = Field(
        None, description="Leave out to only name who pays them; the schedule stays as it is"
    )
    day: int | None = Field(None, description="1-31, for day_of_month")
    next_payday: str | None = Field(None, description="YYYY-MM-DD, for every_two_weeks")
    payer: str | None = Field(
        None,
        description="Who pays their salary (the employer), as they said it: Acme. "
        "'none' clears it. Leave out to keep what's saved",
    )


class SalaryArgs(Args):
    amount: str = Field(description="The usual salary, as the user stated it")
    currency: str | None = None


_RULES = {
    "day_of_month": PayRule.MONTHLY_DAY,
    "last_weekday": PayRule.LAST_WEEKDAY,
    "every_two_weeks": PayRule.BIWEEKLY,
}


def _pay_line(view: salary_cases.PayView) -> str:
    s = view.schedule
    usual = f" Usual salary: {s.baseline}." if s.baseline else " No usual salary saved."
    if s.payer:
        usual += f" Paid by {s.payer}."
    when = "today" if view.days_until == 0 else f"{view.next_payday:%a %-d %b}"
    return (
        f"Paid on {salary_cases.describe_rule(s)} (weekend paydays move to Friday). "
        f"Next payday: {when}.{usual}"
    )


async def _set_pay_schedule(ctx: ToolContext, a: PayScheduleArgs) -> ToolResult:
    payer: tx_cases.Maybe[str | None] = tx_cases.UNSET
    if a.payer is not None:
        payer = None if a.payer.strip().lower() in {"none", "no"} else a.payer
    if a.rule is None:
        if payer is tx_cases.UNSET:
            raise InvalidInput("say when they're paid, or who pays them")
        await salary_cases.set_payer(ctx.uow(), ctx.user, payer, now=ctx.now)
    else:
        anchor = parse_day(ctx, a.next_payday).astimezone(ctx.tz).date() if a.next_payday else None
        await salary_cases.set_schedule(
            ctx.uow(), ctx.user, _RULES[a.rule], day=a.day, anchor=anchor, payer=payer, now=ctx.now
        )
    view = await salary_cases.view(ctx.uow(), ctx.user, now=ctx.now)
    return ToolResult(_pay_line(view) if view else "Saved.", wrote=True)


async def _pay_schedule(ctx: ToolContext, _: NoArgs) -> ToolResult:
    view = await salary_cases.view(ctx.uow(), ctx.user, now=ctx.now)
    return ToolResult(_pay_line(view) if view else "No pay schedule set.")


async def _describe_usual_salary(ctx: ToolContext, a: SalaryArgs) -> str:
    return f"Make {parse_money(ctx, a.amount, a.currency)} your usual salary?"


async def _set_usual_salary(ctx: ToolContext, a: SalaryArgs) -> ToolResult:
    amount = parse_money(ctx, a.amount, a.currency)
    await salary_cases.set_baseline(ctx.uow(), ctx.user, amount, now=ctx.now)
    return ToolResult(f"Your usual salary is now {amount}.", wrote=True)


async def _describe_remove_pay(ctx: ToolContext, _: NoArgs) -> str:
    return "Remove your pay schedule and usual salary? Payday check-ins will stop."


async def _remove_pay(ctx: ToolContext, _: NoArgs) -> ToolResult:
    await salary_cases.remove_schedule(ctx.uow(), ctx.user.id)
    return ToolResult("Removed your pay schedule.", wrote=True)


SPECS: list[ToolSpec] = [
    ToolSpec(
        "set_pay_schedule",
        "Set when the user is paid and/or who pays them (the employer, named on their "
        "salary entries), as they told you.",
        PayScheduleArgs,
        _set_pay_schedule,
    ),
    ToolSpec("show_pay_schedule", "When the user is paid next.", NoArgs, _pay_schedule),
    ToolSpec(
        "set_usual_salary",
        "Change the user's usual salary. Asks the user to confirm.",
        SalaryArgs,
        _set_usual_salary,
        confirm=_describe_usual_salary,
    ),
    ToolSpec(
        "remove_pay_schedule",
        "Stop tracking the user's pay. Asks the user to confirm.",
        NoArgs,
        _remove_pay,
        confirm=_describe_remove_pay,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"show_pay_schedule"})
