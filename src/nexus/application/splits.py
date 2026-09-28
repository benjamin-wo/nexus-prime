from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from nexus.application.clock import utcnow
from nexus.application.ports import UnitOfWork
from nexus.application.transactions import NewTransaction, create_transaction
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.ledger import (
    Direction,
    OpenIou,
    RevisionKind,
    Settlement,
    ShareRequest,
    Source,
    Split,
    Transaction,
    UserId,
    allocate_repayment,
    clean_name,
    plan_split,
    splits_snapshot,
)
from nexus.domain.money import Money


@dataclass(frozen=True, slots=True)
class SplitResult:
    transaction: Transaction
    splits: list[Split]
    own_share: Money


@dataclass(frozen=True, slots=True)
class SettlementResult:
    transaction: Transaction
    settlements: list[Settlement]
    # Paid beyond what was owed; kept as ordinary income, not an IOU.
    unallocated: Money


async def split_bill(
    uow: UnitOfWork,
    actor: UserId,
    transaction_id: UUID,
    participants: list[ShareRequest],
    *,
    include_self: bool = True,
) -> SplitResult:
    """Record who owes the user for a bill they paid. Replaces any earlier split
    of the same bill, as long as nobody has repaid against it yet."""
    async with uow:
        repo = uow.ledger
        tx = await repo.get_transaction(actor, transaction_id, for_update=True)
        if tx is None:
            raise NotFound("transaction not found")
        if tx.is_deleted:
            raise InvalidInput("this transaction is deleted; restore it first")
        if tx.direction is not Direction.OUT:
            raise InvalidInput("only money out can be split")
        if await repo.has_settlements(actor, tx.id):
            raise Conflict("repayments were already recorded against this bill's split")

        plan = plan_split(tx.amount, participants, include_self=include_self)
        previous = await repo.list_splits(actor, tx.id)
        splits = [Split(uuid4(), actor, tx.id, s.participant_name, s.share) for s in plan.shares]
        await repo.replace_splits(actor, tx.id, splits)
        await repo.insert_revision(
            actor, tx.id, RevisionKind.SPLIT, splits_snapshot(previous), utcnow()
        )
        await uow.commit()
    return SplitResult(tx, splits, plan.own_share)


async def list_open_ious(
    uow: UnitOfWork, actor: UserId, *, participant_name: str | None = None
) -> list[OpenIou]:
    name = None if participant_name is None else clean_name(participant_name, field_name="name")
    async with uow:
        return await uow.ledger.open_ious(actor, participant_name=name)


async def settle_iou(
    uow: UnitOfWork,
    actor: UserId,
    participant_name: str,
    amount: Money,
    occurred_at: datetime,
    *,
    notes: str | None = None,
    source: Source = Source.MANUAL,
    external_id: str | None = None,
) -> SettlementResult:
    """Record a friend's repayment as income and pay off their IOUs, oldest first."""
    name = clean_name(participant_name, field_name="name")
    async with uow:
        repo = uow.ledger
        ious = await repo.open_ious(actor, participant_name=name, for_update=True)
        matching = [iou for iou in ious if iou.outstanding.currency == amount.currency]
        if not matching:
            raise InvalidInput(f"{name} has no open IOU in {amount.currency}")

        plan = allocate_repayment(amount, matching)
        tx = await create_transaction(
            repo,
            actor,
            NewTransaction(
                direction=Direction.IN,
                amount=amount,
                occurred_at=occurred_at,
                counterparty=matching[0].split.participant_name,
                notes=notes,
                source=source,
                external_id=external_id,
            ),
            now=utcnow(),
        )
        settlements = [
            Settlement(uuid4(), actor, a.split_id, tx.id, a.amount) for a in plan.allocations
        ]
        await repo.insert_settlements(settlements)
        await uow.commit()
    return SettlementResult(tx, settlements, plan.unallocated)
