"""What channels call. Turns graph runs into replies with buttons."""

import asyncio
import logging
import time as clock
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
from nexus.agent.graph import BUTTONS, IMAGE, RECEIPT, REF, WROTE, strip_ids, thread_id
from nexus.agent.holdings_reader import HoldingsReader, ScreenshotHoldings
from nexus.agent.image_look import (
    MAX_TEXT,
    PORTFOLIO_WORDS,
    TRAVEL_WORDS,
    ImageKind,
    ImageLook,
    ImageLooker,
    Route,
    route,
)
from nexus.agent.receipts import ReceiptReader, caption_date
from nexus.agent.tools import UowFactory
from nexus.agent.trip_reader import TripReader, drafts
from nexus.application import bills as bill_cases
from nexus.application import bookings as booking_cases
from nexus.application import category_rules as rule_cases
from nexus.application import departments as department_cases
from nexus.application import email as email_cases
from nexus.application import investments as investment_cases
from nexus.application import plans as plan_cases
from nexus.application import receipts as receipt_cases
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application import transactions as tx_cases
from nexus.application import travel_research as research_cases
from nexus.application.categories import list_categories
from nexus.application.fx import RateSource
from nexus.application.limits import RateLimiter
from nexus.application.ports import ReceiptStore
from nexus.application.users import get_user
from nexus.domain.chat import CHAT_KEEP, ChatLine, Speaker, channel_of, clip
from nexus.domain.departments import RunStatus
from nexus.domain.errors import DuplicateSource, InvalidInput, NexusError
from nexus.domain.investments import Position, clean_quantity, clean_symbol
from nexus.domain.ledger import Direction, Transaction, UserId
from nexus.domain.money import Money
from nexus.domain.places import quoted
from nexus.infra.llm.factory import text_of
from nexus.infra.pdf.text import PasswordNeeded, pdf_lines

log = logging.getLogger(__name__)
# A turn slower than this is logged as a warning, with what it did (never what was said).
SLOW_TURN_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    data: str


@dataclass(frozen=True, slots=True)
class Picture:
    """An image the user sent: its bytes, type, and a reference unique to it (a
    resent photo has the same one, so its receipt isn't logged twice)."""

    data: bytes
    mime_type: str
    ref: str


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
    "Or send a photo: a receipt to log, or any screenshot or bill to ask me about."
)


SLOW_DOWN = "That's a lot of messages at once. Give me a minute, then try again."
RECENT_MESSAGES = 3  # the newest, and two before it for context


def _log_turn(seconds: float, new: list[BaseMessage]) -> None:
    """How long a turn took, how many model calls it made and which tools it used:
    enough to see what makes a reply slow, without anything the user said."""
    replies = [m for m in new if isinstance(m, AIMessage)]
    tools = [call["name"] for m in replies for call in m.tool_calls]
    log.log(
        logging.WARNING if seconds >= SLOW_TURN_SECONDS else logging.INFO,
        "turn took %.1fs: %d model calls, tools: %s",
        seconds,
        len(replies),
        ", ".join(tools) or "none",
    )


class _NoRates:
    async def rate(self, base: str, quote: str, on: date) -> None:
        return None


