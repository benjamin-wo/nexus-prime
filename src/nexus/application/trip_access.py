"""Shared trips: who may open a trip, inviting people to it, and what they changed.

Every request about a trip first asks ``open_trip`` (or ``open_booking``) what the
person may do. It answers with the trip's owner, and the ordinary trip use cases then
run as that owner: a member's edits are the owner's trip being edited, so nothing
needs a second copy. Someone with no access gets the same "no trip" as for a trip that
doesn't exist, so the answer never says whether a trip is there.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from nexus.application import trips as trip_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import UnitOfWork
from nexus.domain.access import new_token, token_hash
from nexus.domain.bookings import Booking
from nexus.domain.errors import Forbidden, InvalidInput, NotFound
from nexus.domain.ledger import Role, User, UserId
from nexus.domain.trip_access import (
    DIGEST_EVERY,
    INVITE_TTL,
    MAX_MEMBERS,
    MAX_OPEN_INVITES,
    Activity,
    TripAccess,
    TripInvite,
    TripMember,
    clean_name,
    clean_summary,
    digest_key,
    digest_text,
    without_money,
    without_trip_money,
)
from nexus.domain.trips import Readiness, Trip, TripStatus, describe_trip

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]

OWNER_ONLY = "only the trip's owner can do that"
NO_INVITE = "this invite is invalid, used or expired"
ACTIVITY_SHOWN = 20
DIGEST_JOB = "trip.activity_digest"


@dataclass(frozen=True, slots=True)
class Opened:
    """A trip (or booking) the person may reach. Run its use cases as ``owner``."""

    access: TripAccess
    owner: User
    booking: Booking | None = None


async def _owner_of(uow: UnitOfWork, actor: User, access: TripAccess) -> User:
    if access.owner_id == actor.id:
        return actor
    owner = await uow.ledger.get_user(access.owner_id)
    if owner is None:  # pragma: no cover - the trip's foreign key holds the owner
        raise NotFound("no trip with that id")
    return owner


async def open_trip(
    uow: UnitOfWork, actor: User, trip_id: UUID, *, owner_only: bool = False
) -> Opened:
    """What ``actor`` may do on the trip. NotFound for a trip they have no part in (as
    for one that doesn't exist); Forbidden for a member where only the owner may act."""
    async with uow:
        access = await uow.trips.trip_access(actor.id, trip_id)
        if access is None:
            raise NotFound("no trip with that id")
        if owner_only and not access.is_owner:
            raise Forbidden(OWNER_ONLY)
        return Opened(access, await _owner_of(uow, actor, access))


async def open_booking(
    uow: UnitOfWork, actor: User, booking_id: UUID, *, owner_only: bool = False
) -> Opened:
    """The same for a booking, through its trip; one on no trip is its owner's alone."""
    async with uow:
        access = await uow.trips.booking_access(actor.id, booking_id)
        if access is None:
            raise NotFound("no booking with that id")
        if owner_only and not access.is_owner:
            raise Forbidden(OWNER_ONLY)
        booking = await uow.trips.get_booking(access.owner_id, booking_id)
        if booking is None:  # pragma: no cover - deleted in between
            raise NotFound("no booking with that id")
        return Opened(access, await _owner_of(uow, actor, access), booking)


# --- what a member sees of the trip page -----------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanView:
    """The trip page as a member gets it: the plan and nothing else. Built from the
    trip and its bookings alone, so no ledger query is ever made for it."""

    trip: Trip  # without budget, set-aside or planned amounts
    today: date
    status: TripStatus
    bookings: list[Booking]  # without costs
    ready: Readiness  # with no budget check


async def plan_view(
    uow: UnitOfWork, owner_id: UserId, trip_id: UUID, viewer: User, *, now: datetime
) -> PlanView:
    async with uow:
        trip = await uow.trips.get_trip(owner_id, trip_id)
        if trip is None:
            raise NotFound("no trip with that id")
        bookings = await uow.trips.list_bookings(owner_id, trip_id=trip_id)
    today = trip_cases.local_today(viewer, now)
    ready = trip_cases.readiness_of(trip, bookings)
    return PlanView(
        trip=without_trip_money(trip),
        today=today,
        status=trip.status(today),
        bookings=[without_money(b) for b in bookings],
        # The budget isn't theirs to see, so it isn't one of the things left to do.
        ready=Readiness(ready.nights_without_stay, ready.has_transport, False),
    )


async def shared_trips(uow: UnitOfWork, member_id: UserId) -> list[tuple[Trip, str | None]]:
    """The trips someone was added to, money removed, each with its owner's name."""
    async with uow:
        found = await uow.trips.list_member_trips(member_id)
    return [(without_trip_money(t), name) for t, name in found]


# --- finding a trip by name, for the chat ------------------------------------------------


@dataclass(frozen=True, slots=True)
class Found:
    """A trip found by name for someone in chat: one of their own, or one they were added
    to. ``trip`` is as they may see it, so a member's has no money in it. Plan edits run
    as the trip's owner (``owner_id``) and are noted in its activity; anything with money
    in it, or that changes the trip itself, asks ``require_owner`` first."""

    trip: Trip
    opened: Opened

    @property
    def shared(self) -> bool:
        """True when the person is a member of someone else's trip."""
        return not self.opened.access.is_owner

    @property
    def owner_id(self) -> UserId:
        return self.opened.access.owner_id

    @property
    def owner(self) -> User:
        return self.opened.owner

    @property
    def owner_label(self) -> str:
        return clean_name(self.owner.display_name) or "the trip's owner"

    @property
    def whose(self) -> str:
        """What follows the trip's name in a sentence: nothing for one's own trip."""
        return f" ({self.owner_label}'s trip)" if self.shared else ""


def refusal(owner_label: str) -> str:
    return f"Only {owner_label} can change money or the trip's details on a shared trip."


def require_owner(found: Found) -> Trip:
    """The trip, for what only its owner may do (money, dates, travellers, deleting it,
    sharing it). Forbidden, saying who can, for a member."""
    if found.shared:
        raise Forbidden(refusal(found.owner_label))
    return found.trip


def _candidate(trip: Trip, owner: str | None) -> str:
    whose = "yours" if owner is None else f"{clean_name(owner) or 'someone'}'s"
    return f"{trip.destination} ({trip.start:%d %b %Y} to {trip.end:%d %b %Y}, {whose})"


async def find_trip(uow: UowFactory, actor: User, name: str | None, *, now: datetime) -> Found:
    """A trip by its destination ("Japan" finds "Tokyo, Japan") among the actor's own
    trips and the ones they were added to; with no name, the one that's on or next.
    Several matching trips where one is someone else's is an InvalidInput listing them,
    so the person is asked which (several of their own: the one that's on or next, as
    ever). Access is checked by ``open_trip``, as for the web."""
    own = await trip_cases.list_trips(uow(), actor.id)
    shared = await shared_trips(uow(), actor.id)
    owners: dict[UUID, str | None] = {t.id: owner for t, owner in shared}
    trips = [*own, *(t for t, _ in shared)]
    if not trips:
        raise NotFound("no trips yet")
    today = trip_cases.local_today(actor, now)
    if not name or not name.strip():
        picked = trip_cases.current_or_next(trips, today)
    else:
        matches = trip_cases.named(trips, name)
        if not matches:
            raise NotFound(
                f"no trip to {name.strip()}; trips: " + ", ".join(t.destination for t in trips)
            )
        if len(matches) > 1 and any(t.id in owners for t in matches):
            listed = "; ".join(_candidate(t, owners.get(t.id)) for t in matches)
            raise InvalidInput(
                f"{len(matches)} trips match {name.strip()!r}: {listed}. Ask which one."
            )
        picked = trip_cases.current_or_next(matches, today) or matches[0]
    if picked is None:  # pragma: no cover - there are trips
        raise NotFound("no trips yet")
    opened = await open_trip(uow(), actor, picked.id)
    return Found(picked, opened)


async def shared_trip_named_in(uow: UowFactory, actor: User, text: str) -> Found | None:
    """The one trip the actor was added to whose destination ("Tokyo", "Japan") the text
    mentions, for a screenshot sent with a caption like "add these to our Japan trip".
    None when none or several do, or when one of their own trips is mentioned too (a
    screenshot then goes where it always did, by its dates). Access is checked by
    ``open_trip``."""
    said = text.casefold()
    if not said.strip():
        return None
    shared = await shared_trips(uow(), actor.id)
    if not shared:
        return None

    def mentioned(trip: Trip) -> bool:
        parts = (p.strip().casefold() for p in trip.destination.split(","))
        return any(len(p) >= 3 and p in said for p in parts)

    if any(mentioned(t) for t in await trip_cases.list_trips(uow(), actor.id)):
        return None
    hits = [t for t, _ in shared if mentioned(t)]
    if len(hits) != 1:
        return None
    return Found(hits[0], await open_trip(uow(), actor, hits[0].id))


def describe_plan(plan: PlanView) -> list[str]:
    """A member's trip for chat: the plan only, with no money in it."""
    return [
        describe_trip(plan.trip, plan.today) + ".",
        *trip_cases.plan_lines(plan.trip, plan.bookings, plan.ready, plan.status),
    ]


# --- inviting people ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssuedTripInvite:
    token: str  # shown once; only its hash is kept
    invite: TripInvite


async def create_invite(
    uow: UnitOfWork, actor: User, trip_id: UUID, *, now: datetime
) -> IssuedTripInvite:
    """A single-use link that adds one person to the trip, valid for 7 days. A guest
    account may be made for someone with none only when the app's owner issues it."""
    async with uow:
        access = await uow.trips.trip_access(actor.id, trip_id)
        if access is None:
            raise NotFound("no trip with that id")
        if not access.is_owner:
            raise Forbidden(OWNER_ONLY)
        if await uow.trips.count_members(trip_id) >= MAX_MEMBERS:
            raise InvalidInput(f"a trip can have at most {MAX_MEMBERS} people on it besides you")
        if len(await uow.trips.list_open_trip_invites(actor.id, trip_id, now)) >= MAX_OPEN_INVITES:
            raise InvalidInput(f"keep at most {MAX_OPEN_INVITES} open invites; cancel one first")
        token = new_token()
        invite = TripInvite(
            uuid4(),
            token_hash(token),
            trip_id,
            actor.id,
            now,
            now + INVITE_TTL,
            may_create_guest=actor.role is Role.OWNER,
        )
        await uow.trips.insert_trip_invite(invite)
        await uow.commit()
    return IssuedTripInvite(token, invite)


async def open_invites(
    uow: UnitOfWork, actor: User, trip_id: UUID, *, now: datetime
) -> list[TripInvite]:
    """The trip's links that can still be used (owner only)."""
    async with uow:
        await _require_owner(uow, actor, trip_id)
        return await uow.trips.list_open_trip_invites(actor.id, trip_id, now)


async def revoke_invite(
    uow: UnitOfWork, actor: User, trip_id: UUID, invite_id: UUID, *, now: datetime
) -> None:
    async with uow:
        await _require_owner(uow, actor, trip_id)
        if not await uow.trips.revoke_trip_invite(actor.id, trip_id, invite_id, now):
            raise NotFound("no open invite with that id")
        await uow.commit()


async def _require_owner(uow: UnitOfWork, actor: User, trip_id: UUID) -> None:
    access = await uow.trips.trip_access(actor.id, trip_id)
    if access is None:
        raise NotFound("no trip with that id")
    if not access.is_owner:
        raise Forbidden(OWNER_ONLY)


@dataclass(frozen=True, slots=True)
class Joined:
    trip_id: UUID
    owner_id: UserId
    new: bool  # False when they were on the trip already
    own: bool = False  # True when the trip is theirs: the link was made by themselves


async def join_with_invite(
    uow: UnitOfWork, user: User, invite: TripInvite, *, now: datetime
) -> Joined | None:
    """Adds ``user`` to the invite's trip and spends the invite, inside the caller's
    unit of work (with the invite row locked). None when the invite can't be used.
    Someone already on the trip is left as they are and the invite is kept; so is
    the owner, who can't join their own trip: they get the trip back, marked ``own``,
    and the invite is neither spent nor checked."""
    trip_id, owner_id = invite.trip_id, invite.owner_id
    if owner_id == user.id:
        return Joined(trip_id, owner_id, False, own=True)
    already = await uow.trips.trip_access(user.id, trip_id) is not None
    if not invite.usable(now):
        # Opening the same link twice is harmless for the person it was spent on.
        if already and invite.redeemed_by == user.id:
            return Joined(trip_id, owner_id, False)
        return None
    if already:
        return Joined(trip_id, owner_id, False)
    if await uow.trips.count_members(trip_id) >= MAX_MEMBERS:
        raise InvalidInput(f"a trip can have at most {MAX_MEMBERS} people on it besides the owner")
    await uow.trips.add_member(owner_id, trip_id, user.id, invite.id, now)
    await uow.trips.redeem_trip_invite(invite.id, user.id, now)
    return Joined(trip_id, owner_id, True)


async def accept_invite(uow: UnitOfWork, user: User, token: str, *, now: datetime) -> Joined:
    """Joins the trip an invite link is for. NotFound, with one message, for a link that
    is unknown, used, cancelled or expired."""
    async with uow:
        invite = await uow.trips.get_trip_invite(token_hash(token), for_update=True)
        if invite is None:
            raise NotFound(NO_INVITE)
        joined = await join_with_invite(uow, user, invite, now=now)
        if joined is None:
            raise NotFound(NO_INVITE)
        await uow.commit()
    return joined


# --- who is on a trip ----------------------------------------------------------------------


async def list_members(uow: UnitOfWork, actor: User, trip_id: UUID) -> list[TripMember]:
    """The owner and the members; anyone on the trip may ask."""
    async with uow:
        access = await uow.trips.trip_access(actor.id, trip_id)
        if access is None:
            raise NotFound("no trip with that id")
        return await uow.trips.list_members(access.owner_id, trip_id)


async def remove_member(uow: UnitOfWork, actor: User, trip_id: UUID, member_id: UserId) -> None:
    """The owner takes someone off the trip, or a member leaves it. Their access ends
    at once; what they changed stays."""
    async with uow:
        access = await uow.trips.trip_access(actor.id, trip_id)
        if access is None:
            raise NotFound("no trip with that id")
        if not access.is_owner and member_id != actor.id:
            raise Forbidden(OWNER_ONLY)
        if not await uow.trips.remove_member(access.owner_id, trip_id, member_id):
            raise NotFound("no one on this trip with that id")
        await uow.commit()


# --- what people changed -------------------------------------------------------------------


async def record(uow: UnitOfWork, access: TripAccess, summary: str, *, now: datetime) -> None:
    """Notes an edit on a trip that has members, in a few words. Trips nobody shares
    keep no activity. A member's edit also queues the owner's Telegram summary for 30
    minutes on (every edit before it goes shares that one job). Never fails the edit it
    describes."""
    if access.trip_id is None:
        return
    try:
        async with uow:
            if await uow.trips.count_members(access.trip_id) == 0:
                return
            text = clean_summary(summary)
            if text:
                # Held so a summary being made right now either sees this edit or leaves
                # the next summary's key to it; never neither.
                state = await uow.trips.digest_state(access.trip_id, for_update=True)
                await uow.trips.add_activity(
                    access.owner_id, access.trip_id, access.actor_id, text, now
                )
                if state is not None and not access.is_owner:
                    await uow.jobs.enqueue(
                        DIGEST_JOB,
                        {"user_id": str(access.owner_id), "trip_id": str(access.trip_id)},
                        dedupe_key=digest_key(access.trip_id, state.last_at),
                        run_at=now + DIGEST_EVERY,
                    )
                await uow.commit()
    except Exception:
        log.warning("could not record trip activity", exc_info=True)


async def activity(uow: UnitOfWork, actor: User, trip_id: UUID) -> list[Activity]:
    """The latest changes, newest first."""
    async with uow:
        access = await uow.trips.trip_access(actor.id, trip_id)
        if access is None:
            raise NotFound("no trip with that id")
        return await uow.trips.list_activity(access.owner_id, trip_id, limit=ACTIVITY_SHOWN)


async def send_digest(
    uow: UowFactory, owner_id: UserId, trip_id: UUID, *, now: datetime, origin: str | None
) -> bool:
    """The job behind ``record``: tells the trip's owner on Telegram what other people
    changed since the last summary. True if a message was queued.

    Changes up to ``now`` count as told whether or not the owner hears of them (setting
    off, no Telegram chat), so turning the setting on never replays them. The whole
    thing is one transaction with the trip held, so a retry finds nothing left to say.
    A trip deleted meanwhile is nothing to do; someone removed meanwhile is still
    reported. Edits that landed after ``now`` queue the next summary.
    """
    async with uow() as tx:
        state = await tx.trips.digest_state(trip_id, for_update=True)
        if state is None or state.owner_id != owner_id:
            return False
        owner = await tx.ledger.get_user(owner_id)
        changes = await tx.trips.changes_by_others(
            owner_id, trip_id, after=state.last_at, until=now
        )
        await tx.trips.set_digest_at(trip_id, now)
        text = digest_text(state.destination, changes)
        sent = False
        if (
            text
            and owner is not None
            and owner.trip_activity_alerts
            and owner.telegram_chat_id is not None
        ):
            payload: dict[str, Any] = {"user_id": str(owner_id), "text": text}
            if origin:
                payload["buttons"] = [
                    [{"label": "Open the trip", "data": f"url:{origin}/travel/trips/{trip_id}"}]
                ]
            sent = await tx.jobs.enqueue(
                TELEGRAM_SEND,
                payload,
                dedupe_key=f"{digest_key(trip_id, state.last_at)}:send",
                run_at=now,
            )
        if await tx.trips.changes_by_others(owner_id, trip_id, after=now, until=None):
            await tx.jobs.enqueue(
                DIGEST_JOB,
                {"user_id": str(owner_id), "trip_id": str(trip_id)},
                dedupe_key=digest_key(trip_id, now),
                run_at=now + DIGEST_EVERY,
            )
        await tx.commit()
    return sent
