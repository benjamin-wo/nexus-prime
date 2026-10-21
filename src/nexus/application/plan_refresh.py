"""Keep this plan fresh: an open plan with the switch on is made again by itself when it
goes stale, and replaces the old one.

The hourly ``plans.refresh`` job looks at each open plan with Keep fresh on and starts a
plan run for its stock (the same ``start_plan`` the user's own request uses, so the run caps
and the spend cap apply) when, in this order (``domain.plans.refresh_reason``):

1. its valid-until date has passed (a New York date);
2. the live or last price is more than one ATR from the price the plan was written with;
3. the stock reported earnings since the plan was made and that day is now past;
4. it was made a week ago or more.

At most one automatic run per plan every 24 hours (``last_refresh_check``, set when the run
starts, or the plan itself being a refresh made in the last 24 hours), at most 10 a user in
24 hours, and none while a run for that stock is already going. A run that can't start
(a cap, too few prices) leaves the plan as it was and is looked at again next hour.

The run is silent: no progress message and no result message (``plans.is_automatic``).
When it saves, the new plan links to the old one, keeps its Keep fresh and alert settings
and closes it as ``refreshed`` (see ``plans._save``), and the user is told by Telegram, with
quiet hours applying, only if the verdict changed or the entry, stop or first target moved
by more than half an ATR.

Ordering with ``plans.follow``: for ``KEEP_FRESH_GRACE`` (3 days) after the valid-until
date, following a plan whose Keep fresh is on doesn't close it as expired (``follow_plans``
stops short of the date), so an expired plan is still open here and gets refreshed instead
of just running out, whichever job runs first, and a refresh that can't start is tried
every hour. Past the grace the follow expires it like any plan, with the usual message, so
a plan kept fresh never stays open for ever. Turning Keep fresh off lets the next follow
expire it as usual.

A plan the user asks for by hand also replaces their open Keep fresh plans for the stock
(``plans._save``), without a message.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from nexus.application import plans as plan_cases
from nexus.application.departments import Departments
from nexus.application.ports import UnitOfWork
from nexus.application.quotes import RUN_STATUS_AGE, Quotes
from nexus.application.research import LEVEL_BARS
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import User
from nexus.domain.levels import compute
from nexus.domain.market import US_MARKET, MarketStatus, pick_price
from nexus.domain.plans import (
    REFRESH_EVERY,
    REFRESH_PER_USER,
    RefreshReason,
    SavedPlan,
    refresh_reason,
)

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

REFRESH_JOB = "plans.refresh"


async def refresh_plans(
    uow: UowFactory, registry: Departments, quotes: Quotes | None, *, now: datetime
) -> int:
    """The job: start a refresh for each open Keep fresh plan that is due. Returns how many
    were started. One plan's failure never stops the others."""
    if plan_cases.KIND not in registry.kinds:
        return 0
    async with uow() as tx:
        candidates = await tx.investments.plans_to_refresh()
    if not candidates:
        return 0
    status = await quotes.status(now, max_age=RUN_STATUS_AGE) if quotes is not None else None
    started = 0
    for plan in candidates:
        try:
            started += await _consider(uow, registry, plan, status, now)
        except Exception:
            log.exception("a plan couldn't be refreshed")
    return started


def _recent(plan: SavedPlan, now: datetime) -> bool:
    """Whether the plan was sent for a refresh, or was made by one, in the last 24 hours."""
    last = plan.last_refresh_check
    if last is None and plan.refreshed_from is not None:
        last = plan.created_at
    return last is not None and now - last < REFRESH_EVERY


async def _consider(
    uow: UowFactory,
    registry: Departments,
    plan: SavedPlan,
    status: MarketStatus | None,
    now: datetime,
) -> int:
    if _recent(plan, now):
        return 0
    today = now.astimezone(US_MARKET).date()
    made = plan.created_at.astimezone(US_MARKET).date()
    async with uow() as tx:
        user = await tx.ledger.get_user(plan.user_id)
        bars = await tx.investments.bars(plan.symbol, LEVEL_BARS)
        quote = (await tx.investments.quotes([plan.symbol])).get(plan.symbol)
        earnings = await tx.investments.past_earnings(plan.symbol, made + timedelta(days=1), today)
        used = await tx.investments.refresh_checks_since(plan.user_id, now - REFRESH_EVERY)
        going = await tx.runs.active_runs(plan.user_id, plan_cases.KIND)
    if user is None or used >= REFRESH_PER_USER:
        return 0
    if any(run.task.get("symbol") == plan.symbol for run in going):
        return 0
    picked = pick_price(
        bars[-1] if bars else None,
        bars[-2] if len(bars) > 1 else None,
        quote,
        status,
        now,
    )
    atr = plan.atr
    if atr is None and (levels := compute(bars)) is not None:
        atr = levels.atr  # a plan made before Keep fresh: today's typical day's move
    reason = refresh_reason(
        plan,
        now=now,
        price=picked.price if picked else None,
        atr=atr,
        earnings=[e.day for e in earnings],
    )
    if reason is None:
        return 0
    return await _start(uow, registry, plan, user, reason, now)


async def _start(
    uow: UowFactory,
    registry: Departments,
    plan: SavedPlan,
    user: User,
    reason: RefreshReason,
    now: datetime,
) -> int:
    try:
        await plan_cases.start_plan(
            uow,
            registry,
            user,
            plan.symbol,
            now=now,
            refresh_of=plan.id,
            refresh_why=reason.text,
        )
    except InvalidInput as exc:  # a run cap, the spend cap, too few prices
        log.info("a plan's refresh couldn't start: %s", exc)
        return 0
    async with uow() as tx:
        await tx.investments.mark_refresh_check(plan.user_id, plan.id, now)
        await tx.commit()
    return 1