_NO_ENTRIES = Reply(
    "I couldn't find any bookings or plans with dates in that screenshot. Try a clearer "
    "one, or tell me the details."
)
# Which-trip questions sent for one screenshot; the rest wait on the Trips page.
ASK_AT_MOST = 3
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
        trips: TripReader | None = None,
        looker: ImageLooker | None = None,
    ) -> None:
        self._graph = graph
        # The first look at every image; None: images are read as receipts first.
        self._looker = looker
        # Reads screenshots of travel bookings and plans; None: they're read as receipts.
        self._trips = trips
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
        started = clock.monotonic()
        await self._graph.ainvoke(payload, config)
        state = await self._graph.aget_state(config)
        new: list[BaseMessage] = [
            m for m in state.values.get("messages", []) if m.id is None or m.id not in seen
        ]
        _log_turn(clock.monotonic() - started, new)
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

    async def _keep(
        self, actor: UserId, said: str | None, replies: list[Reply], ref: str | None
    ) -> None:
        """Keep this turn of the chat (the user's words and Nexus's replies) for the
        web chat to show again. Its failures never reach the user."""
        try:
            now = self._clock()
            channel = channel_of(ref) if ref else None
            lines = [ChatLine(actor, Speaker.USER, clip(said), channel, now)] if said else []
            lines += [
                ChatLine(actor, Speaker.NEXUS, clip(r.text), channel, now)
                for r in replies
                if r.text.strip()
            ]
            async with self._uow() as tx:
                await tx.memory.add_chat(lines, CHAT_KEEP)
                await tx.commit()
        except Exception:
            log.exception("could not keep the chat")

    async def chat_pending(self, actor: UserId) -> Reply | None:
        """The confirmation waiting for an answer, with its buttons, if any."""
        pending = await self._pending(actor)
        if pending is None:
            return None
        pid, summary = pending
        buttons = [[Button("Confirm", f"hitl:{pid}:y"), Button("Cancel", f"hitl:{pid}:n")]]
        return Reply(summary, buttons)

    async def handle_text(self, actor: UserId, text: str, ref: str) -> list[Reply]:
        replies = await self._handle_text(actor, text, ref)
        await self._keep(actor, text, replies, ref)
        return replies

    async def _handle_text(self, actor: UserId, text: str, ref: str) -> list[Reply]:
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
                # Text read from an image is data, not the user's words: only the caption.
                str(m.additional_kwargs[IMAGE])
                if IMAGE in m.additional_kwargs
                else text_of(m.content)
                for m in state.values.get("messages", [])
                if isinstance(m, HumanMessage) and RECEIPT not in m.additional_kwargs
            ]
            await self._after_turn(actor, [t for t in said if t][-RECENT_MESSAGES:], ref)
        except Exception:
            log.exception("after-turn hook failed")

    async def handle_photo(
        self, actor: UserId, image: bytes, mime_type: str, caption: str | None, ref: str
    ) -> list[Reply]:
        return await self.handle_images(actor, [Picture(image, mime_type, ref)], caption, ref)

    async def handle_images(
        self, actor: UserId, pictures: list[Picture], caption: str | None, ref: str
    ) -> list[Reply]:
        replies = await self._handle_images(actor, pictures, caption, ref)
        what = "a photo" if len(pictures) == 1 else f"{len(pictures)} photos"
        await self._keep(actor, f"[Sent {what}]{f' {caption}' if caption else ''}", replies, ref)
        return replies

    async def _handle_images(
        self, actor: UserId, pictures: list[Picture], caption: str | None, ref: str
    ) -> list[Reply]:
        """Photos or image files the user sent together, with their caption. Each is
        looked at first (what it is, and its text), then code routes it: receipts are
        logged, portfolio and trip screenshots read, and anything else (or a question
        about it) answered by the chat agent from what was read."""
        if (
            self._looker is None
            and self._receipts is None
            and self._holdings is None
            and self._trips is None
        ):
            return [Reply("Reading photos isn't set up yet. Tell me what it says instead.")]
        if self._over_limit(actor):
            return [Reply(SLOW_DOWN)]
        looks = await asyncio.gather(*(self._look(p, caption) for p in pictures))
        replies: list[Reply] = []
        to_chat: list[ImageLook] = []
        unread = 0
        for picture, look in zip(pictures, looks, strict=True):
            done = await self._read_as(actor, route(look, caption), picture, look, caption)
            if done is not None:
                replies += done
            elif look is not None:
                to_chat.append(look)
            else:
                unread += 1
        if to_chat:
            replies += await self.ask_about(actor, to_chat, caption, ref)
        elif unread and not replies:
            replies.append(Reply("I couldn't read that right now. Try again in a bit."))
        return replies

    async def _look(self, picture: Picture, caption: str | None) -> ImageLook | None:
        if self._looker is None:
            return None
        try:
            return await self._looker.look(picture.data, picture.mime_type, caption)
        except Exception:
            log.warning("couldn't look at an image", exc_info=True)
            return None

    async def _read_as(
        self,
        actor: UserId,
        where: Route,
        picture: Picture,
        look: ImageLook | None,
        caption: str | None,
    ) -> list[Reply] | None:
        """The structured read for this route; None when it goes to the chat agent
        instead (a question, another kind, or a reader that found nothing)."""
        said = caption or ""
        if where is Route.TRAVEL and self._trips is not None:
            asked = bool(TRAVEL_WORDS.search(said))
            found = await self._trip_photo(
                actor, picture.data, picture.mime_type, caption, asked=asked
            )
            return found if found is not None or look is not None else [_NO_ENTRIES]
        if where is Route.PORTFOLIO and self._holdings is not None:
            asked = bool(PORTFOLIO_WORDS.search(said))
            holding = await self._holdings_photo(
                actor, picture.data, picture.mime_type, asked=asked
            )
            if holding is not None:
                return [holding]
            return None if look is not None else [_NO_POSITIONS]
        if where is Route.RECEIPT and self._receipts is not None:
            return await self._receipt_photo(actor, picture, look, caption)
        return None

    async def handle_pdf(
        self, actor: UserId, data: bytes, name: str, caption: str | None, ref: str
    ) -> list[Reply]:
        replies = await self._handle_pdf(actor, data, name, caption, ref)
        said = f"[Sent {quoted(name, 80) or 'a PDF'}]{f' {caption}' if caption else ''}"
        await self._keep(actor, said, replies, ref)
        return replies

    async def _handle_pdf(
        self, actor: UserId, data: bytes, name: str, caption: str | None, ref: str
    ) -> list[Reply]:
        """A PDF the user sent (an invoice, a payslip, a booking): its text goes to the
        chat agent as quoted data. Statements are imported on the web instead."""
        if self._over_limit(actor):
            return [Reply(SLOW_DOWN)]
        try:
            lines = await asyncio.to_thread(pdf_lines, data)
        except PasswordNeeded:
            return [
                Reply(
                    "That PDF is locked. For a bank statement, use Import in the web app, "
                    "which asks for the password; otherwise send a screenshot."
                )
            ]
        except InvalidInput as exc:
            return [Reply(f"{str(exc).capitalize()}. Send a screenshot of it instead.")]
        text = quoted(" / ".join(lines), MAX_TEXT)
        if not text:
            return [Reply("There's no text in that PDF (it may be scanned). Send a photo of it.")]
        look = ImageLook(ImageKind.OTHER, None, f"A PDF file named {quoted(name, 80)}", text)
        return await self.ask_about(actor, [look], caption, ref, label="[PDF]")

    async def ask_about(
        self,
        actor: UserId,
        looks: list[ImageLook],
        caption: str | None,
        ref: str,
        *,
        label: str | None = None,
    ) -> list[Reply]:
        """The chat agent answers about images from what was read, quoted as data."""
        many = len(looks) > 1
        quotes = "\n".join(look.quote(n if many else None) for n, look in enumerate(looks, 1))
        label = label or (f"[{len(looks)} photos]" if many else "[photo]")
        content = f"{label}{f' {caption}' if caption else ''}\n{quotes}"
        async with self._locks[actor]:
            await self._decline_pending(actor)
            message = HumanMessage(
                content=content, additional_kwargs={REF: ref, IMAGE: caption or ""}
            )
            replies = await self._run(actor, {"messages": [message]})
        await self._remember(actor, ref)
        return replies

    async def _receipt_photo(
        self, actor: UserId, picture: Picture, look: ImageLook | None, caption: str | None
    ) -> list[Reply] | None:
        receipts = self._receipts
        if receipts is None:  # pragma: no cover - routed only when set up
            return None
        image, mime_type = picture.data, picture.mime_type
        try:
            names = [c.name for c in await list_categories(self._uow(), actor)]
            user = await get_user(self._uow(), actor)
            today = self._clock().astimezone(ZoneInfo(user.timezone)).date()
            draft = await receipts.read(image, mime_type, caption, categories=names, today=today)
        except Exception:
            log.exception("receipt reading failed")
            if look is not None:
                return None  # the chat agent still has what was read
            return [Reply("I couldn't read that photo right now. Type the amount instead.")]
        if draft.is_travel and self._trips is not None:
            # A ticket or booking with a price on it: its entries go on the trip.
            entries = await self._trip_photo(actor, image, mime_type, caption, asked=False)
            if entries is not None:
                return entries
        if look is None:
            # No first look: the receipt reader's hint decides, as before.
            if not draft.is_receipt and self._holdings is not None:
                found = await self._holdings_photo(actor, image, mime_type, asked=False)
                if found is not None:
                    return [found]
        elif not draft.is_receipt or not draft.amount:
            return None  # not a receipt after all: the chat agent answers from the look
        details = draft.model_dump()
        if look is not None and look.currency:
            if not details.get("currency"):
                details["currency"] = look.currency
            elif str(details["currency"]).upper() != look.currency:
                details["seen_currency"] = look.currency
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
                additional_kwargs={RECEIPT: details, REF: picture.ref},
            )
            return await self._run(actor, {"messages": [message]})

    async def _trip_photo(
        self, actor: UserId, image: bytes, mime_type: str, caption: str | None, *, asked: bool
    ) -> list[Reply] | None:
        """A screenshot of bookings or plans put on the user's trips. None when it
        isn't one and the user didn't say it was."""
        try:
            result = await self.read_trip_screenshot(actor, image, mime_type, caption, asked=asked)
        except InvalidInput as exc:
            return [Reply(str(exc))] if asked else None
        if result is None:
            return None
        replies = [Reply(booking_cases.describe_screenshot(result))]
        asks = [s for s in result.saved if s.trip is None and s.ask]
        for saved in asks[:ASK_AT_MOST]:
            text, rows = booking_cases.which_trip(saved)
            replies.append(
                Reply(text, [[Button(b["label"], b["data"]) for b in row] for row in rows])
            )
        if len(asks) > ASK_AT_MOST:
            replies.append(Reply("The rest are on the Trips page, under Not on a trip yet."))
        return [r for r in replies if r.text]

    @property
    def reads_trip_screenshots(self) -> bool:
        return self._trips is not None

    async def read_trip_screenshot(
        self,
        actor: UserId,
        image: bytes,
        mime_type: str,
        caption: str | None = None,
        *,
        trip_id: UUID | None = None,
        asked: bool = True,
    ) -> booking_cases.FromScreenshot | None:
        """Read a screenshot of bookings or plans onto the user's trips (or onto
        ``trip_id``). None when it isn't one and the user didn't say it was;
        InvalidInput when nothing usable was found or it couldn't be read."""
        if self._trips is None:
            raise InvalidInput("reading screenshots isn't set up yet")
        user = await get_user(self._uow(), actor)
        now = self._clock()
        try:
            shot = await self._trips.read(
                image, mime_type, caption, today=now.astimezone(ZoneInfo(user.timezone)).date()
            )
        except Exception as exc:
            log.exception("trip screenshot reading failed")
            raise InvalidInput(
                "I couldn't read that screenshot right now. Try again in a bit."
            ) from exc
        if not shot.is_travel and not asked:
            return None
        entries = drafts(shot)
        if not entries:
            raise InvalidInput(_NO_ENTRIES.text)
        return await booking_cases.add_from_screenshot(
            self._uow(), user, entries, trip_id=trip_id, now=now
        )

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
        # Answers to the chat's own questions are part of the chat; buttons on
        # notifications (bills, emails, plan alerts) are not.
        if data.startswith("hitl:"):
            _, confirmation_id, choice = [*data.split(":"), "", ""][:3]
            replies = await self.resolve(actor, confirmation_id, choice == "y")
            await self._keep(actor, "Confirm" if choice == "y" else "Cancel", replies, None)
            return replies
        if data == "act:undo":
            replies = await self.quick_action(actor, "undo")
            await self._keep(actor, "Undo", replies, None)
            return replies
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
        if data.startswith("plan:mute:"):
            return [await self._mute_plan(actor, data.removeprefix("plan:mute:"))]
        if data.startswith("trip:research:"):
            return [await self._research_trip(actor, data.removeprefix("trip:research:"))]
        if data.startswith("trip:book:"):
            booking_id, _, trip_id = data.removeprefix("trip:book:").partition(":")
            return [await self._booking_trip(actor, booking_id, trip_id)]
        return [Reply("I don't know that button.")]

    async def _research_trip(self, actor: UserId, run_id: str) -> Reply:
        """Make it a trip, on the message with a trip's research."""
        try:
            found = UUID(run_id)
        except ValueError:
            return Reply("I don't know that button.")
        async with self._uow() as tx:
            user = await tx.ledger.get_user(actor)
        if user is None:  # pragma: no cover
            return Reply("I don't know who you are yet.")
        try:
            trip = await research_cases.make_trip(self._uow, user, found, now=self._clock())
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        aside = f", setting aside {trip.set_aside} each payday" if trip.set_aside else ""
        budget = f", budget {trip.budget}" if trip.budget else ""
        return Reply(
            f"✈️ Trip saved: {trip.destination}, {trip.start:%d %b} to {trip.end:%d %b %Y}"
            f"{budget}{aside}. Change the dates or budget anytime on the trip page."
        )

    async def _booking_trip(self, actor: UserId, booking_id: str, trip_id: str) -> Reply:
        """Which trip a booking from email is for, on the question about it."""
        try:
            found = UUID(booking_id)
            trip = None if trip_id == "none" else UUID(trip_id)
        except ValueError:
            return Reply("I don't know that button.")
        try:
            booking, on = await booking_cases.attach(
                self._uow(), actor, found, trip, now=self._clock()
            )
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        if on is None:
            return Reply(f"OK, {booking.draft.title} isn't for a trip.")
        return Reply(f"✈️ {booking.draft.title} is on your {on.destination} trip.")

    async def _mute_plan(self, actor: UserId, plan_id: str) -> Reply:
        """Stop alerts for this plan, on a plan alert."""
        try:
            await plan_cases.set_alerts(self._uow(), actor, UUID(plan_id), on=False)
        except ValueError:
            return Reply("I don't know that button.")
        except NexusError as exc:
            return Reply(str(exc).capitalize() + ".")
        return Reply("🔕 No more alerts for that plan. It's still tracked in your record.")

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
        """Mark paid / Snooze on a bill reminder. Nothing is paid: marking it paid logs
        the bill's amount as this month's expense, unless it's already in the ledger."""
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
                paid = await bill_cases.mark_paid(self._uow, user, bill_id, now=now)
                return Reply(paid.message(ZoneInfo(user.timezone)))
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
