"""Telling users about their transactions on Telegram: as they happen, or in a
summary every hour, three times a day, or (the default) at the end of the day."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
    Source,
    Transaction,
    User,
    UserId,
    Wallet,
    WalletKind,
)
from nexus.domain.money import Money
from nexus.domain.notifications import (
    Frequency,
    Kind,
    Level,
    NotificationSettings,
    describe_quiet,
    heading,
    is_due,
    label,
    move_percent,
)
from nexus.domain.notifications import (
    daily_cap as cap_of,
)

type UowFactory = Callable[[], UnitOfWork]

# At most this many transactions are looked at for one message.
MAX_READ = 500
# An instant message lists this many, then says how many more.
INSTANT_LINES = 5
# A summary lists this many moves between wallets, then says how many more.
MOVE_LINES = 3
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


async def set_market(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    now: datetime,
    move_alert_percent: Decimal | float | int | str | None = None,
    market_summary: bool | None = None,
    quiet_start: time | None = None,
    quiet_end: time | None = None,
    daily_cap: int | float | str | None = None,
) -> NotificationSettings:
    """Change the stock market alerts: how big a move in a day (1% to 20%) is worth a
    message, the morning summary, and the user's quiet hours (equal times: none); and how
    many messages a day (3 to 20) go before the rest wait for a digest. What is left out
    stays as it was."""
    threshold = None if move_alert_percent is None else move_percent(move_alert_percent)
    cap = None if daily_cap is None else cap_of(daily_cap)
    async with uow:
        current = await uow.planning.get_notifications(user_id, for_update=True)
        updated = replace(
            current,
            move_alert_percent=threshold if threshold is not None else current.move_alert_percent,
            market_summary=(current.market_summary if market_summary is None else market_summary),
            quiet_start=_minute(current.quiet_start if quiet_start is None else quiet_start),
            quiet_end=_minute(current.quiet_end if quiet_end is None else quiet_end),
            daily_cap=cap if cap is not None else current.daily_cap,
        )
        await uow.planning.save_notifications(updated, now)
        await uow.commit()
    return updated


def _minute(at: time) -> time:
    return at.replace(second=0, microsecond=0, tzinfo=None)


def describe_market(settings: NotificationSettings) -> str:
    """The stock market alerts and quiet hours, for the chat."""
    summary = "on" if settings.market_summary else "off"
    return (
        f"Stock alerts: a move of {settings.move_alert_percent}% or more in a day; the morning "
        f"summary is {summary}. Quiet hours: "
        f"{describe_quiet(settings.quiet_start, settings.quiet_end)}."
    )


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
        names = {c.id: c.name for c in await tx.ledger.list_categories(user.id)}
        wallets = {w.id: w for w in await tx.ledger.list_wallets(user.id)}

    if instant:
        text = _instant([t for t in logged if t.source not in _TOLD_IN_CHAT], names, wallets)
        buttons: list[list[dict[str, str]]] = []
    else:
        text = await _summary(
            rates, user, logged, names, wallets, waiting, settings, start, now, tz
        )
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
            payload: dict[str, Any] = {
                "user_id": str(user.id),
                "text": text,
                "level": Level.NOW,
                "kind": (
                    Kind.DAILY_SUMMARY
                    if settings.frequency is Frequency.DAILY
                    else Kind.TRANSACTION_UPDATE
                ),
                "link": "/accounting/ledger",
            }
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


def _move_line(t: Transaction, wallets: dict[UUID, Wallet]) -> str:
    """ "Moved S$800 to Investments"; "from X to Y" unless it left the Spending wallet."""
    origin = wallets.get(t.from_wallet_id) if t.from_wallet_id else None
    target = wallets.get(t.to_wallet_id) if t.to_wallet_id else None
    to = target.name if target else "another wallet"
    if origin is None or origin.kind is WalletKind.SPENDING:
        return f"Moved {t.amount} to {to}"
    return f"Moved {t.amount} from {origin.name} to {to}"


def _line(t: Transaction, names: dict[UUID, str], wallets: dict[UUID, Wallet]) -> str:
    if t.direction is Direction.MOVE:
        return _move_line(t, wallets)
    verb = "Spent" if t.direction is Direction.OUT else "Received"
    where = f" at {t.counterparty}" if t.counterparty else ""
    category = f" · {names[t.category_id]}" if t.category_id in names else ""
    return f"{verb} {t.amount}{where}{category}"


def _instant(
    logged: list[Transaction], names: dict[UUID, str], wallets: dict[UUID, Wallet]
) -> str | None:
    if not logged:
        return None
    if len(logged) == 1:
        return f"🧾 {_line(logged[0], names, wallets)}."
    lines = [f"🧾 {len(logged)} new in your ledger:"]
    lines += [_line(t, names, wallets) for t in logged[:INSTANT_LINES]]
    if len(logged) > INSTANT_LINES:
        lines.append(f"and {len(logged) - INSTANT_LINES} more.")
    return "\n".join(lines)


async def _summary(
    rates: RateSource,
    user: User,
    logged: list[Transaction],
    names: dict[UUID, str],
    wallets: dict[UUID, Wallet],
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
    moves = [t for t in logged if t.direction is Direction.MOVE]  # neither spent nor received
    for t in logged:
        if t.direction is Direction.MOVE:
            continue
        amount = fx.convert(t.amount, days[t.id], home, found).home
        if amount is None:
            unconverted.append(t.amount)
            continue
        if t.direction is Direction.OUT:
            spent, spent_count = spent + amount, spent_count + 1
            name = names.get(t.category_id, "Other") if t.category_id else "Uncategorised"
            by_category[name] += amount
        elif t.direction is Direction.IN:
            received, received_count = received + amount, received_count + 1

    lines = [f"🧾 {heading(settings.frequency, start, now, tz, settings.daily_at)}"]
    if spent_count:
        lines.append(f"You spent {spent} ({_count(spent_count)}).")
        top = sorted(by_category.items(), key=lambda kv: kv[1].amount, reverse=True)[:3]
        if len(by_category) > 1:
            lines.append(" · ".join(f"{name} {amount}" for name, amount in top))
    if received_count:
        lines.append(f"You received {received} ({_count(received_count)}).")
    lines += [f"{_move_line(t, wallets)}." for t in moves[:MOVE_LINES]]
    if len(moves) > MOVE_LINES:
        lines.append(f"and {len(moves) - MOVE_LINES} more moves between your wallets.")
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
