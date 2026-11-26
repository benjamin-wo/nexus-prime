"""What the Health tools share: the consent checks and the day and number parsing for logs.

Every figure in the Health tools' text comes from the application layer; the model quotes it
and never works it out.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from nexus.agent.tools.core import ToolContext, ToolResult
from nexus.agent.tools.helpers import parse_day
from nexus.application import food_entry
from nexus.application import gym as gym_cases
from nexus.domain.errors import ConsentRequired, InvalidInput

HEALTH_OFF = (
    "Error: Health is off, so nothing was changed. Nexus keeps workouts only once the user "
    "agrees to it: tell them to open the Health section of the app and agree to Nexus keeping "
    "their health data, then ask again."
)


def health_off() -> ToolResult:
    return ToolResult(HEALTH_OFF, error="ConsentRequired")


async def has_consent(ctx: ToolContext) -> bool:
    return await gym_cases.consent(ctx.uow(), ctx.user.id) is not None


async def need_consent(ctx: ToolContext) -> None:
    """For a confirm card: no card for a write that will be refused."""
    if not await has_consent(ctx):
        raise ConsentRequired(HEALTH_OFF)


async def ai_blocked(ctx: ToolContext) -> ToolResult | None:
    """The reply for a tool that puts the user's past health data in front of the model, when
    they haven't allowed it (Health consent plus the AI processing scope)."""
    if await food_entry.ai_may_read(ctx.uow(), ctx.user.id):
        return None
    return ToolResult(food_entry.AI_OFF, error="ConsentRequired")


def local_day(ctx: ToolContext, at: datetime) -> date:
    return at.astimezone(ctx.tz).date()


def decimal(text: str | None, what: str) -> Decimal | None:
    if text is None or not text.strip():
        return None
    try:
        return Decimal(text.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise InvalidInput(f"{what} {text!r} isn't a number") from exc


def log_day(ctx: ToolContext, when: str | None) -> datetime | None:
    """An earlier day the user named, else None (now)."""
    if not when:
        return None
    at = parse_day(ctx, when)
    if local_day(ctx, at) > ctx.today():
        raise InvalidInput("can't log a workout in the future")
    return at if local_day(ctx, at) < ctx.today() else None
