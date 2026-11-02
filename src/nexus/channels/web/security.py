"""Session cookies, origin checks and CSRF for the web API.

Every route derives the user from the session cookie, never from the request.
State-changing requests must come from our own origin and carry the session's
CSRF token in ``X-CSRF-Token``.

Guests (people brought in by a trip invite) are default-deny: ``Auth``, which almost
every route uses, refuses them. Only the few routes that take ``TripAuth`` (opening
the trips shared with them, and signing out) let a guest in.
"""

import hmac
import ipaddress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from nexus.agent.service import AgentService
from nexus.agent.tools import UowFactory
from nexus.application import acting, ops
from nexus.application.access import SESSION_TTL, resolve_session
from nexus.application.demo import DemoGate, Use
from nexus.application.departments import Departments, default_registry
from nexus.application.email import EmailRuntime
from nexus.application.fx import RateSource
from nexus.application.ideas import IdeaFinder
from nexus.application.limits import RateLimited, RateLimiter
from nexus.application.moves import Explainer
from nexus.application.places import Places
from nexus.application.ports import ReceiptStore, StatementPageReader
from nexus.application.quotes import Quotes
from nexus.application.routes import Routes
from nexus.application.weather import Weather
from nexus.domain.access import Session
from nexus.domain.ledger import Role, User
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
    rates: RateSource
    archive: ReceiptStore | None = None  # receipt files; None = not kept
    email: EmailRuntime | None = None  # Connect Gmail; None = not offered
    # Per-user limits on heavy requests (statement imports).
    limits: RateLimiter = field(default_factory=RateLimiter)
    departments: Departments = field(default_factory=default_registry)
    prices: bool = False  # daily stock prices are set up
    news: bool = False  # company news and earnings dates are set up
    quotes: Quotes | None = None  # live stock quotes; None = not set up
    explainer: Explainer | None = None  # reads a stock's headlines for why it moved
    places: Places | None = None  # Google Maps places on trips; None = not set up
    routes: Routes | None = None  # travel times between a day's stops; None = not set up
    ideas: IdeaFinder | None = None  # quick ideas for a trip; None = not set up
    weather: Weather | None = None  # trip weather; None = not offered
    scans: StatementPageReader | None = None  # reads scanned statements; None = not set up
    demo: DemoGate | None = None  # public-demo allowances and spend cap; None = not counted


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


def set_session_cookie(
    response: Response,
    web: WebRuntime,
    token: str,
    *,
    embedded: bool = False,
    lifetime: timedelta = SESSION_TTL,
) -> None:
    """``lifetime`` is the session's own length (``Session.span``): the cookie never
    outlives a short session. ``embedded`` is for the Telegram Mini App, which Telegram's
    web clients show in an iframe: there the cookie must be SameSite=None (and Partitioned,
    so it is kept only for that embedding). Cross-site requests are still
    refused by the origin and CSRF checks. ``ttl`` is how long the browser keeps
    it: 30 days, or a public demo's 24 hours."""
    secure = not (
        web.settings.environment in {Environment.DEV, Environment.TEST}
        and web.origin.startswith("http://")
    )
    max_age = int(lifetime.total_seconds())
    if embedded and secure:
        # Built by hand: Starlette only writes Partitioned on Python 3.14+.
        # The token is URL-safe base64, so it needs no quoting.
        response.headers.append(
            "set-cookie",
            f"{COOKIE}={token}; HttpOnly; Max-Age={max_age}; Path=/; "
            "SameSite=None; Secure; Partitioned",
        )
        return
    response.set_cookie(
        COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


async def signed_in(request: Request, response: Response, web: Runtime) -> Authed:
    """Any signed-in user, guests included: the session, origin and CSRF checks. A session
    that slid forward on this request gets its cookie sent again with the new Max-Age."""
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not signed in")
    resolved = await resolve_session(web.uow(), token, now=web.clock())
    if resolved is None:
        raise HTTPException(status_code=401, detail="session expired")
    session, user, renewed = resolved
    if renewed:
        set_session_cookie(response, web, token, lifetime=session.span)
    ops.set_user(user.id)
    # From here every transaction of this request sees only this user's rows.
    acting.set_acting_user(user.id)
    acting.set_demo(user.is_demo)  # a public demo gets a third of the usual rate limits
    if request.method not in _SAFE:
        check_origin(request, web)
        given = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(given.encode(), session.csrf_token.encode()):
            raise HTTPException(status_code=403, detail="missing or wrong CSRF token")
    return Authed(user, session, token)


async def authenticated(request: Request, response: Response, web: Runtime) -> Authed:
    """A signed-in owner or member. Guests are refused, so a route is closed to them
    unless it asks for ``TripAuth`` instead."""
    authed = await signed_in(request, response, web)
    if authed.user.role is Role.GUEST:
        raise HTTPException(status_code=403, detail="guests can only open trips shared with them")
    return authed


Auth = Annotated[Authed, Depends(authenticated)]
# For the routes a guest may use: the trips shared with them, and the session itself.
# Those routes must check what the person may do on the trip they name.
TripAuth = Annotated[Authed, Depends(signed_in)]


def limit(web: WebRuntime, auth: Authed, kind: str) -> None:
    """429 when this user has done ``kind`` too often lately."""
    if not web.limits.allow(kind, auth.user.id):
        raise HTTPException(status_code=429, detail="Too many at once. Try again in a few minutes.")


async def demo_use(web: WebRuntime, auth: Authed, kind: Use | None = None, amount: int = 1) -> None:
    """For a request that costs model calls without going through the chat agent: 429 with
    the plain sentence when a public-demo account has used its allowance of ``kind`` (a
    photo or PDF read, say) or all demos have reached their daily spend cap. Nothing for
    anyone else."""
    if not auth.user.is_demo or web.demo is None:
        return
    refusal = await web.demo.use(auth.user.id, kind, amount)
    if refusal is not None:
        raise RateLimited(refusal)


def client_ip(request: Request, web: WebRuntime) -> str:
    """Who is asking, for limits per visitor. Behind proxies (``TRUSTED_PROXY_HOPS``) it is
    the X-Forwarded-For entry that many from the right, the one our own proxy added; what a
    visitor put further left is never believed. Without that header, or when it is not an
    address, the connection's own peer. An IPv6 address stands for its whole /64, which one
    home or phone holds."""
    peer = request.client.host if request.client else "unknown"
    hops = web.settings.trusted_proxy_hops
    entries = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",")]
    entries = [e for e in entries if e]
    candidate = entries[-hops] if hops and len(entries) >= hops else peer
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)
