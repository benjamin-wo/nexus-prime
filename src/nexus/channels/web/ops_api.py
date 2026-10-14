"""GET /api/ops/report: the ops report for the last ``hours`` (default 24, at most 30
days), as JSON or, with ``format=md``, Markdown. POST /api/ops/tickets syncs the
report's problems to GitHub issues now.

Only the owner, signed in, or a script with ``Authorization: Bearer <OPS_TOKEN>`` can
read it; anyone else gets a 404, as if it weren't there. It holds no user data: event
names, timings, status codes, error types and hashed user references.
"""

import hmac
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from nexus.application import ops_report
from nexus.channels.web.security import authenticated, runtime
from nexus.domain.ledger import Role
from nexus.infra.ops_gather import WebhookInfo, build_report
from nexus.jobs.ops_tickets import sync_tickets
from nexus.settings import Settings

router = APIRouter()


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
    built = await build_report(engine, settings, webhook_info(request.app), hours)
    if format == "md":
        return PlainTextResponse(ops_report.markdown(built), media_type="text/markdown")
    return built.as_json()


def webhook_info(app: Any) -> WebhookInfo | None:
    telegram = getattr(app.state, "telegram", None)
    info: WebhookInfo | None = getattr(getattr(telegram, "client", None), "webhook_info", None)
    return info


@router.post("/api/ops/tickets")
async def tickets(request: Request) -> dict[str, list[int]]:
    """Sync the ops tickets now, as the job does every 6 hours."""
    settings: Settings = request.app.state.settings
    await _allowed(request, settings)
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="not ready")
    if not settings.ops_tickets_enabled:
        raise HTTPException(
            status_code=409, detail="OPS_GITHUB_TOKEN and OPS_GITHUB_REPO aren't set"
        )
    synced = await sync_tickets(engine, settings, webhook_info(request.app))
    return {
        "opened": synced.opened,
        "updated": synced.updated,
        "reopened": synced.reopened,
        "closed": synced.closed,
    }
