"""Health: weight and profile by chat, and bringing up a screen. Prime fills things in from
what the user says and asks only for what a feature needs. These tools write at once (no
confirm card); the reply is built in code and carries its own Undo."""

from typing import Literal

from pydantic import Field

from nexus.agent.links import app_link
from nexus.agent.tools.core import Args, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.health import decimal, has_consent, health_off_tap, open_row
from nexus.agent.tools.helpers import parse_day
from nexus.agent.view_links import VIEWS
from nexus.application import energy as energy_cases
from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.domain.errors import InvalidInput
from nexus.domain.health import (
    ActivityLevel,
    Goal,
    HealthProfile,
    SampleKind,
    SampleSource,
    SampleUnit,
    Sex,
)
from nexus.domain.health_texts import GATE_TEXT
from nexus.domain.ledger import MenuSection

GOAL_WORDS = {
    Goal.LOSE: "lose weight",
    Goal.MAINTAIN: "maintain weight",
    Goal.GAIN: "gain weight",
    Goal.PERFORMANCE: "performance",
}


class LogWeightArgs(Args):
    value: str = Field(description="The weight, the number only: 82.4")
    unit: Literal["kg", "lb"] | None = Field(
        None, description="Only if the user said it; left out, the unit they use in the app"
    )
    when: str | None = Field(
        None, description="The day, if not today and the user said so: 2026-09-14 or yesterday"
    )


def _trend_sentence(overview: energy_cases.WeightOverview, *, hidden: bool) -> str:
    """ "Your trend is slowly down, about 0.3 kg a week." Built from the trend, in code."""
    if overview.rate is None:
        return "There aren't enough weigh-ins yet to say which way your trend is going."
    words = overview.trend_words
    if words == "steady":
        return "Your trend is steady."
    if hidden:
        return f"Your trend is {words}."
    return f"Your trend is {words}, about {abs(overview.rate[0]):.1f} kg a week."


async def _log_weight(ctx: ToolContext, a: LogWeightArgs) -> ToolResult:
    if not await has_consent(ctx):
        return health_off_tap()
    value = decimal(a.value, "the weight")
    if value is None:
        raise InvalidInput("what is the weight?")
    unit = SampleUnit(a.unit or (await gym_cases.weight_unit(ctx.uow(), ctx.user.id)).value)
    at = parse_day(ctx, a.when)
    if at.astimezone(ctx.tz).date() > ctx.today():
        raise InvalidInput("can't log a weight in the future")
    sample = await health_cases.log_sample(
        ctx.uow(),
        ctx.user.id,
        SampleKind.WEIGHT,
        value,
        unit=unit,
        start_at=None if a.when is None or at.astimezone(ctx.tz).date() == ctx.today() else at,
        source=SampleSource.CHAT,
        now=ctx.now,
    )
    overview = await energy_cases.weight_overview(ctx.uow(), ctx.user.id, now=ctx.now)
    trend = _trend_sentence(overview, hidden=overview.hidden)
    logged = "Logged." if overview.hidden else f"Logged {sample.value.normalize():f} {unit.value}."
    row = [("Undo", f"weight:undo:{sample.id}")]
    link = app_link(ctx.origin, VIEWS["health.weight_trend"].path)
    if link:
        row.append(("See trend", link))
    return ToolResult(f"{logged} {trend}", wrote=True, buttons=[row], own_undo=True)


class UpdateProfileArgs(Args):
    height_cm: str | None = Field(None, description="Height in centimetres: 180")
    birth_year: int | None = Field(
        None, description="Year of birth: 1990 (from an age, work it out)"
    )
    sex: Literal["female", "male", "unspecified"] | None = Field(
        None, description="Used only for the energy estimate"
    )
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] | None = (
        Field(None, description="How active the user is day to day")
    )
    goal: Literal["lose", "maintain", "gain", "performance"] | None = Field(
        None, description="What the user wants to do about their weight"
    )
    target_rate: str | None = Field(
        None, description="Percent of body weight per week, only if the user named a pace"
    )
    numbers_free: bool | None = Field(
        None, description="True to hide numbers (calories, weights), false to show them again"
    )
    ed_history: bool | None = Field(
        None, description="True only if the user said they have had an eating disorder"
    )


