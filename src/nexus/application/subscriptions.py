"""Recurring payments: propose what looks like a subscription, track the ones the
user agrees to, and say when a tracked one changes price."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import NotFound
from nexus.domain.ledger import User, UserId
from nexus.domain.money import Money
from nexus.domain.recurring import (
    CADENCE_WORDS,
    LOOKBACK,
    Candidate,
    Charge,
    Subscription,
    SubscriptionStatus,
    find_recurring,
    merchant_key,
    monthly_cost,
    next_charge,
    price_changed,
)

type UowFactory = Callable[[], UnitOfWork]

MAX_READ = 5000  # expenses looked at per check
MAX_PROPOSALS = 3  # new proposals per check, so a first check isn't a flood


async def check(uow: UowFactory, user: User, *, now: datetime) -> None:
    """Follow tracked subscriptions' new charges (flagging price changes) and propose
    newly spotted ones."""
    tz = ZoneInfo(user.timezone)
    async with uow() as tx:
        expenses = await tx.ledger.outgoing_since(user.id, now - LOOKBACK, limit=MAX_READ)
        known = await tx.planning.list_subscriptions(user.id)
    charges = [
        Charge(t.id, t.occurred_at.astimezone(tz).date(), t.amount, t.counterparty or "")
        for t in expenses
    ]
    for subscription in known:
        if subscription.status is SubscriptionStatus.ACTIVE:
            await _follow(uow, user, subscription, charges, now)
    seen = {(s.key, s.amount.currency) for s in known}
    fresh = [
        c
        for c in find_recurring(charges, now.astimezone(tz).date())
        if (c.key, c.amount.currency) not in seen
    ]
    for candidate in fresh[:MAX_PROPOSALS]:
        await _propose(uow, user, candidate, now)


async def _follow(
    uow: UowFactory, user: User, subscription: Subscription, charges: list[Charge], now: datetime
) -> None:
    newer = [
        c
        for c in charges
        if merchant_key(c.merchant) == subscription.key
        and c.amount.currency == subscription.amount.currency
        and c.day > subscription.last_charged_on
    ]
    if not newer:
        return
    latest = max(newer, key=lambda c: c.day)
    async with uow() as tx:
        current = await tx.planning.get_subscription(user.id, subscription.id, for_update=True)
        if current is None or current.last_charged_on >= latest.day:
            return
        updated = replace(current, last_charged_on=latest.day, updated_at=now)
        if price_changed(current, latest.amount):
            updated = replace(
                updated,
                amount=latest.amount,
                previous_amount=current.amount,
                price_changed_on=latest.day,
            )
            direction = "up" if latest.amount.amount > current.amount.amount else "down"
            per = CADENCE_WORDS[current.cadence]
            await tx.jobs.enqueue(
                TELEGRAM_SEND,
                {
                    "user_id": str(user.id),
                    "text": f"💸 {current.name} went {direction} from {current.amount} to "
                    f"{latest.amount} a {per} (charged {latest.day:%-d %b}).",
                },
                dedupe_key=f"sub.price:{current.id}:{latest.day.isoformat()}",
                run_at=now,
            )
        await tx.planning.update_subscription(updated)
        await tx.commit()


async def _propose(uow: UowFactory, user: User, candidate: Candidate, now: datetime) -> None:
    subscription = Subscription(
        id=uuid4(),
        user_id=user.id,
        key=candidate.key,
        name=candidate.merchant,
        cadence=candidate.cadence,
        amount=candidate.amount,
        last_charged_on=candidate.last_day,
        status=SubscriptionStatus.PROPOSED,
        created_at=now,
        updated_at=now,
    )
    async with uow() as tx:
        if not await tx.planning.insert_subscription(subscription):
            return
        per = CADENCE_WORDS[candidate.cadence]
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {
                "user_id": str(user.id),
                "text": f"🔁 {candidate.merchant} has charged you about {candidate.amount} "
                f"every {per}, {len(candidate.transaction_ids)} times in a row (last on "
                f"{candidate.last_day:%-d %b}). Track it as a subscription? I'll tell you "
                "if the price changes.",
                "buttons": [
                    [
                        {"label": "Track it", "data": f"sub:track:{subscription.id}"},
                        {"label": "No", "data": f"sub:skip:{subscription.id}"},
                    ]
                ],
            },
            dedupe_key=f"sub.propose:{subscription.id}",
            run_at=now,
        )
        await tx.commit()


async def _set_status(
    uow: UnitOfWork,
    user_id: UserId,
    subscription_id: UUID,
    status: SubscriptionStatus,
    *,
    now: datetime,
) -> Subscription:
    async with uow:
        current = await uow.planning.get_subscription(user_id, subscription_id, for_update=True)
        if current is None:
            raise NotFound("that subscription isn't there any more")
        updated = replace(current, status=status, updated_at=now)
        await uow.planning.update_subscription(updated)
        await uow.commit()
    return updated


async def track(
    uow: UnitOfWork, user_id: UserId, subscription_id: UUID, *, now: datetime
) -> Subscription:
    return await _set_status(uow, user_id, subscription_id, SubscriptionStatus.ACTIVE, now=now)


async def dismiss(
    uow: UnitOfWork, user_id: UserId, subscription_id: UUID, *, now: datetime
) -> Subscription:
    """Turn down a proposal, or stop tracking. It isn't proposed again."""
    return await _set_status(uow, user_id, subscription_id, SubscriptionStatus.DISMISSED, now=now)


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    subscription: Subscription
    next_charge: date
    monthly: Money


@dataclass(frozen=True, slots=True)
class Overview:
    tracked: list[SubscriptionView]
    proposed: list[SubscriptionView]
    monthly_totals: list[Money]  # per currency, tracked only


async def overview(uow: UnitOfWork, user_id: UserId) -> Overview:
    async with uow:
        found = await uow.planning.list_subscriptions(user_id)
    views = [
        SubscriptionView(s, next_charge(s.cadence, s.last_charged_on), monthly_cost(s))
        for s in found
    ]
    tracked = [v for v in views if v.subscription.status is SubscriptionStatus.ACTIVE]
    totals: dict[str, Money] = {}
    for v in tracked:
        prior = totals.get(v.monthly.currency)
        totals[v.monthly.currency] = prior + v.monthly if prior else v.monthly
    return Overview(
        tracked=sorted(tracked, key=lambda v: v.next_charge),
        proposed=[v for v in views if v.subscription.status is SubscriptionStatus.PROPOSED],
        monthly_totals=list(totals.values()),
    )


def describe(view: SubscriptionView) -> str:
    s = view.subscription
    line = (
        f"{s.name}: {s.amount} a {CADENCE_WORDS[s.cadence]}, next about {view.next_charge:%-d %b}"
    )
    if s.previous_amount is not None and s.price_changed_on is not None:
        line += f" (was {s.previous_amount} until {s.price_changed_on:%-d %b})"
    return line
