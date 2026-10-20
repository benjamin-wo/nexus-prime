"""Keeping and sending one alert about a stock: at most once per user, stock, kind and
trading day, at once or held for the morning summary.

An alert is sent now unless it falls in the user's quiet hours and isn't urgent. Held
alerts are listed in the next morning summary; a user who turned that summary off, or who
holds and watches no stock (so none will come), hears about them when quiet hours end
instead, like any other message.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import UnitOfWork
from nexus.domain.alerts import AlertKind, MarketAlert
from nexus.domain.ledger import User
from nexus.domain.notifications import NotificationSettings
from nexus.domain.planning import quiet_until


class Outcome(StrEnum):
    SENT = "sent"  # queued for Telegram now (the sender still waits out quiet hours)
    HELD = "held"  # kept unsent for the morning summary
    DUPLICATE = "duplicate"  # already alerted that day


@dataclass(frozen=True, slots=True)
class Alert:
    symbol: str
    kind: AlertKind
    day: date  # the New York trading date
    text: str
    urgent: bool = False
    buttons: tuple[tuple[str, str], ...] = ()  # (label, callback data), one row each
    dedupe_key: str | None = None  # for the send job; else from the alert's id


def in_quiet_hours(user: User, settings: NotificationSettings, now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(user.timezone))
    return quiet_until(local, settings.quiet_start, settings.quiet_end) is not None


async def _gets_the_summary(tx: UnitOfWork, user: User) -> bool:
    """Whether a morning summary will come for this user (it needs a held or watched stock,
    which a plan alone doesn't give), so that what is held for it is not lost."""
    return bool(
        await tx.investments.list_holdings(user.id) or await tx.investments.list_watch(user.id)
    )


async def deliver(
    tx: UnitOfWork, user: User, settings: NotificationSettings, alert: Alert, *, now: datetime
) -> Outcome:
    """Keep the alert and queue it or hold it, inside the caller's transaction (which
    must commit)."""
    kept = MarketAlert(
        uuid4(), user.id, alert.symbol, alert.kind, alert.day, alert.text, alert.urgent, now
    )
    if not await tx.investments.insert_alert(kept):
        return Outcome.DUPLICATE
    if (
        not alert.urgent
        and settings.market_summary
        and in_quiet_hours(user, settings, now)
        and await _gets_the_summary(tx, user)
    ):
        return Outcome.HELD
    payload: dict[str, Any] = {
        "user_id": str(user.id),
        "text": alert.text,
        "buttons": [[{"label": label, "data": data}] for label, data in alert.buttons],
    }
    if alert.urgent:
        payload["urgent"] = True  # sent at once, quiet hours or not
    await tx.jobs.enqueue(
        TELEGRAM_SEND,
        payload,
        dedupe_key=alert.dedupe_key or f"market-alert:{kept.id}",
        run_at=now,
    )
    await tx.investments.mark_alerts_sent(user.id, [kept.id], now)
    return Outcome.SENT
