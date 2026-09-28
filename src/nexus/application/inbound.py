"""Bookkeeping for inbound channel events and requests the app can't serve."""

from nexus.application.ports import UnitOfWork
from nexus.domain.ledger import UserId


async def claim_event(uow: UnitOfWork, channel: str, event_id: str) -> bool:
    """Record an inbound event. False means it was already handled: skip it."""
    async with uow:
        fresh = await uow.ledger.claim_inbound_event(channel, event_id)
        await uow.commit()
    return fresh


async def log_capability_gap(
    uow: UnitOfWork, actor: UserId, request: str, intent: str, channel: str
) -> None:
    async with uow:
        await uow.ledger.insert_capability_gap(actor, request, intent, channel)
        await uow.commit()
