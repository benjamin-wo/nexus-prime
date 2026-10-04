"""What channels call. Turns graph runs into replies with buttons."""

import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
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
from nexus.agent.holdings_reader import HoldingsReader, ScreenshotHoldings
from nexus.agent.receipts import ReceiptReader, caption_date
from nexus.agent.tools import UowFactory
from nexus.application import bills as bill_cases
from nexus.application import category_rules as rule_cases
from nexus.application import departments as department_cases
from nexus.application import email as email_cases
from nexus.application import investments as investment_cases
from nexus.application import receipts as receipt_cases
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application import transactions as tx_cases
from nexus.application.categories import list_categories
from nexus.application.fx import RateSource
from nexus.application.limits import RateLimiter
from nexus.application.ports import ReceiptStore
from nexus.application.users import get_user
from nexus.domain.departments import RunStatus
from nexus.domain.errors import DuplicateSource, InvalidInput, NexusError
from nexus.domain.investments import Position, clean_quantity, clean_symbol
from nexus.domain.ledger import Direction, Transaction, UserId
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


SLOW_DOWN = "That's a lot of messages at once. Give me a minute, then try again."
RECENT_MESSAGES = 3  # the newest, and two before it for context


class _NoRates:
    async def rate(self, base: str, quote: str, on: date) -> None:
        return None


# A caption that says the photo is a portfolio screenshot, not a receipt.
_PORTFOLIO = re.compile(r"\b(?:portfolio|holdings?|positions?|ibkr|interactive brokers)\b", re.I)
_NO_POSITIONS = Reply(
    "I couldn't find any positions in that screenshot. Send your broker's Portfolio "
    "screen, with the tickers, quantities and average costs showing."
)


def _positions(read: ScreenshotHoldings) -> list[Position]:
    """The positions a screenshot showed clearly; anything unreadable is left out."""
    found = []
    for p in read.positions:
        try:
            found.append(
                Position(
                    clean_symbol(p.symbol),
                    clean_quantity(p.quantity or ""),
                    Money.of(p.average_cost or "", (p.currency or "USD").upper()),
                )
            )
        except NexusError:
            continue
    return found


