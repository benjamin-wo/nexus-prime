"""What each kind of job does."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import budgets as budget_cases
from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.fx import RateSource
from nexus.channels.telegram.client import TelegramClient
from nexus.domain.ledger import UserId
from nexus.domain.planning import quiet_until
from nexus.jobs.runner import Defer, Handler, Schedule

log = logging.getLogger(__name__)

BUDGETS_SWEEP = "budgets.sweep"
SCHEDULES = (Schedule(BUDGETS_SWEEP, timedelta(minutes=10)),)


def build_handlers(
    uow: UowFactory,
    telegram: TelegramClient,
    rates: RateSource,
    clock: Callable[[], datetime],
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
        await telegram.send_message(user.telegram_chat_id, str(payload["text"]))
        return None

    async def sweep_budgets(_: dict[str, Any]) -> None:
        async with uow() as tx:
            user_ids = await tx.planning.users_with_budgets()
        for user_id in user_ids:
            try:
                async with uow() as tx:
                    user = await tx.ledger.get_user(user_id)
                if user is not None:
                    await budget_cases.check_budgets(uow, rates, user, now=clock())
            except Exception:
                # One user's failure must not stop the others; the next sweep retries.
                log.exception("budget check failed for a user")
        return None

    return {TELEGRAM_SEND: send, BUDGETS_SWEEP: sweep_budgets}
