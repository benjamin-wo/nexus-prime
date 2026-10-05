"""What each kind of job does."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.agent.memory_writer import MemoryWriter
from nexus.agent.service import Button
from nexus.application import bills as bill_cases
from nexus.application import bookings as booking_cases
from nexus.application import budgets as budget_cases
from nexus.application import departments as department_cases
from nexus.application import email as email_cases
from nexus.application import market as market_cases
from nexus.application import notifications as notify_cases
from nexus.application import plans as plan_cases
from nexus.application import receipts as receipt_cases
from nexus.application import research as research_cases
from nexus.application import salary as salary_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.email import EmailRuntime
from nexus.application.fx import RateSource
from nexus.application.market import PriceSource
from nexus.application.ports import ReceiptStore
from nexus.application.research import NewsSource
from nexus.channels.telegram.client import TelegramClient, TelegramError
from nexus.channels.telegram.webhook import UNDO_EXPIRE, kept_buttons
from nexus.domain.departments import Run
from nexus.domain.ledger import User, UserId
from nexus.domain.planning import quiet_until
from nexus.jobs.runner import Defer, Handler, Schedule

log = logging.getLogger(__name__)

BUDGETS_SWEEP = "budgets.sweep"
BILLS_SWEEP = "bills.sweep"
PAYDAY_SWEEP = "salary.sweep"
RECEIPTS_PURGE = "receipts.purge"
EMAIL_SWEEP = email_cases.SWEEP_JOB
NOTIFY_SWEEP = "notify.sweep"
SUBSCRIPTIONS_SWEEP = "subscriptions.sweep"
MEMORY_UPDATE = "memory.update"  # in PRIVATE_KINDS: its payload is the user's words
SCHEDULES = (
    Schedule(BUDGETS_SWEEP, timedelta(minutes=10)),
    Schedule(BILLS_SWEEP, timedelta(minutes=30)),
    Schedule(PAYDAY_SWEEP, timedelta(minutes=30)),
    Schedule(RECEIPTS_PURGE, timedelta(hours=1)),
    Schedule(EMAIL_SWEEP, timedelta(minutes=15)),
    Schedule(NOTIFY_SWEEP, timedelta(minutes=5)),
    Schedule(SUBSCRIPTIONS_SWEEP, timedelta(hours=6)),
    Schedule(market_cases.REFRESH_JOB, timedelta(hours=1)),
    Schedule(market_cases.NEWS_JOB, timedelta(hours=1)),
    Schedule(plan_cases.FOLLOW_JOB, timedelta(hours=1)),
    Schedule(booking_cases.REMIND_JOB, timedelta(hours=1)),
)


class TelegramProgress:
    """A run's progress as one Telegram message, edited in place, with Cancel while
    it runs. Progress goes even in quiet hours: the user just asked for the work."""

    def __init__(self, telegram: TelegramClient) -> None:
        self._telegram = telegram

    async def show(self, run: Run, user: User, text: str) -> tuple[int | None, int | None]:
        chat_id = run.chat_id or user.telegram_chat_id
        if chat_id is None:
            return None, None
        buttons = [] if run.finished else [[Button("Cancel", f"run:cancel:{run.id}")]]
        if run.message_id is None:
            return chat_id, await self._telegram.send_message(chat_id, text, buttons or None)
        try:
            await self._telegram.edit_text(chat_id, run.message_id, text, buttons)
        except TelegramError as exc:
            # Unchanged text, or a message the user deleted: nothing to retry.
            log.info("could not edit a run's progress: %s", exc)
        return chat_id, run.message_id


def build_handlers(
    uow: UowFactory,
    telegram: TelegramClient,
    rates: RateSource,
    clock: Callable[[], datetime],
    archive: ReceiptStore | None = None,
    email: EmailRuntime | None = None,
    memory: MemoryWriter | None = None,
    departments: department_cases.Departments | None = None,
    prices: PriceSource | None = None,
    news: NewsSource | None = None,
) -> dict[str, Handler]:
    async def send(payload: dict[str, Any]) -> Defer | None:
        """Message a user on Telegram, but not during their quiet hours."""
        async with uow() as tx:
            user = await tx.ledger.get_user(UserId(UUID(payload["user_id"])))
        if user is None or user.telegram_chat_id is None:
            return None  # nobody to tell; nothing to retry
        # A message the user timed themselves (their daily summary) goes when they
        # asked, quiet hours or not.
        later = (
            None
            if payload.get("anytime")
            else quiet_until(clock().astimezone(ZoneInfo(user.timezone)))
        )
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
                mailbox = email.mailbox_for(connection.provider)
                if user is not None and mailbox is not None:
                    await email_cases.sweep(
                        uow,
                        mailbox,
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

    async def sweep_subscriptions(_: dict[str, Any]) -> None:
        async with uow() as tx:
            user_ids = await tx.planning.users_to_notify()
        await for_each_user(
            user_ids,
            "subscription check",
            lambda user: subscription_cases.check(uow, user, now=clock()),
        )

    async def update_memory(payload: dict[str, Any]) -> Defer | None:
        """Let the memory writer read what the user just said."""
        if memory is None:
            return None
        async with uow() as tx:
            user = await tx.ledger.get_user(UserId(UUID(payload["user_id"])))
        if user is not None:
            await memory.remember(uow, user, [str(m) for m in payload["messages"]], clock())
        return None

    async def expire_undo(payload: dict[str, Any]) -> None:
        """Take the Undo button off a reply, leaving any others on it."""
        try:
            await telegram.set_buttons(
                int(payload["chat_id"]), int(payload["message_id"]), kept_buttons(payload)
            )
        except TelegramError as exc:
            # Deleted, too old, or already without it: nothing to retry for a button.
            log.info("could not take Undo off a message: %s", exc)

    async def refresh_prices(_: dict[str, Any]) -> None:
        if prices is not None:
            fetched = await market_cases.refresh(uow, prices, now=clock())
            log.info("price refresh: fetched %d stocks", fetched)
            if fetched:  # new closes: see what the plans make of them now
                await follow_plans({})

    async def refresh_news(_: dict[str, Any]) -> None:
        if news is not None:
            fetched = await research_cases.refresh_news(uow, news, now=clock())
            log.info("news refresh: fetched %d stocks", fetched)

    async def follow_plans(_: dict[str, Any]) -> None:
        alerts = await plan_cases.follow_plans(uow, now=clock())
        if alerts:
            log.info("plans: queued %d alerts", alerts)

    async def travel_reminders(_: dict[str, Any]) -> None:
        sent = await booking_cases.remind_everyone(uow, now=clock())
        if sent:
            log.info("travel: queued %d reminders", sent)

    registry = departments or department_cases.default_registry()
    progress = TelegramProgress(telegram)

    async def department_step(payload: dict[str, Any]) -> None:
        """One step of a department's run; the step queues the next itself."""
        async with uow() as tx:
            user = await tx.ledger.get_user(UserId(UUID(payload["user_id"])))
        if user is not None:
            await department_cases.advance(
                uow,
                registry,
                progress,
                user,
                UUID(payload["run_id"]),
                now=clock(),
                tries=int(payload.get("tries", 0)),
            )

    return {
        market_cases.REFRESH_JOB: refresh_prices,
        market_cases.NEWS_JOB: refresh_news,
        plan_cases.FOLLOW_JOB: follow_plans,
        booking_cases.REMIND_JOB: travel_reminders,
        department_cases.STEP_JOB: department_step,
        UNDO_EXPIRE: expire_undo,
        MEMORY_UPDATE: update_memory,
        SUBSCRIPTIONS_SWEEP: sweep_subscriptions,
        NOTIFY_SWEEP: sweep_notifications,
        EMAIL_SWEEP: sweep_email,
        RECEIPTS_PURGE: purge_receipts,
        TELEGRAM_SEND: send,
        BUDGETS_SWEEP: sweep_budgets,
        BILLS_SWEEP: sweep_bills,
        PAYDAY_SWEEP: sweep_paydays,
    }
