"""Web API: sign-in, device sign-in, who am I, demo, time zone, invites."""

import hashlib
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import Field

from nexus.agent.graph import thread_id
from nexus.application import access, erasure, ops
from nexus.application import demo as demo_cases
from nexus.application import device_signin as device_cases
from nexus.application import whereabouts as whereabouts_cases
from nexus.application.users import RegisterUser
from nexus.channels.web.security import (
    COOKIE,
    Auth,
    Runtime,
    TripAuth,
    WebRuntime,
    check_origin,
    clear_session_cookie,
    client_ip,
    set_session_cookie,
)
from nexus.channels.web.shapes import MeOut, Model, me_out
from nexus.channels.web.telegram_login import (
    LoginRejected,
    TelegramIdentity,
    verify_login,
    verify_webapp,
)
from nexus.domain.demo import forbid as forbid_demo
from nexus.domain.errors import Forbidden
from nexus.domain.ledger import (
    Role,
    User,
    ZoneSource,
)

router = APIRouter(prefix="/api")
# The one page-level route the bot's sign-in link needs, outside /api (the SPA owns /login).
login_link_router = APIRouter()


class ConfigOut(Model):
    bot_username: str


@router.get("/config")
async def config(web: Runtime) -> ConfigOut:
    """What the sign-in page needs before anyone is signed in."""
    return ConfigOut(bot_username=await web.bot_username())


# --- auth ---------------------------------------------------------------------------


class LoginIn(Model):
    telegram: dict[str, Any]
    invite: str | None = None
    # A trip invite (not an app invite): adds the person to that trip, and may make a
    # guest account for someone with none.
    trip_invite: str | None = None


def _bot_token(web: WebRuntime) -> str:
    token = web.settings.telegram_bot_token
    if token is None:  # pragma: no cover - web is only enabled with Telegram
        raise HTTPException(status_code=404)
    return token.get_secret_value()


async def _log_in(
    web: WebRuntime, telegram: dict[str, Any], invite: str | None, trip_invite: str | None = None
) -> access.LoggedIn:
    now = web.clock()
    try:
        identity = verify_login(telegram, _bot_token(web), now=now)
    except LoginRejected as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return await _open_session(web, identity, invite, now, trip_invite)


async def _open_session(
    web: WebRuntime,
    identity: TelegramIdentity,
    invite: str | None,
    now: datetime,
    trip_invite: str | None = None,
    *,
    renewable: bool = True,
) -> access.LoggedIn:
    return await access.log_in(
        web.uow(),
        identity.telegram_user_id,
        invite_token=invite,
        defaults=RegisterUser(
            telegram_user_id=identity.telegram_user_id,
            telegram_chat_id=identity.telegram_user_id,
            home_currency=web.settings.default_home_currency,
            timezone=web.settings.default_timezone,
            role=Role.MEMBER,
        ),
        owner_telegram_id=web.settings.admin_telegram_chat_id,
        now=now,
        trip_invite_token=trip_invite,
        display_name=identity.display_name,
        renewable=renewable,
    )


@router.post("/auth/telegram")
async def login(body: LoginIn, request: Request, response: Response, web: Runtime) -> MeOut:
    check_origin(request, web)
    logged_in = await _log_in(web, body.telegram, body.invite, body.trip_invite)
    set_session_cookie(response, web, logged_in.token, lifetime=logged_in.session.span)
    return me_out(logged_in.user, logged_in.session.csrf_token, logged_in.joined_trip)


class WebAppLoginIn(Model):
    init_data: str = Field(min_length=1, max_length=4096)
    # A trip invite, as for the widget sign-in: the Mini App has no other way to carry it.
    trip_invite: str | None = None


@router.post("/auth/webapp")
async def login_webapp(
    body: WebAppLoginIn, request: Request, response: Response, web: Runtime
) -> MeOut:
    """Sign in from inside Telegram (the Mini App), with no widget or phone number."""
    check_origin(request, web)
    now = web.clock()
    try:
        identity = verify_webapp(body.init_data, _bot_token(web), now=now)
    except LoginRejected as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    # The Mini App signs in again from Telegram's launch data whenever its session has ended,
    # and its partitioned cookie is not one to re-send from a later request: so it does not slide.
    logged_in = await _open_session(web, identity, None, now, body.trip_invite, renewable=False)
    set_session_cookie(
        response, web, logged_in.token, embedded=True, lifetime=logged_in.session.span
    )
    return me_out(logged_in.user, logged_in.session.csrf_token, logged_in.joined_trip)


