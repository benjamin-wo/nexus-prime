"""Alerts during the US session: what a live price says about a plan, and what a big move
in a day is. Pure rules, no I/O.

A plan is followed on daily bars after the close (see ``domain.plans``); these rules look
at the live price in between. An alert is kept once per user, stock, kind and trading day.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.domain.ledger import UserId
from nexus.domain.market import percent
from nexus.domain.plans import EventKind, SavedPlan


class AlertKind(StrEnum):
    PLAN_ENTRY = "plan_entry"  # the price is in (or through) the plan's buy zone
    PLAN_STOP = "plan_stop"  # at or below the plan's stop
    PLAN_TARGET = "plan_target"  # at or above the plan's first target
    BIG_MOVE = "big_move"  # up or down by the user's threshold or more in a day


# The plan event each plan alert is the live version of.
EVENT_OF = {
    AlertKind.PLAN_ENTRY: EventKind.ENTRY,
    AlertKind.PLAN_STOP: EventKind.STOPPED,
    AlertKind.PLAN_TARGET: EventKind.TARGET,
}
KIND_OF = {event: kind for kind, event in EVENT_OF.items()}


@dataclass(frozen=True, slots=True)
class MarketAlert:
    id: UUID
    user_id: UserId
    symbol: str
    kind: AlertKind
    day: date  # the New York trading date
    text: str
    urgent: bool
    created_at: datetime
    sent_at: datetime | None = None  # None while it waits for the morning summary


def plan_alerts(plan: SavedPlan, price: Decimal, *, holds: bool) -> list[AlertKind]:
    """What a live ``price`` says about an open plan, for a user who ``holds`` the stock
    or not.

    - Entry: a plan not yet entered, whose price is at or below the top of its buy zone
      but above its stop (below that the setup is broken, not a chance to buy).
    - Stop: a plan that is entered or about a stock already held (or that the user
      holds), at or below its stop.
    - Target: the same, at or above its first target.
    """
    entered = plan.entered_on is not None or plan.held
    found: list[AlertKind] = []
    if not entered and plan.entry_high is not None and price <= plan.entry_high:
        if plan.stop is None or price > plan.stop:
            found.append(AlertKind.PLAN_ENTRY)
    if entered or holds:
        if plan.stop is not None and price <= plan.stop:
            found.append(AlertKind.PLAN_STOP)
        target = plan.first_target
        if target is not None and price >= target:
            found.append(AlertKind.PLAN_TARGET)
    return found


def big_move(price: Decimal, prev_close: Decimal, threshold: Decimal) -> Decimal | None:
    """The day's change in percent if it is ``threshold`` or more either way, else None."""
    change = percent(price - prev_close, prev_close) if prev_close > 0 else None
    return change if change is not None and abs(change) >= threshold else None


MINUS = "\u2212"  # a real minus sign, which reads better than a hyphen next to a number


def signed(value: Decimal) -> str:
    """A change as "+5.4%" or "-5.4%" (with a real minus sign), to one decimal place."""
    rounded = abs(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{MINUS if value < 0 else '+'}{rounded}%"


def clock_time(at: datetime, tz: ZoneInfo) -> str:
    return f"{at.astimezone(tz):%-I:%M%p}".lower()


def move_text(symbol: str, change: Decimal, price: Decimal, at: datetime, tz: ZoneInfo) -> str:
    """The alert for a big move: the stock, the change, the time in the user's timezone
    and the price."""
    icon = "📉" if change < 0 else "📈"
    return f"{icon} {symbol} {signed(change)} today at {clock_time(at, tz)}, {price:,.2f}"


def stop_text(plan: SavedPlan, price: Decimal, at: datetime, tz: ZoneInfo) -> str:
    """The plan's stop wording (see ``plans.event_text``), for a price still trading."""
    return (
        f"🛑 {plan.symbol} is at {price:,.2f} as of {clock_time(at, tz)}, at or below its stop "
        f"of {plan.stop:,.2f}. The plan says cut it: the reason to own it has broken."
    )