class AgentService:
    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        uow: UowFactory,
        receipts: ReceiptReader | None,
        clock: Callable[[], datetime],
        archive: ReceiptStore | None = None,
        rates: RateSource | None = None,
        after_turn: Callable[[UserId, list[str], str], Awaitable[None]] | None = None,
        limiter: RateLimiter | None = None,
        holdings: HoldingsReader | None = None,
    ) -> None:
        self._graph = graph
        # Reads broker portfolio screenshots; None: photos are only read as receipts.
        self._holdings = holdings
        # For figures in the home currency; None leaves foreign amounts out.
        self._rates = rates
        self._uow = uow
        self._receipts = receipts
        self._clock = clock
        # Where receipt photos are kept; None = they're read but not kept.
        self._archive = archive
        # Given the user's recent messages after each text turn (the memory writer's
        # job is queued from here); its failures never reach the user.
        self._after_turn = after_turn
        # Messages that reach the model, per user; None: no limit (tests, evals).
        self._limiter = limiter
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
        # By id, not position: a long conversation drops its oldest messages mid-turn.
        seen = {m.id for m in (await self._graph.aget_state(config)).values.get("messages", [])}
        await self._graph.ainvoke(payload, config)
        state = await self._graph.aget_state(config)
        new: list[BaseMessage] = [
            m for m in state.values.get("messages", []) if m.id is None or m.id not in seen
        ]
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
        # Buttons from this turn's tool results (e.g. a rule offer) and from the reply.
        sources = [m for m in new if isinstance(m, ToolMessage)] + ([final] if final else [])
        extra = [
            [Button(str(label), str(data)) for label, data in row]
            for m in sources
            for row in m.additional_kwargs.get(BUTTONS) or []
        ]
        return [Reply(text or "Done.", extra + ([[UNDO]] if wrote else []))]

    async def _decline_pending(self, actor: UserId) -> bool:
        if await self._pending(actor) is None:
            return False
        await self._graph.ainvoke(Command(resume={"approved": False}), self._config(actor))
        return True

    def _over_limit(self, actor: UserId) -> bool:
        return self._limiter is not None and not self._limiter.allow("message", actor)

    async def handle_text(self, actor: UserId, text: str, ref: str) -> list[Reply]:
        if self._over_limit(actor):
            return [Reply(SLOW_DOWN)]
        async with self._locks[actor]:
            # A new message instead of a button press means "no" to a waiting confirmation.
            declined = await self._decline_pending(actor)
            if declined and kernel.is_termination(text):
                return [Reply("Cancelled. Nothing was changed.")]
            message = HumanMessage(content=text, additional_kwargs={REF: ref})
            replies = await self._run(actor, {"messages": [message]})
            await self._remember(actor, ref)
            return replies

    async def _remember(self, actor: UserId, ref: str) -> None:
        """Hand the user's last few messages (their own words only) to ``after_turn``."""
        if self._after_turn is None:
            return
        try:
            state = await self._graph.aget_state(self._config(actor))
            said = [
                text_of(m.content)
                for m in state.values.get("messages", [])
                if isinstance(m, HumanMessage) and RECEIPT not in m.additional_kwargs
            ]
            await self._after_turn(actor, [t for t in said if t][-RECENT_MESSAGES:], ref)
        except Exception:
            log.exception("after-turn hook failed")

    async def handle_photo(
        self, actor: UserId, image: bytes, mime_type: str, caption: str | None, ref: str
    ) -> list[Reply]:
        receipts = self._receipts
        if receipts is None and self._holdings is None:
            return [Reply("Reading receipt photos isn't set up yet. Type the amount instead.")]
        if self._over_limit(actor):
            return [Reply(SLOW_DOWN)]
        if receipts is None or (self._holdings is not None and _PORTFOLIO.search(caption or "")):
            found = await self._holdings_photo(actor, image, mime_type, asked=True)
            return [found or _NO_POSITIONS]
        try:
            names = [c.name for c in await list_categories(self._uow(), actor)]
            user = await get_user(self._uow(), actor)
            today = self._clock().astimezone(ZoneInfo(user.timezone)).date()
            draft = await receipts.read(image, mime_type, caption, categories=names, today=today)
        except Exception:
            log.exception("receipt reading failed")
            return [Reply("I couldn't read that photo right now. Type the amount instead.")]
        if not draft.is_receipt and self._holdings is not None:
            # Not a receipt: it may be a portfolio screenshot sent without a caption.
            found = await self._holdings_photo(actor, image, mime_type, asked=False)
            if found is not None:
                return [found]
        details = draft.model_dump()
        if not details.get("date"):  # none printed: the caption may say ("from yesterday")
            details["date"] = caption_date(caption, today)
        if self._archive is not None and draft.is_receipt and draft.amount:
            try:
                stored = await receipt_cases.stash(
                    self._uow(), self._archive, actor, image, mime_type, now=self._clock()
                )
                details["receipt_id"] = str(stored.id)
            except Exception:
                # Keeping the photo is a bonus; the expense can still be logged without it.
                log.exception("could not store a receipt photo")
        async with self._locks[actor]:
            await self._decline_pending(actor)
            message = HumanMessage(
                content="[receipt photo]" + (f" {caption}" if caption else ""),
                additional_kwargs={RECEIPT: details, REF: ref},
            )
            return await self._run(actor, {"messages": [message]})

    async def _holdings_photo(
        self, actor: UserId, image: bytes, mime_type: str, *, asked: bool
    ) -> Reply | None:
        """A broker screenshot read into positions, kept as a draft for the user to
        save. None when the image isn't one (and the user didn't say it was)."""
        try:
            proposal = await self.read_portfolio(actor, image, mime_type, asked=asked)
        except InvalidInput as exc:
            # Unasked, a photo that couldn't be read as a portfolio goes on as a receipt.
            return Reply(str(exc)) if asked else None
        if proposal is None:
            return None
        text = investment_cases.describe_proposal(proposal)
        if proposal.first or proposal.changes:
            draft = proposal.draft.id
            return Reply(
                text,
                [[Button("Save", f"hold:save:{draft}"), Button("Cancel", f"hold:skip:{draft}")]],
            )
        await investment_cases.discard_draft(self._uow(), actor, proposal.draft.id)
        return Reply(text)

    @property
    def reads_portfolios(self) -> bool:
        return self._holdings is not None

    async def read_portfolio(
        self, actor: UserId, image: bytes, mime_type: str, *, asked: bool = True
    ) -> investment_cases.Proposal | None:
        """Read a broker screenshot into a draft for the user to save. None when it
        isn't one and the user didn't say it was; InvalidInput when nothing usable
        was found or it couldn't be read."""
        if self._holdings is None:
            raise InvalidInput("reading screenshots isn't set up yet")
        try:
            read = await self._holdings.read(image, mime_type)
        except Exception as exc:
            log.exception("portfolio screenshot reading failed")
            raise InvalidInput(
                "I couldn't read that screenshot right now. Try again in a bit."
            ) from exc
        if not read.is_portfolio and not asked:
            return None
        positions = _positions(read)
        if not positions:
            raise InvalidInput(_NO_POSITIONS.text)
        return await investment_cases.propose(self._uow(), actor, positions, now=self._clock())

    async def _holdings_button(self, actor: UserId, action: str, draft_id: str) -> Reply:
        """Save / Cancel on positions read from a screenshot."""
        try:
            found = UUID(draft_id)
        except ValueError:
            return Reply("I don't know that button.")
        try:
            if action == "save":
                saved = await investment_cases.save_draft(
                    self._uow(), actor, found, now=self._clock()
                )
                return Reply(
                    f"Saved {len(saved)} positions. They're on the Investment page in the web app."
                )
            if action == "skip":
                await investment_cases.discard_draft(self._uow(), actor, found)
                return Reply("OK, I've left your holdings as they were.")
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        return Reply("I don't know that button.")

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
        if data.startswith("email:"):
            _, action, email_id = [*data.split(":"), "", ""][:3]
            return [await self._email_button(actor, action, email_id)]
        if data.startswith("rule:"):
            return [await self._rule_button(actor, data.removeprefix("rule:"))]
        if data.startswith("bill:"):
            _, action, occurrence_id = [*data.split(":"), "", ""][:3]
            return [await self._bill_button(actor, action, occurrence_id)]
        if data.startswith("sub:"):
            _, action, subscription_id = [*data.split(":"), "", ""][:3]
            return [await self._subscription_button(actor, action, subscription_id)]
        if data.startswith("hold:"):
            _, action, draft_id = [*data.split(":"), "", ""][:3]
            return [await self._holdings_button(actor, action, draft_id)]
        if data.startswith("run:cancel:"):
            return [await self._cancel_run(actor, data.removeprefix("run:cancel:"))]
        return [Reply("I don't know that button.")]

    async def _cancel_run(self, actor: UserId, run_id: str) -> Reply:
        """Cancel on a department job's progress message."""
        try:
            found = UUID(run_id)
        except ValueError:
            return Reply("I don't know that button.")
        try:
            before = await department_cases.get_run(self._uow(), actor, found)
            if before.finished:
                ended = "been cancelled" if before.status is RunStatus.CANCELLED else "finished"
                return Reply(f"{before.title} has already {ended}.")
            run = await department_cases.cancel_run(self._uow(), actor, found, now=self._clock())
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        if run.status is not RunStatus.CANCELLED:  # pragma: no cover - finished in between
            return Reply(f"{run.title} has already finished.")
        return Reply(f"⏹ Cancelled {run.title}. Nothing more will run.")

    async def _subscription_button(self, actor: UserId, action: str, subscription_id: str) -> Reply:
        """Track it / No on a proposed subscription."""
        try:
            found = UUID(subscription_id)
        except ValueError:
            return Reply("I don't know that button.")
        now = self._clock()
        try:
            if action == "track":
                tracked = await subscription_cases.track(self._uow(), actor, found, now=now)
                return Reply(
                    f"Tracking {tracked.name}. I'll tell you if the price changes. "
                    "Your subscriptions are on the Plan page."
                )
            if action == "skip":
                await subscription_cases.dismiss(self._uow(), actor, found, now=now)
                return Reply("OK, I won't ask about that one again.")
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        return Reply("I don't know that button.")

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

    async def _email_button(self, actor: UserId, action: str, email_id: str) -> Reply:
        """Log it / Skip on a receipt found in the user's email; for money received,
        also Yes, paid back / Just income; for one that looks like a payment already
        recorded, Same one / It's another."""
        try:
            found = UUID(email_id)
        except ValueError:
            return Reply("I don't know that button.")
        user = await get_user(self._uow(), actor)
        repayment = {"log": None, "repay": True, "income": False}
        try:
            if action in repayment:
                tx = await email_cases.log_email(
                    self._uow, user, found, now=self._clock(), repayment=repayment[action]
                )
                if tx.direction is Direction.IN:
                    return Reply(await self._money_in(actor, tx), [[UNDO]])
                where = f" at {tx.counterparty}" if tx.counterparty else ""
                return Reply(f"Logged {tx.amount}{where}.", [[UNDO]])
            if action == "skip":
                await email_cases.skip_email(self._uow(), actor, found)
                return Reply("Skipped. Nothing was logged.")
            if action == "same":
                kept = await email_cases.same_payment(self._uow, user, found, now=self._clock())
                if kept is None:
                    return Reply(
                        "Got it, one payment. Answer the other email to log it, and only once."
                    )
                where = f" as {kept.counterparty}" if kept.counterparty else ""
                return Reply(f"Got it, one payment: kept {kept.amount}{where}. Nothing added.")
        except DuplicateSource:
            return Reply("That email was already logged.")
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        return Reply("I don't know that button.")

    async def _money_in(self, actor: UserId, tx: Transaction) -> str:
        """What logging money received did: a repayment says who still owes what."""
        who = tx.counterparty
        if who is None:
            return f"Logged {tx.amount} received."
        async with self._uow() as uow:
            settled = await uow.ledger.has_settlements_for_income(actor, tx.id)
        if not settled:
            return f"Logged {tx.amount} received from {who}."
        left = await split_cases.list_open_ious(self._uow(), actor, participant_name=who)
        owed = ", ".join(str(i.outstanding) for i in left)
        status = f"{who} still owes {owed}." if left else f"{who} is all settled. 🎉"
        return f"Recorded {tx.amount} from {who} as paid back. {status}"

    async def _rule_button(self, actor: UserId, data: str) -> Reply:
        """The answer to a rule offer after a category correction."""
        action, _, transaction_id = data.partition(":")
        if action == "skip":
            return Reply("OK, just this once. Your rules are unchanged.")
        if action != "save":
            return Reply("I don't know that button.")
        try:
            tx_id = UUID(transaction_id)
        except ValueError:
            return Reply("I don't know that button.")
        user = await get_user(self._uow(), actor)
        try:
            change = await rule_cases.accept_suggestion(self._uow(), user, tx_id, now=self._clock())
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        pattern, name = change.rule.pattern, change.category.name
        if not change.changed:
            return Reply(f"Your rule already files “{pattern}” under {name}.")
        if change.previous:
            return Reply(
                f"Changed: “{pattern}” now files under {name} instead of {change.previous.name}."
            )
        return Reply(f"Saved: new expenses from “{pattern}” will go under {name}.")

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
        rates = self._rates if self._rates is not None else _NoRates()
        summary = await tx_cases.summarize_in_home(self._uow(), rates, user, start, end)
        if not any(t.count or t.unconverted for t in summary.totals):
            return Reply("Nothing recorded this month yet.")
        lines = [f"{today:%B} so far:"]
        for t in summary.totals:
            if not t.count and not t.unconverted:
                continue
            line = f"{'Spent' if t.direction.value == 'out' else 'Received'} {t.total}"
            if t.unconverted:
                line += " (plus " + ", ".join(str(m) for m in t.unconverted) + " not converted)"
            lines.append(line)
        lines += [
            f"  {c.category_name or 'Uncategorised'}: {c.total}"
            for c in summary.spending_by_category[:6]
        ]
        return Reply("\n".join(lines))
