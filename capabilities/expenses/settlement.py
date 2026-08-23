from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict

from sqlmodel import select

from core.db import async_session_factory
from core.models import ExpenseTransaction, IncomeTransaction, TaskItem, UserProfile


@dataclass(frozen=True, slots=True)
class IouSettlementCommand:
    """A user-scoped request to record money received for one split participant."""

    expense_id: int
    user_id: int
    participant: str
    amount: float | None = None
    received_at: datetime | None = None
    notes: str | None = None


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _number(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _naive_utc(value: datetime | None) -> datetime:
    if value is None:
        return _utcnow_naive()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _participant_names_match(left: Any, right: Any) -> bool:
    """Match participant names across casing and an obvious one-letter typo."""
    left_value = "".join(ch for ch in str(left or "").casefold() if ch.isalnum())
    right_value = "".join(ch for ch in str(right or "").casefold() if ch.isalnum())
    if not left_value or not right_value:
        return False
    if left_value == right_value:
        return True
    return (
        len(left_value) >= 4
        and len(right_value) >= 4
        and SequenceMatcher(None, left_value, right_value).ratio() >= 0.86
    )


async def settle_iou(command: IouSettlementCommand) -> Dict[str, Any]:
    """Settle an IOU and synchronize its split, task, and repayment record."""
    participant = command.participant.strip().title()
    if not participant:
        return {"status": "invalid_participant"}

    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction).where(
                ExpenseTransaction.id == command.expense_id,
                ExpenseTransaction.user_id == command.user_id,
            )
        )
        expense = result.scalar_one_or_none()
        if expense is None:
            return {"status": "not_found", "expense_id": command.expense_id}

        split_data = dict(expense.split_data or {})
        share_amounts = dict(
            split_data.get("share_amounts")
            or split_data.get("custom_amounts")
            or {}
        )
        participant = next(
            (
                stored_name
                for stored_name in share_amounts
                if _participant_names_match(stored_name, participant)
            ),
            None,
        )
        if participant is None:
            return {
                "status": "invalid_participant",
                "expense_id": command.expense_id,
                "participant": command.participant.strip().title(),
            }

        amount_due = _number(share_amounts[participant])
        if amount_due <= 0:
            return {
                "status": "invalid_amount",
                "expense_id": command.expense_id,
                "participant": participant,
            }

        paid_status = dict(split_data.get("paid_status") or {})
        paid_amounts = dict(split_data.get("paid_amounts") or {})
        current_paid = min(amount_due, max(0.0, _number(paid_amounts.get(participant))))
        if paid_status.get(participant) is True or current_paid >= amount_due - 0.01:
            income_result = await session.execute(
                select(IncomeTransaction).where(
                    IncomeTransaction.source_message_id
                    == f"iou:{command.expense_id}:{participant.lower()}"
                )
            )
            existing_income = income_result.scalar_one_or_none()
            return {
                "status": "already_settled",
                "expense_id": command.expense_id,
                "participant": participant,
                "amount_due": amount_due,
                "amount_received": 0.0,
                "total_received": amount_due,
                "currency": expense.currency,
                "income_id": existing_income.id if existing_income else None,
            }

        requested_amount = command.amount
        amount_received = (
            round(amount_due - current_paid, 2)
            if requested_amount is None
            else round(requested_amount, 2)
        )
        remaining = round(amount_due - current_paid, 2)
        if amount_received <= 0 or amount_received > remaining + 0.01:
            return {
                "status": "invalid_amount",
                "expense_id": command.expense_id,
                "participant": participant,
                "amount_due": amount_due,
                "remaining": remaining,
            }

        total_received = round(min(amount_due, current_paid + amount_received), 2)
        is_settled = total_received >= amount_due - 0.01
        paid_amounts[participant] = total_received
        paid_status[participant] = is_settled
        split_data["paid_amounts"] = paid_amounts
        split_data["paid_status"] = paid_status
        history = list(split_data.get("settlement_history") or [])
        recorded_at = _naive_utc(command.received_at)
        history.append(
            {
                "participant": participant,
                "amount": amount_received,
                "total_received": total_received,
                "recorded_at": recorded_at.isoformat() + "Z",
            }
        )
        split_data["settlement_history"] = history
        expense.split_data = split_data
        session.add(expense)

        profile_result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == command.user_id)
        )
        if profile_result.scalar_one_or_none() is None:
            session.add(
                UserProfile(
                    user_id=command.user_id,
                    telegram_chat_id=command.user_id,
                    current_timezone="Asia/Singapore",
                )
            )

        income_key = f"iou:{command.expense_id}:{participant.lower()}"
        income_result = await session.execute(
            select(IncomeTransaction).where(
                IncomeTransaction.source_message_id == income_key
            )
        )
        income = income_result.scalar_one_or_none()
        if income is None:
            income = IncomeTransaction(
                user_id=command.user_id,
                amount=total_received,
                currency=expense.currency,
                source=participant,
                category="Friend Repayment",
                date=recorded_at,
                notes=command.notes or f"Repayment for {expense.merchant}",
                source_message_id=income_key,
                linked_expense_id=expense.id,
            )
        else:
            income.amount = total_received
            income.date = recorded_at
            income.linked_expense_id = expense.id
            if command.notes:
                income.notes = command.notes
        session.add(income)

        task_id = (split_data.get("task_ids") or {}).get(participant)
        task = None
        if task_id:
            task_result = await session.execute(
                select(TaskItem).where(
                    TaskItem.id == task_id,
                    TaskItem.user_id == command.user_id,
                )
            )
            task = task_result.scalar_one_or_none()
        if task is None:
            task_result = await session.execute(
                select(TaskItem).where(
                    TaskItem.user_id == command.user_id,
                    TaskItem.linked_expense_id == expense.id,
                    TaskItem.iou_friend == participant,
                )
            )
            task = task_result.scalars().first()
        if task is not None and is_settled:
            task.status = "done"
            task.completed_at = _utcnow_naive()
            task.is_reminder_active = False
            session.add(task)

        await session.commit()
        await session.refresh(income)
        return {
            "status": "settled" if is_settled else "partially_settled",
            "expense_id": command.expense_id,
            "participant": participant,
            "amount_due": amount_due,
            "amount_received": amount_received,
            "total_received": total_received,
            "currency": expense.currency,
            "income_id": income.id,
            "task_id": task.id if task else None,
        }


