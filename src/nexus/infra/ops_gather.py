"""Builds the ops report from the database and live checks: used by the report
endpoint and the ticket job alike."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import ops_report
from nexus.application.clock import utcnow
from nexus.infra import ops_store
from nexus.infra.http import timed_client
from nexus.jobs.handlers import SCHEDULES
from nexus.settings import Settings

log = logging.getLogger(__name__)

OPENROUTER_KEY = "https://openrouter.ai/api/v1/key"
CHECK_SECONDS = 10.0

WebhookInfo = Callable[[], Awaitable[dict[str, Any]]]


async def build_report(
    engine: AsyncEngine, settings: Settings, webhook_info: WebhookInfo | None, hours: int
) -> ops_report.Report:
    now = utcnow()
    since = now - timedelta(hours=hours)
    window, jobs, state, webhook, credit, agent = await asyncio.gather(
        ops_store.read_window(engine, since, now),
        ops_store.read_jobs(engine, now, since),
        ops_store.read_state(engine, date(now.year, now.month, 1)),
        _webhook(webhook_info),
        _openrouter(settings),
        ops_store.read_agent_events(engine, now - timedelta(days=ops_report.MISTAKES_DAYS), now),
    )
    checks = ops_report.Checks(
        now=now,
        since=since,
        schedules=[(s.kind, s.every) for s in SCHEDULES] if settings.run_jobs else [],
        stuck_jobs=jobs.stuck,
        overdue_jobs=jobs.overdue,
        failed_jobs=jobs.failed,
        last_done=jobs.last_done,
        webhook=webhook,
        openrouter=credit,
        broken_mailboxes=state["broken_mailboxes"],
        search_credits=state["search_credits"],
        search_monthly=settings.tavily_monthly_credits if settings.tavily_api_key else None,
        database_bytes=state["database_bytes"],
        mistakes=agent,
    )
    return ops_report.build(window.events, window.requests, window.calls, checks)


async def _webhook(info: WebhookInfo | None) -> dict[str, Any] | None:
    if info is None:
        return None
    try:
        found = await asyncio.wait_for(info(), CHECK_SECONDS)
    except Exception as exc:
        log.info("ops report: couldn't read Telegram's webhook info: %s", type(exc).__name__)
        return None
    return {
        k: found.get(k)
        for k in ("pending_update_count", "last_error_date", "last_error_message")
        if k in found
    }


async def _openrouter(settings: Settings) -> dict[str, Any] | None:
    key = settings.openrouter_api_key
    if key is None:
        return None
    try:
        async with timed_client(timeout=CHECK_SECONDS) as http:
            response = await http.get(
                OPENROUTER_KEY, headers={"Authorization": f"Bearer {key.get_secret_value()}"}
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
    except Exception as exc:
        log.info("ops report: couldn't read OpenRouter's key status: %s", type(exc).__name__)
        return None
    return {
        k: data.get(k)
        for k in ("usage", "limit", "limit_remaining", "usage_daily")
        if data.get(k) is not None
    }
