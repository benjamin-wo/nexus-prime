"""Web access: owner-issued invites, Telegram login and sessions."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from nexus.application import trip_access
from nexus.application.ports import UnitOfWork
from nexus.application.users import RegisterUser, ensure_user
from nexus.domain.access import Invite, Session, new_token, token_hash
from nexus.domain.errors import Forbidden, InvalidInput
from nexus.domain.ledger import Role, User, UserId

INVITE_TTL = timedelta(hours=24)
SESSION_TTL = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class IssuedInvite:
    token: str
    invite: Invite


@dataclass(frozen=True, slots=True)
class LoggedIn:
    token: str
    session: Session
    user: User
    joined_trip: UUID | None = None  # the trip a trip invite added them to, if one did


async def create_invite(uow: UnitOfWork, actor: UserId, *, now: datetime) -> IssuedInvite:
    """A single-use invite, valid for 24 hours. Owners only."""
    async with uow:
        user = await uow.ledger.get_user(actor)
        if user is None or user.role is not Role.OWNER:
            raise Forbidden("only the owner can invite people")
        token = new_token()
        invite = Invite(uuid4(), token_hash(token), actor, now, now + INVITE_TTL)
        await uow.ledger.insert_invite(invite)
        await uow.commit()
    return IssuedInvite(token, invite)


async def log_in(
    uow: UnitOfWork,
    telegram_user_id: int,
    *,
    invite_token: str | None,
    defaults: RegisterUser,
    owner_telegram_id: int | None,
    now: datetime,
    trip_invite_token: str | None = None,
    display_name: str | None = None,
) -> LoggedIn:
    """Open a session for a verified Telegram identity.

    Without an invite, only the owner or someone who already redeemed one may
    log in. An invite is single use: redeeming it grants web access (creating
    the user if needed) and it can't be used again, by anyone.

    A trip invite (``trip_invite_token``) adds the person to that trip. Someone who
    can already sign in just gets the trip. Someone with no account gets a guest one,
    who can open that trip and nothing else, but only if the app's owner made the
    invite; otherwise they need an app invite first. An existing account's role is
    never changed, so someone who has an account without web access is refused.
    ``display_name`` is what other people on a trip see for them; it is refreshed on
    every sign-in.
    """
    joined: UUID | None = None
    async with uow:
        repo = uow.ledger
        user = await repo.get_user_by_telegram_id(telegram_user_id)
        if user is None and telegram_user_id == owner_telegram_id:
            owner = replace(defaults, telegram_user_id=telegram_user_id, role=Role.OWNER)
            user = (await ensure_user(repo, owner)).user
        if invite_token and not (user is not None and user.has_web_access):
            invite = await repo.get_invite(token_hash(invite_token), for_update=True)
            if invite is None or not invite.usable(now):
                raise Forbidden("this invite is invalid, used or expired")
            if user is None:
                user = (await ensure_user(repo, defaults)).user
            await repo.redeem_invite(invite.id, user.id, now)
            await repo.grant_web_access(user.id, now)
            user = await repo.get_user(user.id)
            if user is None:  # pragma: no cover - just fetched
                raise RuntimeError("user vanished during login")
        elif trip_invite_token and not (user is not None and user.has_web_access):
            user = await _guest_for_trip_invite(uow, user, trip_invite_token, defaults, now)
        elif user is None or not user.has_web_access:
            raise Forbidden("you need an invite to use the web app")

        if trip_invite_token:
            joined = await _join_trip(
                uow, user, trip_invite_token, now, strict=user.role is Role.GUEST
            )
        if display_name and display_name != user.display_name:
            await repo.set_display_name(user.id, display_name)
            user = replace(user, display_name=display_name)

        token = new_token()
        session = Session(token_hash(token), user.id, new_token(), now, now + SESSION_TTL)
        await repo.insert_session(session)
        await uow.commit()
    return LoggedIn(token, session, user, joined)


TRIP_INVITE_REFUSED = "this trip invite is invalid, used or expired"


async def _guest_for_trip_invite(
    uow: UnitOfWork, user: User | None, token: str, defaults: RegisterUser, now: datetime
) -> User:
    """The guest account a trip invite makes for someone who can't sign in yet."""
    invite = await uow.trips.get_trip_invite(token_hash(token), for_update=True)
    if invite is None or not invite.usable(now):
        raise Forbidden(TRIP_INVITE_REFUSED)
    if user is not None or not invite.may_create_guest:
        # An account that exists is never changed to fit: it needs an app invite.
        raise Forbidden("ask the trip's owner for an app invite to use the web app")
    registration = await ensure_user(uow.ledger, replace(defaults, role=Role.GUEST))
    if not registration.created:  # an account appeared meanwhile: leave it as it is
        raise Forbidden("ask the trip's owner for an app invite to use the web app")
    made = registration.user
    await uow.ledger.grant_web_access(made.id, now)
    found = await uow.ledger.get_user(made.id)
    if found is None:  # pragma: no cover - just made
        raise RuntimeError("user vanished during login")
    return found


async def _join_trip(
    uow: UnitOfWork, user: User, token: str, now: datetime, *, strict: bool
) -> UUID | None:
    """Adds the signed-in user to the trip the invite is for, when it can be used. A
    link that can't be used (or is the user's own trip's, or the trip is full) changes
    nothing here: whoever could sign in still can. ``strict`` is for a guest, who has
    no other reason to sign in, so a full trip is an error."""
    invite = await uow.trips.get_trip_invite(token_hash(token), for_update=True)
    if invite is None or invite.owner_id == user.id:
        return None
    try:
        joined = await trip_access.join_with_invite(uow, user, invite, now=now)
    except InvalidInput:
        if strict:
            raise
        return None
    return joined.trip_id if joined else None


async def resolve_session(
    uow: UnitOfWork, token: str, *, now: datetime
) -> tuple[Session, User] | None:
    """The live session and its user, or None if unknown, expired or revoked."""
    async with uow:
        session = await uow.ledger.get_session(token_hash(token))
        if session is None or not session.active(now):
            return None
        user = await uow.ledger.get_user(session.user_id)
    if user is None or not user.has_web_access:
        return None
    return session, user


async def log_out(uow: UnitOfWork, token: str, *, now: datetime) -> None:
    async with uow:
        await uow.ledger.revoke_session(token_hash(token), now)
        await uow.commit()
