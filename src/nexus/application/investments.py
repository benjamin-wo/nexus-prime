"""Holdings: read from a broker screenshot (and saved only once the user says so),
or changed one trade at a time. Research only: nothing here trades."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from nexus.application.ports import UnitOfWork
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.investments import (
    DraftStatus,
    Holding,
    HoldingsDraft,
    Position,
    buy,
    changes,
    describe_position,
    merge_positions,
    sell,
)
from nexus.domain.ledger import UserId
from nexus.domain.money import Money

type UowFactory = Callable[[], UnitOfWork]


async def portfolio(uow: UnitOfWork, user_id: UserId) -> list[Holding]:
    async with uow:
        return await uow.investments.list_holdings(user_id)


@dataclass(frozen=True, slots=True)
class Proposal:
    draft: HoldingsDraft
    changes: list[str]  # what saving it would change; empty if nothing would
    first: bool  # no holdings yet: this would be the whole portfolio


async def propose(
    uow: UnitOfWork, user_id: UserId, positions: Sequence[Position], *, now: datetime
) -> Proposal:
    """Keep positions read from a screenshot as a draft for the user to check. An
    older draft still waiting is dropped: the newest screenshot wins."""
    merged = merge_positions(list(positions))
    if not merged:
        raise InvalidInput("no positions were found in that screenshot")
    async with uow:
        held = [h.position for h in await uow.investments.list_holdings(user_id)]
        older = await uow.investments.latest_waiting_draft(user_id)
        if older is not None:
            await uow.investments.set_draft_status(user_id, older.id, DraftStatus.DISCARDED)
        draft = HoldingsDraft(uuid4(), user_id, merged, DraftStatus.WAITING, now)
        await uow.investments.insert_draft(draft)
        await uow.commit()
    return Proposal(draft, changes(held, merged), first=not held)


def describe_proposal(proposal: Proposal) -> str:
    """The question about a screenshot, for Telegram and the chat."""
    positions = proposal.draft.positions
    if proposal.first:
        lines = [f"📈 I read {len(positions)} positions from your screenshot:"]
        lines += [f"• {describe_position(p)}" for p in positions]
        lines.append("Save these as your holdings?")
    elif proposal.changes:
        lines = ["📈 Compared with what I have, your screenshot shows:"]
        lines += [f"• {line}" for line in proposal.changes]
        lines.append("Update your holdings to match?")
    else:
        lines = ["📈 Your screenshot matches the holdings I already have. Nothing to change."]
    return "\n".join(lines)


async def _waiting(uow: UnitOfWork, user_id: UserId, draft_id: UUID) -> HoldingsDraft:
    draft = await uow.investments.get_draft(user_id, draft_id, for_update=True)
    if draft is None:
        raise NotFound("that screenshot isn't waiting any more")
    if draft.status is not DraftStatus.WAITING:
        raise Conflict(f"that screenshot was already {draft.status.value}")
    return draft


async def save_draft(
    uow: UnitOfWork, user_id: UserId, draft_id: UUID, *, now: datetime
) -> list[Position]:
    """The user said yes: the screenshot is the whole portfolio now. Stocks it
    doesn't list are removed."""
    async with uow:
        draft = await _waiting(uow, user_id, draft_id)
        keep = {p.symbol for p in draft.positions}
        for held in await uow.investments.list_holdings(user_id):
            if held.position.symbol not in keep:
                await uow.investments.remove_position(user_id, held.position.symbol)
        for position in draft.positions:
            await uow.investments.save_position(user_id, position, now)
        await uow.investments.set_draft_status(user_id, draft_id, DraftStatus.SAVED)
        await uow.commit()
    return draft.positions


async def discard_draft(uow: UnitOfWork, user_id: UserId, draft_id: UUID) -> None:
    async with uow:
        await _waiting(uow, user_id, draft_id)
        await uow.investments.set_draft_status(user_id, draft_id, DraftStatus.DISCARDED)
        await uow.commit()


async def waiting_draft(uow: UnitOfWork, user_id: UserId) -> HoldingsDraft | None:
    async with uow:
        return await uow.investments.latest_waiting_draft(user_id)


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


async def record_trade(
    uow: UnitOfWork,
    user_id: UserId,
    side: Side,
    symbol: str,
    quantity: Decimal,
    price: Money | None,
    *,
    now: datetime,
) -> Position | None:
    """A trade the user made (at their broker): the position after it, or None
    when it's all sold. A purchase needs the price paid."""
    async with uow:
        held = {h.position.symbol: h.position for h in await uow.investments.list_holdings(user_id)}
        if side is Side.BUY:
            if price is None:
                raise InvalidInput(f"what price did you pay for the {symbol}?")
            after: Position | None = buy(held.get(symbol), symbol, quantity, price)
        else:
            after = sell(held.get(symbol), symbol, quantity)
        if after is None:
            await uow.investments.remove_position(user_id, symbol)
        else:
            await uow.investments.save_position(user_id, after, now)
        await uow.commit()
    return after


async def set_position(
    uow: UnitOfWork, user_id: UserId, position: Position, *, now: datetime
) -> None:
    """Set a position outright, as the web app's edit does."""
    async with uow:
        await uow.investments.save_position(user_id, position, now)
        await uow.commit()


async def remove(uow: UnitOfWork, user_id: UserId, symbol: str) -> None:
    async with uow:
        if not await uow.investments.remove_position(user_id, symbol):
            raise NotFound(f"you don't hold any {symbol}")
        await uow.commit()
