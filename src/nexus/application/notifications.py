"""Telling users about their transactions on Telegram: as they happen, or in a
summary every hour, three times a day, or (the default) at the end of the day."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, Source, Transaction, User, UserId
from nexus.domain.money import Money
from nexus.domain.notifications import (
    Frequency,
    NotificationSettings,
    heading,
    is_due,
    label,
)

type UowFactory = Callable[[], UnitOfWork]

# At most this many transactions are looked at for one message.
MAX_READ = 500
# An instant message lists this many, then says how many more.
INSTANT_LINES = 5
# Logged in the chat itself (or confirmed there): the reply already said so.
_TOLD_IN_CHAT = frozenset({Source.TEXT, Source.PHOTO, Source.EMAIL})


async def get_settings(uow: UnitOfWork, user_id: UserId) -> NotificationSettings:
    async with uow:
        return await uow.planning.get_notifications(user_id)


async def set_frequency(
    uow: UnitOfWork,
    user_id: UserId,
    frequency: Frequency,
    *,
    now: datetime,
    daily_at: time | None = None,
) -> NotificationSettings:
    """Change how often updates come. ``daily_at`` sets the daily summary's time
    (and only goes with the daily summary); left out, it stays as it was."""
    if daily_at is not None and frequency is not Frequency.DAILY:
        raise InvalidInput("a time can only be set for the daily summary")
    async with uow:
        current = await uow.planning.get_notifications(user_id, for_update=True)
        since = current.notified_until
        if since is None or current.frequency is Frequency.OFF:
            since = now  # turning them on doesn't replay what happened while off
        updated = replace(
            current,
            frequency=frequency,
            notified_until=since,
            daily_at=(daily_at or current.daily_at).replace(second=0, microsecond=0),
        )
        await uow.planning.save_notifications(updated, now)
        await uow.commit()
    return updated


def describe(settings: NotificationSettings) -> str:
    frequency = settings.frequency
    if frequency is Frequency.OFF:
        return "Transaction updates are off."
    if frequency is Frequency.INSTANT:
        return "You get a message for each transaction as it happens."
    return f"You get a summary of your transactions {label(frequency, settings.daily_at)}."


async def notify(
    uow: UowFactory,
    rates: RateSource,
    user: User,
    *,
    now: datetime,
    review_url: str | None = None,
) -> bool:
    """Send the user what's due, if anything. True if a message was queued."""
    tz = ZoneInfo(user.timezone)
    async with uow() as tx:
        settings = await tx.planning.get_notifications(user.id)
        if settings.notified_until is None or settings.frequency is Frequency.OFF:
            # Start counting from now; while off, nothing builds up.
            await tx.planning.save_notifications(replace(settings, notified_until=now), now)
            await tx.commit()
            return False
        if not is_due(settings, now, tz):
            return False
        start = settings.notified_until
        logged = [
            t
            for t in await tx.ledger.logged_between(user.id, start, now, limit=MAX_READ)
            if t.source is not Source.IMPORT  # a bulk import of old data isn't news
        ]
        instant = settings.frequency is Frequency.INSTANT
        # Instantly, email receipts are asked about one by one as they're found.
        waiting = 0 if instant else await tx.email.count_waiting(user.id, start, now)
        names = {
            c.id: c.name for c in await tx.ledger.list_categories(user.id, include_inactive=True)
        }

    if instant:
        text = _instant([t for t in logged if t.source not in _TOLD_IN_CHAT], names)
        buttons: list[list[dict[str, str]]] = []
    else:
        text = await _summary(rates, user, logged, names, waiting, settings, start, now, tz)
        buttons = (
            [[{"label": "Review them", "data": f"url:{review_url}"}]]
            if waiting and review_url
            else []
        )

    async with uow() as tx:
        current = await tx.planning.get_notifications(user.id, for_update=True)
        if current.notified_until != start:
            return False  # the settings changed meanwhile; the next check starts over
        sent = False
        if text:
            payload: dict[str, Any] = {"user_id": str(user.id), "text": text}
            if settings.frequency is Frequency.DAILY:
                payload["anytime"] = True  # the user chose the time, quiet hours or not
            if buttons:
                payload["buttons"] = buttons
            sent = await tx.jobs.enqueue(
                TELEGRAM_SEND,
                payload,
                dedupe_key=f"notify:{user.id}:{now.isoformat()}",
                run_at=now,
            )
        await tx.planning.save_notifications(replace(current, notified_until=now), now)
        await tx.commit()
    return sent


def _line(t: Transaction, names: dict[UUID, str]) -> str:
    verb = "Spent" if t.direction is Direction.OUT else "Received"
    where = f" at {t.counterparty}" if t.counterparty else ""
    category = f" · {names[t.category_id]}" if t.category_id in names else ""
    return f"{verb} {t.amount}{where}{category}"


def _instant(logged: list[Transaction], names: dict[UUID, str]) -> str | None:
    if not logged:
        return None
    if len(logged) == 1:
        return f"🧾 {_line(logged[0], names)}."
    lines = [f"🧾 {len(logged)} new in your ledger:"]
    lines += [_line(t, names) for t in logged[:INSTANT_LINES]]
    if len(logged) > INSTANT_LINES:
        lines.append(f"and {len(logged) - INSTANT_LINES} more.")
    return "\n".join(lines)


async def _summary(
    rates: RateSource,
    user: User,
    logged: list[Transaction],
    names: dict[UUID, str],
    waiting: int,
    settings: NotificationSettings,
    start: datetime,
    now: datetime,
    tz: ZoneInfo,
) -> str | None:
    if not logged and not waiting:
        return None  # nothing happened: no message
    home = user.home_currency
    days = {t.id: t.occurred_at.astimezone(tz).date() for t in logged}
    found = await fx.rates_for(rates, home, ((t.amount.currency, days[t.id]) for t in logged))
    spent, received = Money.zero(home), Money.zero(home)
    spent_count = received_count = 0
    by_category: dict[str, Money] = defaultdict(lambda: Money.zero(home))
    unconverted: list[Money] = []
    for t in logged:
        amount = fx.convert(t.amount, days[t.id], home, found).home
        if amount is None:
            unconverted.append(t.amount)
            continue
        if t.direction is Direction.OUT:
            spent, spent_count = spent + amount, spent_count + 1
            name = names.get(t.category_id, "Other") if t.category_id else "Uncategorised"
            by_category[name] += amount
        else:
            received, received_count = received + amount, received_count + 1

    lines = [f"🧾 {heading(settings.frequency, start, now, tz, settings.daily_at)}"]
    if spent_count:
        lines.append(f"You spent {spent} ({_count(spent_count)}).")
        top = sorted(by_category.items(), key=lambda kv: kv[1].amount, reverse=True)[:3]
        if len(by_category) > 1:
            lines.append(" · ".join(f"{name} {amount}" for name, amount in top))
    if received_count:
        lines.append(f"You received {received} ({_count(received_count)}).")
    if unconverted:
        shown = ", ".join(str(m) for m in unconverted[:3])
        lines.append(f"Also {shown}, which I couldn't convert to {home}.")
    if waiting:
        lines.append(
            f"📧 {waiting} receipt{'s' if waiting != 1 else ''} from your email "
            f"{'are' if waiting != 1 else 'is'} waiting for you."
        )
    if settings.frequency is Frequency.DAILY:
        lines.append("To change how often or when I send these, just tell me.")
    return "\n".join(lines)


def _count(n: int) -> str:
    return f"{n} transaction{'s' if n != 1 else ''}"
