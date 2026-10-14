"""GET /api/ops/report: the ops report for the last ``hours`` (default 24, at most 30
days), as JSON or, with ``format=md``, Markdown.

Only the owner, signed in, or a script with ``Authorization: Bearer <OPS_TOKEN>`` can
read it; anyone else gets a 404, as if it weren't there. It holds no user data: event
names, timings, status codes, error types and hashed user references.
"""

import asyncio
import hmac
import logging
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from nexus.application import ops_report
from nexus.application.clock import utcnow
from nexus.channels.web.security import authenticated, runtime
from nexus.domain.ledger import Role
from nexus.infra import ops_store
from nexus.infra.http import timed_client
from nexus.jobs.handlers import SCHEDULES
from nexus.settings import Settings

log = logging.getLogger(__name__)
router = APIRouter()

OPENROUTER_KEY = "https://openrouter.ai/api/v1/key"
CHECK_SECONDS = 10.0


async def _allowed(request: Request, settings: Settings) -> None:
    given = request.headers.get("authorization", "")
    token = settings.ops_token
    if token is not None and given.startswith("Bearer "):
        if hmac.compare_digest(given[7:].encode(), token.get_secret_value().encode()):
            return
        raise HTTPException(status_code=404)
    try:
        authed = await authenticated(request, runtime(request))
    except HTTPException:
        raise HTTPException(status_code=404) from None
    if authed.user.role is not Role.OWNER:
        raise HTTPException(status_code=404)


@router.get("/api/ops/report", response_model=None)
async def report(
    request: Request,
    hours: int = Query(24, ge=1, le=24 * 30),
    format: Literal["json", "md"] = "json",
) -> dict[str, Any] | PlainTextResponse:
    settings: Settings = request.app.state.settings
    await _allowed(request, settings)
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="not ready")
    now = utcnow()
    since = now - timedelta(hours=hours)
    window, jobs, state, webhook, credit = await asyncio.gather(
        ops_store.read_window(engine, since, now),
        ops_store.read_jobs(engine, now, since),
        ops_store.read_state(engine, date(now.year, now.month, 1)),
        _webhook(request),
        _openrouter(settings),
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
    )
    built = ops_report.build(window.events, window.requests, window.calls, checks)
    if format == "md":
        return PlainTextResponse(ops_report.markdown(built), media_type="text/markdown")
    return built.as_json()


async def _webhook(request: Request) -> dict[str, Any] | None:
    telegram = getattr(request.app.state, "telegram", None)
    info = getattr(getattr(telegram, "client", None), "webhook_info", None)
    if info is None:
        return None
    try:
        found: dict[str, Any] = await asyncio.wait_for(info(), CHECK_SECONDS)
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
