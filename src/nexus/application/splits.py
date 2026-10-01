from collections.abc import Callable
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
    same_person,
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
    """Who owes the user; with a name, that person's IOUs, the name matched as in
    ``owing_person``."""
    async with uow:
        everyone = await uow.ledger.open_ious(actor)
    if participant_name is None:
        return everyone
    person = owing_person(everyone, clean_name(participant_name, field_name="name"))
    return [iou for iou in everyone if iou.split.participant_name == person]


def owing_person(open_ious: list[OpenIou], name: str) -> str | None:
    """Who, among the people with open IOUs, ``name`` refers to: the exact name if
    someone has it, else the one person it plainly matches ("Wei Ming" for "TAN WEI
    MING"). None if nobody or more than one person matches."""
    people = {iou.split.participant_name for iou in open_ious}
    exact = [p for p in people if p.casefold() == name.strip().casefold()]
    if exact:
        return exact[0]
    loose = [p for p in people if same_person(p, name)]
    return loose[0] if len(loose) == 1 else None


async def mark_repaid(
    uow: Callable[[], UnitOfWork], actor: UserId, split_id: UUID, *, now: datetime
) -> SettlementResult:
    """One IOU paid back in full, today: its outstanding amount is recorded as money
    in from that person."""
    async with uow() as tx:
        ious = await tx.ledger.open_ious(actor)
    iou = next((i for i in ious if i.split.id == split_id), None)
    if iou is None:
        raise NotFound("that IOU isn't open")
    return await settle_iou(
        uow(),
        actor,
        iou.split.participant_name,
        iou.outstanding,
        now,
        notes="Paid back",
        split_id=split_id,
    )


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
    split_id: UUID | None = None,
) -> SettlementResult:
    """Record a friend's repayment as income and pay off their IOUs, oldest first.
    The name can be written as the bank writes it: see ``owing_person``."""
    name = clean_name(participant_name, field_name="name")
    async with uow:
        repo = uow.ledger
        everyone = await repo.open_ious(actor, for_update=True)
        person = owing_person(everyone, name) or name
        ious = [iou for iou in everyone if iou.split.participant_name == person]
        matching = [
            iou
            for iou in ious
            if iou.outstanding.currency == amount.currency
            and (split_id is None or iou.split.id == split_id)
        ]
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