def _said_saved(a: UpdateProfileArgs, saved: HealthProfile, *, hidden: bool) -> list[str]:
    """What was saved, as short phrases; numbers left out in numbers-free mode."""
    parts: list[str] = []
    if a.height_cm is not None and saved.height_cm is not None:
        parts.append("your height" if hidden else f"height {saved.height_cm.normalize():f} cm")
    if a.birth_year is not None:
        parts.append("your birth year" if hidden else f"birth year {saved.birth_year}")
    if a.sex is not None:
        parts.append("sex (used only for the energy estimate)")
    if a.activity_level is not None and saved.activity_level is not None:
        parts.append(f"activity level {saved.activity_level.value.replace('_', ' ')}")
    if a.goal is not None and saved.goal.value == a.goal:
        parts.append(f"goal: {GOAL_WORDS[saved.goal]}")
    if a.target_rate is not None and saved.target_rate_pct_per_week is not None:
        parts.append(
            "your weekly pace"
            if hidden
            else f"pace {saved.target_rate_pct_per_week.normalize():f}% of body weight a week"
        )
    if a.numbers_free is not None:
        parts.append("numbers hidden" if saved.numbers_free else "numbers shown")
    if a.ed_history:
        parts.append("what you told me about your eating history")
    return parts


async def _update_health_profile(ctx: ToolContext, a: UpdateProfileArgs) -> ToolResult:
    if not await has_consent(ctx):
        return health_off_tap()
    height = decimal(a.height_cm, "the height")
    rate = decimal(a.target_rate, "the pace")
    if (
        height is None
        and rate is None
        and all(
            v is None
            for v in (a.birth_year, a.sex, a.activity_level, a.goal, a.numbers_free, a.ed_history)
        )
    ):
        raise InvalidInput("nothing to save: pass only what the user said")
    done = await health_cases.update_profile(
        ctx.uow,
        ctx.user.id,
        now=ctx.now,
        sex_for_equations=Sex(a.sex) if a.sex else None,
        birth_year=a.birth_year,
        height_cm=height,
        activity_level=ActivityLevel(a.activity_level) if a.activity_level else None,
        goal=Goal(a.goal) if a.goal else None,
        target_rate_pct_per_week=rate,
        numbers_free=a.numbers_free,
        ed_history=a.ed_history,
    )
    saved = done.saved.profile
    parts = _said_saved(a, saved, hidden=saved.numbers_free)
    lines = [f"Saved {', '.join(parts)}." if parts else "Saved."]
    held_back = done.asked_goal is Goal.LOSE and saved.goal is not Goal.LOSE
    if held_back:
        why = GATE_TEXT.get(done.saved.gate.reason.value, "")
        lines.append(f"I haven't set a weight-loss goal. {why}".strip())
    return ToolResult(
        " ".join(lines),
        wrote=True,
        buttons=[[("Undo", f"profile:undo:{done.undo_token}")]],
        own_undo=True,
    )


class ShowArgs(Args):
    view: Literal[
        "health.today",
        "health.weight_trend",
        "health.workout",
        "health.records",
        "finance.month_outlook",
        "finance.budgets",
        "travel.trips",
        "invest.portfolio",
    ] = Field(description="Which screen to bring up")


async def _show(ctx: ToolContext, a: ShowArgs) -> ToolResult:
    shown = VIEWS.get(a.view)
    if shown is None:
        raise InvalidInput(f"no such view; use one of: {', '.join(VIEWS)}")
    row = open_row(ctx, a.view)
    if row:
        return ToolResult(shown.line, buttons=[row])
    return ToolResult(f"{shown.line} It's in the app, under {shown.where}.")


SPECS = (
    ToolSpec(
        "log_weight",
        "Log the user's weight straight away (no confirmation), for 'I weigh 82 kg', 'I'm 180 "
        "lb' or 'weighed in at 74.5 this morning'. Its reply says what was logged and which way "
        "the trend is going, with an Undo button: quote it as it is, and add no figures of "
        "your own.",
        LogWeightArgs,
        _log_weight,
    ),
    ToolSpec(
        "update_health_profile",
        "Save what the user said about themselves, straight away and without asking: height, "
        "birth year (from an age), sex, how active they are, a weight goal and pace, hiding "
        "numbers, or an eating-disorder history. Pass only what they said. The app's safety "
        "rules apply, and its reply says what was saved and any goal that was held back, "
        "with an Undo button: quote it as it is. Never ask the user to fill in a profile.",
        UpdateProfileArgs,
        _update_health_profile,
    ),
    ToolSpec(
        "show",
        "Bring up a screen of the app for 'show me my weight trend', 'open my budgets', 'show "
        "my trips'. Reads nothing out: it says one line and gives an Open button. Views: "
        "health.today, health.weight_trend, health.workout, health.records, "
        "finance.month_outlook, finance.budgets, travel.trips, invest.portfolio. For a "
        "question about figures, use the tool that answers it instead.",
        ShowArgs,
        _show,
    ),
)


READ_ONLY: frozenset[str] = frozenset({"show"})

MENU: dict[str, MenuSection] = dict.fromkeys(
    ("log_weight", "update_health_profile"), MenuSection.HEALTH
)
