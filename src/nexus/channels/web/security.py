"""Session cookies, origin checks and CSRF for the web API.

Every route derives the user from the session cookie, never from the request.
State-changing requests must come from our own origin and carry the session's
CSRF token in ``X-CSRF-Token``.
"""

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from nexus.agent.service import AgentService
from nexus.agent.tools import UowFactory
from nexus.application.access import SESSION_TTL, resolve_session
from nexus.domain.access import Session
from nexus.domain.ledger import User
from nexus.settings import Environment, Settings

COOKIE = "nexus_session"
_SAFE = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True, slots=True)
class WebRuntime:
    settings: Settings
    origin: str
    uow: UowFactory
    service: AgentService
    clock: Callable[[], datetime]
    bot_username: Callable[[], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class Authed:
    user: User
    session: Session
    token: str


def runtime(request: Request) -> WebRuntime:
    web: WebRuntime | None = getattr(request.app.state, "web", None)
    if web is None:
        raise HTTPException(status_code=404)
    return web


Runtime = Annotated[WebRuntime, Depends(runtime)]


def check_origin(request: Request, web: WebRuntime) -> None:
    """Refuse cross-site requests: Origin (or Referer) must be our own."""
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer", "")
        origin = referer[: len(web.origin)] if referer.startswith(web.origin) else None
    if origin != web.origin:
        raise HTTPException(status_code=403, detail="cross-origin request refused")


def set_session_cookie(response: Response, web: WebRuntime, token: str) -> None:
    secure = not (
        web.settings.environment in {Environment.DEV, Environment.TEST}
        and web.origin.startswith("http://")
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


async def authenticated(request: Request, web: Runtime) -> Authed:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not signed in")
    resolved = await resolve_session(web.uow(), token, now=web.clock())
    if resolved is None:
        raise HTTPException(status_code=401, detail="session expired")
    session, user = resolved
    if request.method not in _SAFE:
        check_origin(request, web)
        given = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(given.encode(), session.csrf_token.encode()):
            raise HTTPException(status_code=403, detail="missing or wrong CSRF token")
    return Authed(user, session, token)


Auth = Annotated[Authed, Depends(authenticated)]
