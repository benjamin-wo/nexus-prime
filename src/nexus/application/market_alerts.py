"""Alerts while the US market is open, from the live quotes.

After each quote refresh that fetched something, and only while the regular session is
on, every user's open plans (with alerts on) and held and watched stocks are checked
against the stored live price:

- a plan not yet entered whose price is in or through its buy zone: ``plan_entry``;
- at or below the plan's stop: ``plan_stop``, urgent when the user holds the stock;
- at or above the plan's first target: ``plan_target``;
- a held or watched stock up or down by the user's threshold or more in the day (5% unless
  they chose another): ``big_move``.

Each is kept once per user, stock, kind and trading day (``market_alerts``). It is sent now,
unless it falls in the user's quiet hours and isn't urgent: then it waits, unsent, for the
morning summary. The plan wording is the plan's own (``plans.event_text``); the evening
follow on daily bars doesn't repeat an event already alerted that day.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from nexus.application.alerting import Alert, Outcome, deliver
from nexus.application.market import PRICE_CURRENCY
from nexus.application.plans import event_text
from nexus.application.ports import UnitOfWork
from nexus.domain.alerts import (
    EVENT_OF,
    AlertKind,
    big_move,
    move_text,
    plan_alerts,
    stop_text,
)
from nexus.domain.ledger import UserId
from nexus.domain.market import (
    US_MARKET,
    MarketStatus,
    Picked,
    PriceKind,
    is_holiday,
    pick_price,
    regular_open,
)
from nexus.domain.plans import Followed, PlanEvent, PlanStatus, SavedPlan

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]


async def check(uow: UowFactory, status: MarketStatus | None, *, now: datetime) -> int:
    """Alert every user to what the live prices say. Does nothing unless the regular
    session is on (``status`` is the exchange's word, or None to use the usual hours).
    Returns how many alerts were made, sent or held."""
    today = now.astimezone(US_MARKET).date()
    if not regular_open(status, now) or is_holiday(today):
        return 0
    async with uow() as tx:
        user_ids = await tx.planning.users_to_notify()
        plans = await tx.investments.plans_to_follow()
    made = 0
    for user_id in user_ids:
        try:
            made += await _check_user(
                uow, user_id, [p for p in plans if p.user_id == user_id], status, now
            )
        except Exception:
            # One user's failure must not stop the others; the next refresh retries.
            log.exception("market alerts failed for a user")
    return made


async def _check_user(
    uow: UowFactory,
    user_id: UserId,
    open_plans: list[SavedPlan],
    status: MarketStatus | None,
    now: datetime,
) -> int:
    today = now.astimezone(US_MARKET).date()
    async with uow() as tx:
        user = await tx.ledger.get_user(user_id)
        if user is None:
            return 0
        settings = await tx.planning.get_notifications(user_id)
        held = {
            h.position.symbol
            for h in await tx.investments.list_holdings(user_id)
            if h.position.average_cost.currency == PRICE_CURRENCY
        }
        watched = set(await tx.investments.list_watch(user_id))
        symbols = sorted(held | watched | {p.symbol for p in open_plans})
        quotes = await tx.investments.quotes(symbols)
        bars = await tx.investments.latest_bars(symbols, 1)
        live: dict[str, Picked] = {}
        for symbol in symbols:
            found = bars.get(symbol, [])
            picked = pick_price(found[0] if found else None, None, quotes.get(symbol), status, now)
            if picked is not None and picked.kind is PriceKind.LIVE and picked.day == today:
                live[symbol] = picked
        made = 0
        tz = ZoneInfo(user.timezone)
        for alert in _plan_alerts(open_plans, live, held, tz):
            made += await deliver(tx, user, settings, alert, now=now) is not Outcome.DUPLICATE
        for symbol in sorted((held | watched) & live.keys()):
            picked = live[symbol]
            change = (
                big_move(picked.price, picked.previous, settings.move_alert_percent)
                if picked.previous is not None and picked.at is not None
                else None
            )
            if change is not None and picked.at is not None:
                alert = Alert(
                    symbol,
                    AlertKind.BIG_MOVE,
                    today,
                    move_text(symbol, change, picked.price, picked.at, tz),
                )
                made += await deliver(tx, user, settings, alert, now=now) is not Outcome.DUPLICATE
        await tx.commit()
    return made


def _plan_alerts(
    plans: list[SavedPlan], live: dict[str, Picked], held: set[str], tz: ZoneInfo
) -> list[Alert]:
    found: list[Alert] = []
    for plan in plans:
        picked = live.get(plan.symbol)
        if (
            picked is None
            or picked.at is None
            or not plan.alerts
            or plan.status is not PlanStatus.OPEN
            or plan.valid_until < picked.day
        ):
            continue
        holds = plan.symbol in held
        for kind in plan_alerts(plan, picked.price, holds=holds):
            found.append(
                Alert(
                    plan.symbol,
                    kind,
                    picked.day,
                    _text(plan, kind, picked.price, picked.at, tz),
                    urgent=kind is AlertKind.PLAN_STOP and holds,
                    buttons=(("Stop alerts for this plan", f"plan:mute:{plan.id}"),),
                )
            )
    return found


def _text(plan: SavedPlan, kind: AlertKind, price: Decimal, at: datetime, tz: ZoneInfo) -> str:
    """The plan's own wording for the event, with the live price where it says one."""
    if kind is AlertKind.PLAN_STOP:
        return stop_text(plan, price, at, tz)
    day = at.astimezone(US_MARKET).date()
    where = plan.entry_high if kind is AlertKind.PLAN_ENTRY else plan.first_target
    event = PlanEvent(EVENT_OF[kind], day, where or price)
    still_open = Followed(
        PlanStatus.OPEN, plan.entered_on, plan.checked_through, None, None, None, []
    )
    return event_text(plan, event, still_open)
