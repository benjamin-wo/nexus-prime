"""Web access: owner-issued invites, Telegram login and sessions."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import uuid4

from nexus.application.ports import UnitOfWork
from nexus.application.users import RegisterUser, ensure_user
from nexus.domain.access import Invite, Session, new_token, token_hash
from nexus.domain.errors import Forbidden
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
) -> LoggedIn:
    """Open a session for a verified Telegram identity.

    Without an invite, only the owner or someone who already redeemed one may
    log in. An invite is single use: redeeming it grants web access (creating
    the user if needed) and it can't be used again, by anyone.
    """
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
        elif user is None or not user.has_web_access:
            raise Forbidden("you need an invite to use the web app")

        token = new_token()
        session = Session(token_hash(token), user.id, new_token(), now, now + SESSION_TTL)
        await repo.insert_session(session)
        await uow.commit()
    return LoggedIn(token, session, user)


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
