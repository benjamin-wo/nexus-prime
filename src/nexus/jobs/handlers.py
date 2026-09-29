"""What each kind of job does."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.agent.service import Button
from nexus.application import bills as bill_cases
from nexus.application import budgets as budget_cases
from nexus.application import email as email_cases
from nexus.application import notifications as notify_cases
from nexus.application import receipts as receipt_cases
from nexus.application import salary as salary_cases
from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.email import EmailRuntime
from nexus.application.fx import RateSource
from nexus.application.ports import ReceiptStore
from nexus.channels.telegram.client import TelegramClient
from nexus.domain.ledger import User, UserId
from nexus.domain.planning import quiet_until
from nexus.jobs.runner import Defer, Handler, Schedule

log = logging.getLogger(__name__)

BUDGETS_SWEEP = "budgets.sweep"
BILLS_SWEEP = "bills.sweep"
PAYDAY_SWEEP = "salary.sweep"
RECEIPTS_PURGE = "receipts.purge"
EMAIL_SWEEP = "email.sweep"
NOTIFY_SWEEP = "notify.sweep"
SCHEDULES = (
    Schedule(BUDGETS_SWEEP, timedelta(minutes=10)),
    Schedule(BILLS_SWEEP, timedelta(minutes=30)),
    Schedule(PAYDAY_SWEEP, timedelta(minutes=30)),
    Schedule(RECEIPTS_PURGE, timedelta(hours=1)),
    Schedule(EMAIL_SWEEP, timedelta(minutes=15)),
    Schedule(NOTIFY_SWEEP, timedelta(minutes=5)),
)


def build_handlers(
    uow: UowFactory,
    telegram: TelegramClient,
    rates: RateSource,
    clock: Callable[[], datetime],
    archive: ReceiptStore | None = None,
    email: EmailRuntime | None = None,
) -> dict[str, Handler]:
    async def send(payload: dict[str, Any]) -> Defer | None:
        """Message a user on Telegram, but not during their quiet hours."""
        async with uow() as tx:
            user = await tx.ledger.get_user(UserId(UUID(payload["user_id"])))
        if user is None or user.telegram_chat_id is None:
            return None  # nobody to tell; nothing to retry
        later = quiet_until(clock().astimezone(ZoneInfo(user.timezone)))
        if later is not None:
            return Defer(later)
        buttons = [
            [Button(str(b["label"]), str(b["data"])) for b in row]
            for row in payload.get("buttons") or []
        ]
        await telegram.send_message(user.telegram_chat_id, str(payload["text"]), buttons or None)
        return None

    async def for_each_user(
        user_ids: list[UserId], what: str, check: Callable[[User], Awaitable[object]]
    ) -> None:
        for user_id in user_ids:
            try:
                async with uow() as tx:
                    user = await tx.ledger.get_user(user_id)
                if user is not None:
                    await check(user)
            except Exception:
                # One user's failure must not stop the others; the next sweep retries.
                log.exception("%s failed for a user", what)

    async def sweep_budgets(_: dict[str, Any]) -> None:
        async with uow() as tx:
            user_ids = await tx.planning.users_with_budgets()
        await for_each_user(
            user_ids,
            "budget check",
            lambda user: budget_cases.check_budgets(uow, rates, user, now=clock()),
        )

    async def sweep_bills(_: dict[str, Any]) -> None:
        async with uow() as tx:
            user_ids = await tx.planning.users_with_bills()
        await for_each_user(
            user_ids,
            "bill reminders",
            lambda user: bill_cases.send_reminders(uow, user, now=clock()),
        )

    async def sweep_paydays(_: dict[str, Any]) -> None:
        async with uow() as tx:
            user_ids = await tx.planning.users_with_salary_schedules()
        await for_each_user(
            user_ids,
            "payday check-in",
            lambda user: salary_cases.payday_checkin(uow, user, now=clock()),
        )

    async def purge_receipts(_: dict[str, Any]) -> None:
        if archive is not None:
            erased = await receipt_cases.purge(uow, archive, now=clock())
            if erased:
                log.info("purged %d receipts", erased)

    async def sweep_email(_: dict[str, Any]) -> None:
        if email is None:
            return
        async with uow() as tx:
            connections = await tx.email.connections_to_sweep()
        for connection in connections:
            try:
                async with uow() as tx:
                    user = await tx.ledger.get_user(connection.user_id)
                if user is not None:
                    await email_cases.sweep(
                        uow,
                        email.mailbox,
                        email.reader,
                        email.cipher,
                        archive,
                        user,
                        connection,
                        now=clock(),
                        review_url=email.review_url,
                    )
            except Exception:
                # One mailbox's failure must not stop the others; the next sweep retries.
                log.exception("email sweep failed for a mailbox")

    async def sweep_notifications(_: dict[str, Any]) -> None:
        async with uow() as tx:
            user_ids = await tx.planning.users_to_notify()
        review_url = email.review_url if email is not None else None
        await for_each_user(
            user_ids,
            "transaction updates",
            lambda user: notify_cases.notify(uow, rates, user, now=clock(), review_url=review_url),
        )

    return {
        NOTIFY_SWEEP: sweep_notifications,
        EMAIL_SWEEP: sweep_email,
        RECEIPTS_PURGE: purge_receipts,
        TELEGRAM_SEND: send,
        BUDGETS_SWEEP: sweep_budgets,
        BILLS_SWEEP: sweep_bills,
        PAYDAY_SWEEP: sweep_paydays,
    }
