"""Health: Nutrition tools. Food figures come from ``application.food_entry`` and
``application.nutrition``: the model names foods and portions, code looks them up and
does the sums."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from nexus.agent.tools.core import Args, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.health import (
    ai_blocked,
    decimal,
    has_consent,
    health_off,
    log_day,
    need_consent,
)
from nexus.agent.tools.helpers import parse_day
from nexus.application import food_entry
from nexus.application import health_targets as targets_cases
from nexus.application import nutrition as nutrition_cases
from nexus.domain.errors import (
    InvalidInput,
)
from nexus.domain.ledger import MenuSection
from nexus.domain.nutrition import Cooking, EntrySource, MealSlot


class FoodItemArgs(Args):
    food: str = Field(
        description="The food as the user said it ('chicken rice', 'egg'), or its id from an "
        "earlier answer of this tool"
    )
    portion: str | None = Field(
        None, description="A serving the user said ('1 cup', '1 plate', '2 slices')"
    )
    grams: str | None = Field(
        None, description="Weight in grams: what the user said, or your estimate (estimated true)"
    )
    estimated: bool = Field(False, description="True when grams is your guess, not the user's")
    cooking: Literal["fried", "stir-fried", "curry/gravy"] | None = Field(
        None, description="Only if the user said how it was cooked"
    )
    modifiers: list[str] = Field(
        default_factory=list, description="'less rice', 'extra gravy': only what the user said"
    )


class LogFoodArgs(Args):
    foods: list[FoodItemArgs] = Field(description="Everything eaten in this meal")
    meal: Literal["breakfast", "lunch", "dinner", "snack"] | None = Field(
        None, description="The meal; left out, it follows the time of day"
    )
    when: str | None = Field(
        None, description="The day, if not today and the user said so: 2026-09-14 or yesterday"
    )


class PhotoItemArgs(FoodItemArgs):
    shown: str | None = None  # the photo's own name for the item, shown in the confirm card


class LogPhotoMealArgs(Args):
    """What the meal-photo flow asks ``log_photo_meal`` to log. Not offered to the model."""

    foods: list[PhotoItemArgs]
    meal: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    when: str | None = None


class FoodTodayArgs(Args):
    day: str | None = Field(
        None, description="'today' (the default), 'yesterday' or a date like 2026-09-14"
    )


def _slot_for(ctx: ToolContext, at: datetime) -> MealSlot:
    hour = at.astimezone(ctx.tz).hour
    if 5 <= hour < 11:
        return MealSlot.BREAKFAST
    if 11 <= hour < 15:
        return MealSlot.LUNCH
    if 17 <= hour < 22:
        return MealSlot.DINNER
    return MealSlot.SNACK


def _food_requests(
    a: LogFoodArgs | LogPhotoMealArgs, *, photo: bool
) -> list[food_entry.FoodRequest]:
    if not a.foods:
        raise InvalidInput("no foods given: ask the user what they ate")
    return [
        food_entry.FoodRequest(
            f.food,
            f.portion,
            decimal(f.grams, "the weight"),
            f.estimated or photo,
            Cooking(f.cooking) if f.cooking else None,
            tuple(f.modifiers),
            photo,
            f.shown if isinstance(f, PhotoItemArgs) else None,
        )
        for f in a.foods
    ]


async def _prepared_meal(
    ctx: ToolContext, a: LogFoodArgs | LogPhotoMealArgs, *, photo: bool
) -> tuple[food_entry.Resolved, MealSlot, datetime | None]:
    at = log_day(ctx, a.when)
    meal = MealSlot(a.meal) if a.meal else _slot_for(ctx, at or ctx.now)
    resolved = await food_entry.resolve(ctx.uow, _food_requests(a, photo=photo))
    return resolved, meal, at


async def _describe_meal(ctx: ToolContext, a: LogFoodArgs | LogPhotoMealArgs, photo: bool) -> str:
    await need_consent(ctx)
    resolved, meal, _ = await _prepared_meal(ctx, a, photo=photo)
    hidden = await nutrition_cases.numbers_hidden(ctx.uow(), ctx.user.id)
    return food_entry.confirm_text(resolved, meal, hidden=hidden, photo=photo)


async def _write_meal(
    ctx: ToolContext, a: LogFoodArgs | LogPhotoMealArgs, photo: bool
) -> ToolResult:
    if not await has_consent(ctx):
        return health_off()
    try:
        resolved, meal, at = await _prepared_meal(ctx, a, photo=photo)
    except food_entry.NeedsAnswer as exc:  # its text is already an "Error: ..." for the model
        return ToolResult(str(exc), error="NeedsAnswer")
    source = EntrySource.PHOTO if photo else EntrySource.CHAT
    await nutrition_cases.log_meal(
        ctx.uow(), ctx.user.id, resolved.inputs, meal, at, source, now=ctx.now
    )
    hidden = await nutrition_cases.numbers_hidden(ctx.uow(), ctx.user.id)
    return ToolResult(
        food_entry.confirm_text(resolved, meal, hidden=hidden, done=True, photo=photo), wrote=True
    )


async def _describe_log_food(ctx: ToolContext, a: LogFoodArgs) -> str:
    return await _describe_meal(ctx, a, False)


async def _log_food(ctx: ToolContext, a: LogFoodArgs) -> ToolResult:
    return await _write_meal(ctx, a, False)


# Only the meal-photo flow (AgentGraph._meal_step) builds this call: the model is never offered
# it, so only code can set the photo source and the estimated range.
async def _describe_log_photo_meal(ctx: ToolContext, a: LogPhotoMealArgs) -> str:
    return await _describe_meal(ctx, a, True)


async def _log_photo_meal(ctx: ToolContext, a: LogPhotoMealArgs) -> ToolResult:
    return await _write_meal(ctx, a, True)


async def _food_today(ctx: ToolContext, a: FoodTodayArgs) -> ToolResult:
    if (blocked := await ai_blocked(ctx)) is not None:
        return blocked
    day = parse_day(ctx, a.day).astimezone(ctx.tz).date() if a.day else None
    targets = None
    if day is None or day == ctx.today():
        found = await targets_cases.safe_targets(ctx.uow, ctx.user.id, now=ctx.now, record=False)
        targets = found.overview.targets
    summary = await nutrition_cases.day_summary(
        ctx.uow(), ctx.user.id, day, targets=targets, now=ctx.now
    )
    names = await nutrition_cases.food_names(
        ctx.uow(), [i.food_id for e in summary.entries for i in e.items]
    )
    return ToolResult(food_entry.day_text(summary, names))


SPECS = (
    ToolSpec(
        "log_food",
        "Log what the user ate, as foods with a serving or a weight. Calories and macros are "
        "worked out by code from the food database: never state or estimate them yourself. "
        "If a food isn't found or is unclear it says what to ask the user. Asks the user to "
        "confirm.",
        LogFoodArgs,
        _log_food,
        confirm=_describe_log_food,
    ),
    ToolSpec(
        "log_photo_meal",
        "Log a meal read from a photo. Used by the photo flow only.",
        LogPhotoMealArgs,
        _log_photo_meal,
        confirm=_describe_log_photo_meal,
        exposed=False,
    ),
    ToolSpec(
        "food_today",
        "What the user ate on a day (today by default), with totals and what is left of "
        "today's targets, as worked out by code. Read-only.",
        FoodTodayArgs,
        _food_today,
    ),
)


READ_ONLY: frozenset[str] = frozenset(
    {
        "food_today",
    }
)

MENU: dict[str, MenuSection] = dict.fromkeys(
    (
        "food_today",
        "log_food",
    ),
    MenuSection.HEALTH,
)