@router.get("/auth/telegram/callback", include_in_schema=False)
async def login_callback(request: Request, web: Runtime) -> Response:
    """The Login Widget's redirect mode: Telegram sends the signed fields here.

    Redirect mode avoids the widget's JavaScript callback, which would need
    'unsafe-eval' in the Content-Security-Policy.
    """
    params = dict(request.query_params)
    invite = params.pop("invite", None)
    trip_invite = params.pop("trip_invite", None)
    try:
        logged_in = await _log_in(web, params, invite, trip_invite)
    except HTTPException:
        return RedirectResponse("/login?error=signin", status_code=303)
    except Forbidden:
        return RedirectResponse("/login?error=access", status_code=303)
    # Someone just added to a trip lands on it.
    where = f"/travel/trips/{logged_in.joined_trip}" if logged_in.joined_trip else "/"
    response = RedirectResponse(where, status_code=303)
    set_session_cookie(response, web, logged_in.token, lifetime=logged_in.session.span)
    return response


_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


# Link previews (Telegram's own crawler above all) fetch an address the moment it is sent
# in a chat; a sign-in link must survive that.
_PREVIEW_BOTS = ("telegrambot", "twitterbot", "facebookexternalhit", "slackbot", "discordbot")


@login_link_router.get("/login/link/{token}", include_in_schema=False)
async def login_with_link(token: str, request: Request, web: Runtime) -> Response:
    """The link the bot's ``/web`` sends: signs the person in on whatever browser opens it,
    once, within five minutes, then goes to the app. A link that is unknown, used or expired
    goes to the sign-in page with a note. Nothing here puts the token in a log or an event
    (the access log's path is redacted, see ``infra.logs``)."""
    if any(bot in request.headers.get("user-agent", "").lower() for bot in _PREVIEW_BOTS):
        return Response(status_code=204)  # a preview must not spend the link
    try:
        logged_in = await access.redeem_login_link(web.uow(), token, now=web.clock())
    except Forbidden:
        ops.emit("access", "login_link", ok=False, reason="refused")
        return RedirectResponse("/login?error=link", status_code=303, headers=_NO_STORE)
    ops.set_user(logged_in.user.id)
    ops.emit("access", "login_link", ok=True)
    response = RedirectResponse("/", status_code=303, headers=_NO_STORE)
    set_session_cookie(response, web, logged_in.token, lifetime=logged_in.session.span)
    return response


# --- signing in from the iOS app (see application/device_signin.py) ------------------------


class DeviceStartOut(Model):
    code: str  # shown as XXXX-XXXX
    poll_id: str
    expires_in: int
    bot_username: str


@router.post("/auth/device")
async def start_device_signin(request: Request, web: Runtime) -> DeviceStartOut:
    """The app asks for a code to approve in Telegram. No session yet, so no CSRF token (as for
    the Telegram sign-in), but the origin must be our own. 429 past 10 an hour-ish per address."""
    check_origin(request, web)
    if not web.limits.allow("device_start", client_ip(request, web), demo=False):
        raise HTTPException(status_code=429, detail="Too many sign-in codes. Try again later.")
    try:
        started = web.devices.start()
    except device_cases.StoreFull as exc:
        raise HTTPException(status_code=503, detail="Try again in a few minutes.") from exc
    ops.emit("access", "device_code", ok=True, pending=len(web.devices))
    return DeviceStartOut(
        code=device_cases.display_code(started.code),
        poll_id=started.poll_id,
        expires_in=started.expires_in,
        bot_username=await web.bot_username(),
    )


@router.get("/auth/device/{poll_id}")
async def poll_device_signin(poll_id: str, request: Request, web: Runtime) -> Response:
    """Pending, or approved with the one-time login path (then the request is gone). 404 for an
    unknown or expired one. Never cached, and nothing here logs the poll id."""
    headers = {"Cache-Control": "no-store"}
    if not web.limits.allow("device_poll_ip", client_ip(request, web), demo=False):
        raise HTTPException(status_code=429, detail="Too many requests.")
    if not web.devices.knows_poll(poll_id):
        raise HTTPException(status_code=404)
    # Keyed by a hash so the limiter, like the store, never holds the secret itself.
    key = hashlib.sha256(poll_id.encode()).hexdigest()
    if not web.limits.allow("device_poll", key, demo=False):
        raise HTTPException(status_code=429, detail="Too many requests.")
    state = web.devices.poll(poll_id)
    if state is None:
        raise HTTPException(status_code=404)
    if isinstance(state, device_cases.Pending):
        return JSONResponse({"status": "pending"}, headers=headers)
    try:
        token = await access.issue_login_link(web.uow(), state.user_id, now=web.clock())
    except Forbidden as exc:  # lost web access since approving
        ops.emit("access", "device_signin", ok=False, reason="refused")
        raise HTTPException(status_code=404) from exc
    ops.emit("access", "device_signin", ok=True)
    return JSONResponse(
        {"status": "approved", "login_path": f"/login/link/{token}"}, headers=headers
    )


