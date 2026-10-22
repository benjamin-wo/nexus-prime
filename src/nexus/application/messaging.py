"""What happens to a message queued for Telegram: sent, held for quiet hours or the next
digest, and kept as a record for 30 days.

Every message is a ``telegram.send`` job whose payload says its ``level`` (urgent, now or
digest), its ``kind`` and optionally the web ``link`` that opens what it is about; the
rules are ``domain.notifications.decide``. A message held for quiet hours or a digest
joins the digest that goes when quiet hours end (and at 19:00 for what was held outside
them), unless it has buttons: that one is sent on its own, once its time comes, so its
buttons work. Payloads queued before levels existed carry ``urgent`` or ``anytime``
instead: ``urgent`` is that level, ``anytime`` is a message the user timed (sent at once,
never capped, not held) and anything else is ``now``.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.ports import UnitOfWork
from nexus.domain.ledger import UserId
from nexus.domain.notifications import (
    UNCAPPED,
    Decision,
    HoldUntil,
    Kind,
    Level,
    Notification,
    Send,
    Status,
    decide,
    digest_text,
    local_day,
)
from nexus.domain.planning import quiet_until

log = logging.getLogger(__name__)

DIGEST_SWEEP = "notify.digest"
PRUNE_JOB = "notify.prune"
KEEP = timedelta(days=30)
# The web page lists at most this many.
SHOWN = 500

type Buttons = list[list[dict[str, str]]]
type Post = Callable[[int, str, Buttons], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class Outgoing:
    """A ``telegram.send`` payload, read."""

    user_id: UserId
    text: str
    buttons: Buttons
    level: Level
    kind: str
    link: str | None
    anytime: bool  # the user timed it: sent whenever, never capped
    notification_id: UUID | None  # set once it is held, for the job that sends it later

    @property
    def has_buttons(self) -> bool:
        return any(self.buttons)


def read(payload: dict[str, Any]) -> Outgoing:
    anytime = bool(payload.get("anytime"))
    if "level" in payload:
        level = Level(payload["level"])
    else:
        level = Level.URGENT if payload.get("urgent") else Level.NOW
    held = payload.get("notification_id")
    return Outgoing(
        user_id=UserId(UUID(payload["user_id"])),
        text=str(payload["text"]),
        buttons=[
            [{"label": str(b["label"]), "data": str(b["data"])} for b in row]
            for row in payload.get("buttons") or []
        ],
        level=level,
        kind=str(payload.get("kind") or (Kind.DAILY_SUMMARY if anytime else Kind.MESSAGE)),
        link=payload.get("link"),
        anytime=anytime,
        notification_id=UUID(held) if held else None,
    )


async def deliver(
    uow: UowFactory, payload: dict[str, Any], post: Post, *, now: datetime
) -> datetime | None:
    """Send the message, hold it or put it in the next digest, and keep the record.
    Returns when to run the job again, for a held message that was already recorded."""
    out = read(payload)
    async with uow() as tx:
        user = await tx.ledger.get_user(out.user_id)
        if user is None:
            return None
        record = (
            await tx.notifications.get(out.user_id, out.notification_id)
            if out.notification_id
            else None
        )
        if out.notification_id and (record is None or record.status is not Status.HELD):
            return None  # told meanwhile, or forgotten
        settings = await tx.planning.get_notifications(out.user_id)
        tz = ZoneInfo(user.timezone)
        uncapped = out.anytime or out.kind in UNCAPPED
        sent_today = 0 if uncapped else await _sent_today(tx, user.id, now, tz)
    if user.telegram_chat_id is None:
        await _keep(uow, out, record, Status.DROPPED, now)  # nobody to tell; nothing to retry
        return None
    decision: Decision = Send()
    if not out.anytime:
        # A digest item with buttons, once its time has come, is sent like any message.
        level = Level.NOW if record is not None and record.level is Level.DIGEST else out.level
        decision = decide(
            level,
            now.astimezone(tz),
            settings.quiet_start,
            settings.quiet_end,
            sent_today,
            settings.daily_cap,
            out.has_buttons,
        )
    if isinstance(decision, Send):
        await post(user.telegram_chat_id, out.text, out.buttons)
        await _keep(uow, out, record, Status.SENT, now)
        return None
    until = decision.until if isinstance(decision, HoldUntil) else decision.at
    return await _hold(uow, out, payload, record, until, now)


async def _sent_today(tx: UnitOfWork, user_id: UserId, now: datetime, tz: ZoneInfo) -> int:
    start, end = local_day(now, tz)
    return await tx.notifications.count_sent(
        user_id, start, end, except_kinds=[k.value for k in UNCAPPED]
    )


async def _keep(
    uow: UowFactory, out: Outgoing, record: Notification | None, status: Status, now: datetime
) -> None:
    """Record that the message went (or never will); a held one is updated, not repeated."""
    if out.kind == Kind.DIGEST:
        return  # its items are the record
    sent_at = now if status is Status.SENT else None
    async with uow() as tx:
        if record is None:
            await tx.notifications.insert(
                Notification(
                    uuid4(),
                    out.user_id,
                    out.kind,
                    out.level,
                    out.text,
                    out.link,
                    out.has_buttons,
                    now,
                    status,
                    sent_at=sent_at,
                )
            )
        else:
            await tx.notifications.update(
                replace(record, status=status, sent_at=sent_at, held_until=None)
            )
        await tx.commit()


async def _hold(
    uow: UowFactory,
    out: Outgoing,
    payload: dict[str, Any],
    record: Notification | None,
    until: datetime,
    now: datetime,
) -> datetime | None:
    """Keep the message until ``until``. One with buttons is queued again for then; one
    already queued that way is run again by the caller (the returned time)."""
    async with uow() as tx:
        if record is not None:
            await tx.notifications.update(replace(record, held_until=until))
            await tx.commit()
            return until
        held = Notification(
            uuid4(),
            out.user_id,
            out.kind,
            out.level,
            out.text,
            out.link,
            out.has_buttons,
            now,
            Status.HELD,
            held_until=until,
        )
        await tx.notifications.insert(held)
        if out.has_buttons:
            await tx.jobs.enqueue(
                TELEGRAM_SEND,
                {**payload, "notification_id": str(held.id)},
                dedupe_key=f"notification:{held.id}",
                run_at=until,
            )
        await tx.commit()
    return None


async def send_digests(uow: UowFactory, *, now: datetime) -> int:
    """Fold each user's held messages without buttons, whose time has come, into one
    message. Returns how many digests were queued."""
    async with uow() as tx:
        user_ids = await tx.notifications.users_with_digest_due(now)
    queued = 0
    for user_id in user_ids:
        try:
            queued += await _digest(uow, user_id, now)
        except Exception:
            # One user's failure must not stop the others; the next sweep retries.
            log.exception("digest failed for a user")
    return queued


async def _digest(uow: UowFactory, user_id: UserId, now: datetime) -> int:
    async with uow() as tx:
        user = await tx.ledger.get_user(user_id)
        if user is None:
            return 0
        settings = await tx.planning.get_notifications(user_id)
        local = now.astimezone(ZoneInfo(user.timezone))
        if quiet_until(local, settings.quiet_start, settings.quiet_end) is not None:
            return 0  # the user's quiet hours changed meanwhile: wait for their end
        items = await tx.notifications.due_for_digest(user_id, now)
        if not items:
            return 0
        ids = [i.id for i in items]
        if user.telegram_chat_id is None:  # unlinked since: nobody to tell
            await tx.notifications.close_held(user_id, ids, Status.DROPPED, at=now)
            await tx.commit()
            return 0
        # Marked in the same transaction as it is queued, and keyed by its first item, so
        # a digest is never made twice.
        queued = await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {
                "user_id": str(user_id),
                "text": digest_text(items),
                "kind": Kind.DIGEST,
                "level": Level.NOW,
                "anytime": True,  # not held again
            },
            dedupe_key=f"digest:{user_id}:{items[0].id}",
            run_at=now,
        )
        await tx.notifications.close_held(user_id, ids, Status.DIGESTED, at=now, digest_id=uuid4())
        await tx.commit()
    return int(queued)


async def history(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> list[Notification]:
    """The user's messages of the last 30 days, newest first."""
    async with uow:
        return await uow.notifications.recent(user_id, now - KEEP, SHOWN)


async def prune(uow: UowFactory, *, now: datetime) -> int:
    """Forget messages older than 30 days, for everyone. Returns how many."""
    async with uow() as tx:
        gone = await tx.notifications.prune(now - KEEP)
        await tx.commit()
    return gone
