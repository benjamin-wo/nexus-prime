"""Undo: reverses whichever of the user's last two kinds of change is newest, a ledger
write or a change to a trip's itinerary made from chat.

Repeated Undo walks further back, mixing both by time. An itinerary change is undone
with the rest of its batch (everything one chat message changed). An undo is not itself
undoable.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from nexus.application import mistakes
from nexus.application import transactions as tx_cases
from nexus.application.clock import utcnow
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import NothingToUndo
from nexus.domain.ledger import UserId
from nexus.domain.trip_changes import ChangeKind, TripChange, from_snapshot, title_of


@dataclass(frozen=True, slots=True)
class Reverted:
    """One itinerary change, undone or (with ``skipped``) not."""

    kind: ChangeKind
    title: str
    trip: str  # the trip's name, "" when it can't be reached any more
    skipped: str | None = None  # why it couldn't be undone, like "it was removed since"


@dataclass(frozen=True, slots=True)
class TripUndo:
    """An itinerary batch undone, newest change first."""

    items: list[Reverted]

    def message(self) -> str:
        """For the reply: "Undone: A and B off the Spain trip, C back on.", plus what
        couldn't be undone. Oldest change first, as the user made them."""
        oldest_first = list(reversed(self.items))
        done = [i for i in oldest_first if i.skipped is None]
        sentences: list[str] = []
        for trip in dict.fromkeys(i.trip for i in done):
            here = [i for i in done if i.trip == trip]
            parts: list[tuple[ChangeKind, str]] = []
            for kind, tail in (
                (ChangeKind.ADD, "off"),
                (ChangeKind.REMOVE, "back on"),
                (ChangeKind.CHANGE, "back as it was"),
            ):
                titles = [i.title for i in here if i.kind is kind]
                if titles:
                    parts.append((kind, f"{_and(titles)} {tail}"))
            where = f"the {trip} trip" if trip else "the trip"
            # The trip is named once, with the first part.
            first_kind, first = parts[0]
            parts[0] = (
                first_kind,
                f"{first} {'on ' if first_kind is ChangeKind.CHANGE else ''}{where}",
            )
            sentences.append(", ".join(text for _, text in parts))
        text = "Undone: " + "; ".join(sentences) + "." if sentences else "Nothing was undone."
        stuck = dict.fromkeys(f"{i.title} ({i.skipped})" for i in oldest_first if i.skipped)
        if stuck:
            text += " Couldn't undo " + "; ".join(stuck) + "."
        return text


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


async def undo_latest(uow: UnitOfWork, actor: UserId) -> tx_cases.UndoResult | TripUndo:
    """Reverses this user's newest change that hasn't been undone, whichever kind. At
    the same instant the itinerary change counts as the newer."""
    async with uow:
        revision = await uow.ledger.latest_open_revision(actor)
        change = await uow.trips.latest_open_change(actor)
        result: tx_cases.UndoResult | TripUndo
        if change is not None and (revision is None or change.created_at >= revision.created_at):
            result = await _undo_batch(uow, actor, change)
            changed_at = change.created_at
        elif revision is not None:
            result = await tx_cases.reverse_revision(uow, actor, revision)
            changed_at = revision.created_at
        else:
            raise NothingToUndo("there is nothing to undo")
        await uow.commit()
    _record(result, changed_at)
    return result


def _record(result: tx_cases.UndoResult | TripUndo, changed_at: datetime) -> None:
    """An Undo is a sign the change was wrong: which tool's, and how long after."""
    if isinstance(result, TripUndo):
        done = {mistakes.TRIP_TOOLS[i.kind] for i in result.items if i.skipped is None}
        if done:
            mistakes.undo(sorted(done), changed_at)
    else:
        tx = result.transaction
        mistakes.undo([mistakes.revision_tool(result.undone, tx.direction)], changed_at)


async def _undo_batch(uow: UnitOfWork, actor: UserId, newest: TripChange) -> TripUndo:
    batch = [newest] if newest.batch is None else await uow.trips.open_batch(actor, newest.batch)
    items = [await _revert(uow, actor, change) for change in batch]
    await uow.trips.mark_changes_undone(actor, [c.id for c in batch], utcnow())
    return TripUndo(items)


async def _revert(uow: UnitOfWork, actor: UserId, change: TripChange) -> Reverted:
    """Puts one entry back as it was. Run as the trip's owner, whose itinerary it is;
    skipped, with the reason, when that is no longer possible."""
    title = title_of(change)
    access = await uow.trips.trip_access(actor, change.trip_id)
    if access is None:
        return Reverted(change.kind, title, "", "you're no longer on that trip")
    owner = access.owner_id
    trip = await uow.trips.get_trip(owner, change.trip_id)
    where = trip.destination if trip else ""

    def skip(why: str) -> Reverted:
        return Reverted(change.kind, title, where, why)

    current = await uow.trips.get_booking(owner, change.booking_id)
    if change.kind is ChangeKind.ADD:
        if current is None:
            return skip("it was removed since")
        await uow.trips.delete_booking(owner, change.booking_id)
    elif change.kind is ChangeKind.REMOVE:
        if current is not None:
            return skip("it's back already")
        before = from_snapshot(change.before) if change.before else None
        if before is None:
            return skip("what it was is lost")
        before = replace(before, user_id=owner)
        if (
            before.transaction_id
            and await uow.ledger.get_transaction(owner, before.transaction_id) is None
        ):
            before = replace(before, transaction_id=None)
        if not await uow.trips.insert_booking(before):
            return skip("that email's booking is saved already")
    else:
        if current is None:
            return skip("it was removed since")
        before = from_snapshot(change.before) if change.before else None
        if before is None:
            return skip("what it was is lost")
        await uow.trips.update_booking(replace(current, draft=before.draft, cost=before.cost))
    return Reverted(change.kind, title, where)