async def settle_matching_iou(
    user_id: int,
    participant: str,
    amount: float,
    received_at: datetime | None = None,
    notes: str | None = None,
) -> Dict[str, Any] | None:
    """Settle the unique open IOU matching a conversational repayment message."""
    normalized_participant = participant.strip().title()
    requested_amount = _number(amount)
    if not normalized_participant or requested_amount <= 0:
        return None

    async with async_session_factory() as session:
        result = await session.execute(
            select(TaskItem).where(
                TaskItem.user_id == user_id,
                TaskItem.linked_expense_id.is_not(None),
                TaskItem.status != "done",
            )
        )
        candidates = [
            task
            for task in result.scalars().all()
            if _participant_names_match(task.iou_friend, normalized_participant)
            and abs(_number(task.iou_amount) - requested_amount) <= 0.01
        ]

    if len(candidates) == 1:
        task = candidates[0]
        return await settle_iou(
            IouSettlementCommand(
                expense_id=task.linked_expense_id,
                user_id=user_id,
                participant=task.iou_friend,
                amount=requested_amount,
                received_at=received_at,
                notes=notes,
            )
        )
    # Do not guess if the same person has multiple indistinguishable open IOUs.
    if len(candidates) > 1:
        return None

    async with async_session_factory() as session:
        expenses = (await session.execute(
            select(ExpenseTransaction)
            .where(ExpenseTransaction.user_id == user_id)
            .order_by(ExpenseTransaction.date.desc())
            .limit(100)
        )).scalars().all()

    split_candidates: list[tuple[int, str]] = []
    for expense in expenses:
        split_data = dict(expense.split_data or {})
        share_amounts = dict(
            split_data.get("share_amounts")
            or split_data.get("custom_amounts")
            or {}
        )
        paid_status = dict(split_data.get("paid_status") or {})
        paid_amounts = dict(split_data.get("paid_amounts") or {})
        for stored_name, raw_due in share_amounts.items():
            if stored_name == "Me" or paid_status.get(stored_name) is True:
                continue
            amount_due = _number(raw_due)
            outstanding = max(0.0, amount_due - _number(paid_amounts.get(stored_name)))
            if (
                outstanding > 0.01
                and _participant_names_match(stored_name, normalized_participant)
                and requested_amount <= outstanding + 0.01
            ):
                split_candidates.append((expense.id, stored_name))

    # Do not guess when multiple web-created splits could match the message.
    if len(split_candidates) != 1:
        return None

    expense_id, stored_participant = split_candidates[0]
    return await settle_iou(
        IouSettlementCommand(
            expense_id=expense_id,
            user_id=user_id,
            participant=stored_participant,
            amount=requested_amount,
            received_at=received_at,
            notes=notes,
        )
    )
