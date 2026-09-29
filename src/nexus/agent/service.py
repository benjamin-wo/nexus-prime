"""What channels call. Turns graph runs into replies with buttons."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from nexus.agent import kernel
from nexus.agent.graph import BUTTONS, RECEIPT, REF, WROTE, strip_ids, thread_id
from nexus.agent.receipts import ReceiptReader
from nexus.agent.tools import UowFactory
from nexus.application import bills as bill_cases
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.users import get_user
from nexus.domain.errors import DuplicateSource, NexusError
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.infra.llm.factory import text_of

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    data: str


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)


UNDO = Button("Undo", "act:undo")
MENU = [
    [Button("This month", "qa:summary"), Button("Who owes me", "qa:ious")],
    [Button("Undo last change", "act:undo"), Button("How to log", "qa:help")],
]
HELP = (
    "Just tell me what happened:\n"
    "• coffee 5.50\n"
    "• grab 12 yesterday\n"
    "• split dinner 90 with Ann and Ben\n"
    "• Ann paid me back 30\n"
    "• salary 4200\n"
    "Or send a photo of a receipt."
)


class AgentService:
    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        uow: UowFactory,
        receipts: ReceiptReader | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._graph = graph
        self._uow = uow
        self._receipts = receipts
        self._clock = clock
        # One turn at a time per user; a turn reads and writes the user's thread.
        self._locks: defaultdict[UserId, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _config(self, actor: UserId) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id(actor), "user_id": str(actor)}}

    async def _pending(self, actor: UserId) -> tuple[str, str] | None:
        """The waiting confirmation's (id, summary), if any."""
        snapshot = await self._graph.aget_state(self._config(actor))
        for pending in snapshot.interrupts:
            value = pending.value if isinstance(pending.value, dict) else {}
            return pending.id, str(value.get("summary", "Confirm?"))
        return None

    async def _run(self, actor: UserId, payload: Any) -> list[Reply]:
        config = self._config(actor)
        before = len((await self._graph.aget_state(config)).values.get("messages", []))
        await self._graph.ainvoke(payload, config)
        state = await self._graph.aget_state(config)
        new: list[BaseMessage] = state.values.get("messages", [])[before:]
        pending = await self._pending(actor)
        if pending is not None:
            pid, summary = pending
            buttons = [[Button("Confirm", f"hitl:{pid}:y"), Button("Cancel", f"hitl:{pid}:n")]]
            return [Reply(summary, buttons)]
        wrote = any(
            isinstance(m, AIMessage | ToolMessage) and m.additional_kwargs.get(WROTE) for m in new
        )
        final = next(
            (m for m in reversed(new) if isinstance(m, AIMessage) and not m.tool_calls), None
        )
        text = strip_ids(text_of(final.content)) if final else ""
        extra = [
            [Button(str(label), str(data)) for label, data in row]
            for row in (final.additional_kwargs.get(BUTTONS) or [] if final else [])
        ]
        return [Reply(text or "Done.", extra + ([[UNDO]] if wrote else []))]

    async def _decline_pending(self, actor: UserId) -> bool:
        if await self._pending(actor) is None:
            return False
        await self._graph.ainvoke(Command(resume={"approved": False}), self._config(actor))
        return True

    async def handle_text(self, actor: UserId, text: str, ref: str) -> list[Reply]:
        async with self._locks[actor]:
            # A new message instead of a button press means "no" to a waiting confirmation.
            declined = await self._decline_pending(actor)
            if declined and kernel.is_termination(text):
                return [Reply("Cancelled. Nothing was changed.")]
            message = HumanMessage(content=text, additional_kwargs={REF: ref})
            return await self._run(actor, {"messages": [message]})

    async def handle_photo(
        self, actor: UserId, image: bytes, mime_type: str, caption: str | None, ref: str
    ) -> list[Reply]:
        if self._receipts is None:
            return [Reply("Reading receipt photos isn't set up yet. Type the amount instead.")]
        try:
            draft = await self._receipts.read(image, mime_type, caption)
        except Exception:
            log.exception("receipt reading failed")
            return [Reply("I couldn't read that photo right now. Type the amount instead.")]
        async with self._locks[actor]:
            await self._decline_pending(actor)
            message = HumanMessage(
                content="[receipt photo]" + (f" {caption}" if caption else ""),
                additional_kwargs={RECEIPT: draft.model_dump(), REF: ref},
            )
            return await self._run(actor, {"messages": [message]})

    async def resolve(self, actor: UserId, confirmation_id: str, approved: bool) -> list[Reply]:
        async with self._locks[actor]:
            pending = await self._pending(actor)
            if pending is None or pending[0] != confirmation_id:
                return [Reply("That confirmation has expired. Nothing was changed.")]
            return await self._run(actor, Command(resume={"approved": approved}))

    async def press(self, actor: UserId, data: str) -> list[Reply]:
        """A button press from any channel: confirmations, Undo and quick actions."""
        if data.startswith("hitl:"):
            _, confirmation_id, choice = [*data.split(":"), "", ""][:3]
            return await self.resolve(actor, confirmation_id, choice == "y")
        if data == "act:undo":
            return await self.quick_action(actor, "undo")
        if data.startswith("qa:"):
            return await self.quick_action(actor, data.removeprefix("qa:"))
        if data.startswith("salary:"):
            return [await self._salary_button(actor, data.removeprefix("salary:"))]
        if data.startswith("bill:"):
            _, action, occurrence_id = [*data.split(":"), "", ""][:3]
            return [await self._bill_button(actor, action, occurrence_id)]
        return [Reply("I don't know that button.")]

    async def _salary_button(self, actor: UserId, data: str) -> Reply:
        """Payday check-in and usual-salary buttons. Each is the user's own answer."""
        action, _, rest = data.partition(":")
        user = await get_user(self._uow(), actor)
        now = self._clock()
        try:
            match action:
                case "log":
                    day = date.fromisoformat(rest)
                    tx = await salary_cases.log_payday_salary(self._uow, user, day, now=now)
                    return Reply(f"Logged {tx.amount} salary. Enjoy payday! 🎉", [[UNDO]])
                case "later":
                    return Reply("No problem. Tell me once it's in, like 'salary 5000'.")
                case "base":
                    amount, _, currency = rest.partition(":")
                    usual = Money.of(amount, currency)
                    await salary_cases.set_baseline(self._uow(), user, usual, now=now)
                    return Reply(f"Your usual salary is now {usual}.")
                case "keep":
                    return Reply("OK, I've kept your usual salary as it was.")
        except DuplicateSource:
            return Reply("Your salary for that payday is already logged.")
        except ValueError:
            pass
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        return Reply("I don't know that button.")

    async def _bill_button(self, actor: UserId, action: str, occurrence_id: str) -> Reply:
        """Mark paid / Snooze on a bill reminder. Records the user's word only; nothing
        is paid and the ledger isn't touched."""
        try:
            bill_id = await bill_cases.occurrence_bill(self._uow(), actor, UUID(occurrence_id))
        except ValueError:
            bill_id = None
        if bill_id is None:
            return Reply("That reminder is out of date: the bill is already paid or removed.")
        user = await get_user(self._uow(), actor)
        now = self._clock()
        try:
            if action == "paid":
                view = await bill_cases.mark_paid(self._uow, user, bill_id, now=now)
                return Reply(f"Marked {view.bill.name} ({view.due:%-d %b}) as paid.")
            if action == "snooze":
                view = await bill_cases.snooze(self._uow, user, bill_id, now=now)
                return Reply(f"OK, I'll remind you about {view.bill.name} again tomorrow.")
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        return Reply("I don't know that button.")

    async def quick_action(self, actor: UserId, action: str) -> list[Reply]:
        """Buttons that don't need the model."""
        match action:
            case "menu":
                return [Reply("What would you like to do?", MENU)]
            case "help":
                return [Reply(HELP)]
            case "undo":
                async with self._locks[actor]:
                    await self._decline_pending(actor)
                    try:
                        result = await tx_cases.undo_last(self._uow(), actor)
                    except NexusError as exc:
                        return [Reply(str(exc).capitalize() + ".")]
                tx = result.transaction
                what = f"{tx.amount} {tx.counterparty}" if tx.counterparty else str(tx.amount)
                return [Reply(f"Undone: the {result.undone.value} of {what}.")]
            case "ious":
                ious = await split_cases.list_open_ious(self._uow(), actor)
                if not ious:
                    return [Reply("Nobody owes you anything.")]
                return [
                    Reply("\n".join(f"{i.split.participant_name}: {i.outstanding}" for i in ious))
                ]
            case "summary":
                return [await self._month_summary(actor)]
        return [Reply("I don't know that action.")]

    async def _month_summary(self, actor: UserId) -> Reply:
        user = await get_user(self._uow(), actor)
        tz = ZoneInfo(user.timezone)
        today = self._clock().astimezone(tz).date()
        start = datetime.combine(today.replace(day=1), time(), tzinfo=tz)
        end = datetime.combine(today + timedelta(days=1), time(), tzinfo=tz)
        summary = await tx_cases.summarize(self._uow(), actor, start, end)
        if not summary.totals:
            return Reply("Nothing recorded this month yet.")
        lines = [f"{today:%B} so far:"]
        lines += [
            f"{'Spent' if t.direction.value == 'out' else 'Received'} {t.total}"
            for t in summary.totals
        ]
        lines += [
            f"  {c.category_name or 'Uncategorised'}: {c.total}"
            for c in summary.spending_by_category[:6]
        ]
        return Reply("\n".join(lines))
