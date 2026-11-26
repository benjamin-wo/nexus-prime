"""Tools for splitting bills, what people owe and split habits."""

from collections.abc import Iterable

from pydantic import Field

from nexus.agent.tools.core import NEW_PERSON, Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import (
    _load,
    category_map,
    guess_category,
    parse_money,
    resolve_category,
    show,
)
from nexus.application import people as people_cases
from nexus.application import split_habits as habit_cases
from nexus.application import splits as split_cases
from nexus.domain.ledger import (
    ShareRequest,
    plan_split,
)
from nexus.domain.split_habits import parse_share


class Participant(Args):
    name: str
    amount: str | None = Field(
        None, description="Their share; omit on every entry to split equally"
    )


class SplitArgs(Args):
    transaction_id: str
    participants: list[Participant] = Field(min_length=1, description="Everyone except the user")
    include_me: bool = Field(True, description="Whether the user takes an equal share")
    new_person: bool = Field(False, description=NEW_PERSON)


async def _check_people(ctx: ToolContext, names: Iterable[str], new_person: bool) -> None:
    """Refuses a name that is a near miss for someone the user already knows (Anne for Ann),
    so the model asks instead of making a second person; ``new_person`` says it is one."""
    if not new_person:
        await people_cases.check_not_misspelt(ctx.uow(), ctx.user.id, names)


def _requests(ctx: ToolContext, a: SplitArgs, currency: str) -> list[ShareRequest]:
    return [
        ShareRequest(p.name, parse_money(ctx, p.amount, currency) if p.amount else None)
        for p in a.participants
    ]


async def _describe_split(ctx: ToolContext, a: SplitArgs) -> str:
    await _check_people(ctx, [p.name for p in a.participants], a.new_person)
    tx = await _load(ctx, a.transaction_id)
    plan = plan_split(tx.amount, _requests(ctx, a, tx.amount.currency), include_self=a.include_me)
    owed = ", ".join(f"{s.participant_name} owes {s.share}" for s in plan.shares)
    head = (await show(ctx, tx)).split(" [id")[0]
    return f"Split {head}: {owed}; your share {plan.own_share}?"


async def _split(ctx: ToolContext, a: SplitArgs) -> ToolResult:
    await _check_people(ctx, [p.name for p in a.participants], a.new_person)
    tx = await _load(ctx, a.transaction_id)
    result = await split_cases.split_bill(
        ctx.uow(),
        ctx.user.id,
        tx.id,
        _requests(ctx, a, tx.amount.currency),
        include_self=a.include_me,
    )
    owed = ", ".join(f"{s.participant_name} owes {s.share}" for s in result.splits)
    return ToolResult(f"Split recorded: {owed}; your share {result.own_share}.", wrote=True)


class IousArgs(Args):
    name: str | None = Field(None, description="Only this person")


async def _ious(ctx: ToolContext, a: IousArgs) -> ToolResult:
    ious = await split_cases.list_open_ious(ctx.uow(), ctx.user.id, participant_name=a.name)
    if not ious:
        return ToolResult("Nobody owes anything.")
    return ToolResult(
        "\n".join(
            f"{i.split.participant_name} owes {i.outstanding} "
            f"(from {i.expense_occurred_at.astimezone(ctx.tz).date().isoformat()})"
            for i in ious
        )
    )


class SetSplitHabitArgs(Args):
    person: str = Field(description="Who the user splits with")
    applies_to: str | None = Field(
        None,
        description="The category the habit holds for, exact name from the list ('dinners' "
        "and 'meals out' are Dining Out); omit for any expense",
    )
    share: str | None = Field(
        None,
        description="The other person's share of the bill: '50%', '0.4' or '1/3'; omit for "
        "half. With several people call once per person, e.g. 1/3 each for three of you",
    )
    new_person: bool = Field(False, description=NEW_PERSON)


class RemoveSplitHabitArgs(Args):
    person: str
    applies_to: str | None = Field(
        None, description="Only the habit for this category; omit to forget all with this person"
    )


async def _habit_category(ctx: ToolContext, name: str | None, *, strict: bool) -> str | None:
    """The exact name of the category a habit is for. Unknown names are an error when saving
    (``strict``), and left as written when forgetting, so a habit for a category that has
    since been deleted can still be removed."""
    if name is None:
        return None
    category_id = await (resolve_category if strict else guess_category)(ctx, name)
    if category_id is None:
        return name
    return (await category_map(ctx))[category_id].name


async def _set_split_habit(ctx: ToolContext, a: SetSplitHabitArgs) -> ToolResult:
    await _check_people(ctx, [a.person], a.new_person)
    habit = await habit_cases.set_habit(
        ctx.uow(),
        ctx.user.id,
        a.person,
        await _habit_category(ctx, a.applies_to, strict=True),
        parse_share(a.share),
        now=ctx.now,
    )
    return ToolResult(
        f"Saved split habit: {habit.describe()}. From now on it splits matching expenses when "
        "they're logged; expenses already logged aren't changed.",
        wrote=True,
    )


async def _list_split_habits(ctx: ToolContext, _: NoArgs) -> ToolResult:
    habits = await habit_cases.list_habits(ctx.uow(), ctx.user.id)
    if not habits:
        return ToolResult("No split habits saved.")
    return ToolResult("\n".join(h.describe() for h in habits))


async def _remove_split_habit(ctx: ToolContext, a: RemoveSplitHabitArgs) -> ToolResult:
    removed = await habit_cases.remove_habit(
        ctx.uow(),
        ctx.user.id,
        a.person,
        await _habit_category(ctx, a.applies_to, strict=False),
    )
    return ToolResult(
        "Removed split habit: " + "; ".join(h.describe() for h in removed) + ".", wrote=True
    )


SPECS: list[ToolSpec] = [
    ToolSpec(
        "split_bill",
        "Split an expense the user paid with other people. Asks the user to confirm. "
        "The people given replace any split it already has, so list everyone it ends "
        "with: for 'split it with Anne instead' that is Anne alone, not the earlier "
        "people. If the user then corrects a detail ('no, Anne is a new friend') or "
        "undoes the split, build it again from what they asked for, not from the earlier "
        "split.",
        SplitArgs,
        _split,
        confirm=_describe_split,
    ),
    ToolSpec("list_ious", "Who still owes the user money.", IousArgs, _ious),
    ToolSpec(
        "set_split_habit",
        "Save a standing arrangement to split expenses with someone ('I always split "
        "dinners with Ann'): from then on matching expenses are split when logged. Saves "
        "at once. If the same message logs an expense, call this first. Not for splitting "
        "one expense: that is split_bill.",
        SetSplitHabitArgs,
        _set_split_habit,
    ),
    ToolSpec(
        "list_split_habits",
        "The user's standing split arrangements and each person's share.",
        NoArgs,
        _list_split_habits,
    ),
    ToolSpec(
        "remove_split_habit",
        "Forget a standing split arrangement ('stop splitting dinners with Ann').",
        RemoveSplitHabitArgs,
        _remove_split_habit,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"list_ious", "list_split_habits"})