@router.post("/auth/logout", status_code=204)
async def logout(auth: TripAuth, response: Response, web: Runtime) -> None:
    await access.log_out(web.uow(), auth.token, now=web.clock())
    clear_session_cookie(response)


@router.get("/me")
async def me(auth: TripAuth, web: Runtime) -> MeOut:
    usage = await web.demo.usage(auth.user.id) if auth.user.is_demo and web.demo else None
    return me_out(auth.user, auth.session.csrf_token, demo=usage)


class DemoOut(Model):
    expires_at: datetime


@router.post("/demo")
async def start_demo(request: Request, response: Response, web: Runtime) -> DemoOut:
    """Start a public demo: a private account of the visitor's own, filled with made-up
    data, signed in at once. No auth. 403 ``demo_off`` unless DEMO_ENABLED; a visitor who
    already has a live demo gets that one back, and one signed in as themselves gets 409
    ``signed_in`` (their session is never replaced); 429 past five new demos an hour from one
    address; 503 ``demo_unavailable`` if the account could not be filled (it is erased, no
    cookie is set). No CSRF token is needed (there is no session yet), as for the Telegram
    sign-in; a request from another origin is 400, so 403 only ever means demos are off."""
    try:
        check_origin(request, web)
    except HTTPException as exc:  # 403 here would read as "demos are off"
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    if not web.settings.demo_enabled:
        raise HTTPException(status_code=403, detail=demo_cases.DEMO_OFF)
    token = request.cookies.get(COOKIE)
    if token:
        resolved = await access.resolve_session(web.uow(), token, now=web.clock())
        if resolved is not None and resolved.user.is_demo:
            return DemoOut(expires_at=resolved.session.expires_at)
        if resolved is not None:
            # Someone signed in as themselves keeps their own session: a demo never
            # replaces it (the web sends them Home instead).
            raise HTTPException(status_code=409, detail="signed_in")
    if not web.limits.allow("demo", client_ip(request, web), demo=False):
        raise HTTPException(status_code=429, detail=demo_cases.BUSY)

    async def erase(user: User) -> None:
        await erasure.delete_user_data(
            web.uow, user, chat_thread=thread_id(user.id), store=web.archive, email=None
        )

    try:
        logged_in = await demo_cases.start_demo(web.uow, now=web.clock(), erase=erase)
    except demo_cases.DemoUnavailable as exc:
        raise HTTPException(status_code=503, detail="demo_unavailable") from exc
    set_session_cookie(response, web, logged_in.token, lifetime=demo_cases.DEMO_TTL)
    return DemoOut(expires_at=logged_in.session.expires_at)


class TimezoneIn(Model):
    timezone: str = Field(max_length=64)
    # "phone": the browser's own zone, sent on its own. "manual": the user picked it in
    # Settings (an explicit statement, kept as source "chat").
    source: Literal["phone", "manual"]


class TimezoneOut(Model):
    timezone: str
    home_timezone: str
    timezone_source: str
    timezone_set_at: datetime | None = None
    # Whether the current zone is now a different one than before the call.
    changed: bool


def timezone_out(reported: whereabouts_cases.Reported) -> TimezoneOut:
    user = reported.user
    return TimezoneOut(
        timezone=user.timezone,
        home_timezone=user.home_timezone,
        timezone_source=user.timezone_source.value,
        timezone_set_at=user.timezone_set_at,
        changed=reported.changed,
    )


@router.post("/me/timezone")
async def set_my_timezone(body: TimezoneIn, auth: Auth, web: Runtime) -> TimezoneOut:
    """Say where the user is. A phone that repeats the zone they are in only refreshes
    when it last said so; a new zone is told once on Telegram (not when picked by hand)."""
    phone = body.source == "phone"
    reported = await whereabouts_cases.report_zone(
        web.uow(),
        auth.user.id,
        body.timezone,
        ZoneSource.PHONE if phone else ZoneSource.CHAT,
        web.clock(),
        notify=phone,
    )
    return timezone_out(reported)


@router.post("/me/timezone/home")
async def set_my_timezone_home(auth: Auth, web: Runtime) -> TimezoneOut:
    """Back to the user's home time zone."""
    reported = await whereabouts_cases.report_zone(
        web.uow(), auth.user.id, None, ZoneSource.HOME, web.clock(), notify=False
    )
    return timezone_out(reported)


class InviteOut(Model):
    url: str
    expires_at: datetime


@router.post("/invites")
async def invite(auth: Auth, web: Runtime) -> InviteOut:
    forbid_demo(auth.user, "Inviting people")
    issued = await access.create_invite(web.uow(), auth.user.id, now=web.clock())
    return InviteOut(url=f"{web.origin}/invite/{issued.token}", expires_at=issued.invite.expires_at)
