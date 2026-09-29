"""The agent graph.

    kernel ─┬─ reply (deterministic) ──────────────────────────────► END
            ├─ receipt draft ─► confirm ─► tools ─► kernel_reply ──► END
            └─ agent ⇄ (confirm ─► tools)                        ──► END

``confirm`` pauses the run with ``interrupt()`` before any consequential write
and has no side effects of its own, so re-running it on resume is safe.
"""

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID, uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from nexus.agent import kernel
from nexus.agent.tools import ToolContext, ToolSpec, UowFactory, run_tool
from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.categories import list_categories
from nexus.application.category_rules import list_rules
from nexus.application.fx import RateSource
from nexus.application.inbound import log_capability_gap
from nexus.application.users import get_user
from nexus.domain.errors import DuplicateSource, InvalidInput, NexusError
from nexus.domain.ledger import Direction, Source, UserId
from nexus.domain.money import Money
from nexus.infra.llm.factory import text_of

log = logging.getLogger(__name__)

_END: Literal["__end__"] = "__end__"
MAX_STEPS = 8
HISTORY_LIMIT = 40
_ID = re.compile(r"\s*\[id [0-9a-f-]{36}\]")

WROTE = "nexus_wrote"
KERNEL = "nexus_kernel"
RECEIPT = "nexus_receipt"
REF = "nexus_ref"
# Extra reply buttons: rows of [label, data].
BUTTONS = "nexus_buttons"

REFUSALS = {
    "transfer": "I can't send or transfer money. I only keep track of it.",
    "payment": "I can't make payments. I only record what you've spent.",
    "cancel_subscription": (
        "I can't cancel subscriptions for you. That has to be done with the provider."
    ),
}


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int


@dataclass(frozen=True, slots=True)
class AgentDeps:
    uow: UowFactory
    tools: dict[str, ToolSpec]
    primary: BaseChatModel
    fallbacks: Sequence[BaseChatModel]
    skill_index: str
    health: Callable[[], Awaitable[str]]
    clock: Callable[[], datetime]
    rates: RateSource | None = None


def strip_ids(text: str) -> str:
    return _ID.sub("", text)


def _last(messages: Sequence[BaseMessage], kind: type[BaseMessage]) -> Any:
    for message in reversed(messages):
        if isinstance(message, kind):
            return message
    raise LookupError(f"no {kind.__name__} in state")


def _trim(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """The recent history, starting at a user message so no tool result is orphaned."""
    window = list(messages[-HISTORY_LIMIT:])
    for i, message in enumerate(window):
        if isinstance(message, HumanMessage):
            return window[i:]
    return window[-1:]


def _reply(
    text: str, *, wrote: bool = False, buttons: list[list[tuple[str, str]]] | None = None
) -> Command[Any]:
    """End the turn with ``text``; ``buttons`` are extra (label, data) rows under it."""
    kwargs: dict[str, Any] = {WROTE: wrote}
    if buttons:
        kwargs[BUTTONS] = [[list(b) for b in row] for row in buttons]
    return Command(
        goto=END, update={"messages": [AIMessage(content=text, additional_kwargs=kwargs)]}
    )


class AgentGraph:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps
        schemas = [spec.schema() for spec in deps.tools.values() if spec.exposed]
        bound: Runnable[Any, Any] = deps.primary.bind_tools(schemas)
        if deps.fallbacks:
            bound = bound.with_fallbacks([m.bind_tools(schemas) for m in deps.fallbacks])
        self._model = bound

    # --- helpers ------------------------------------------------------------------

    async def _context(self, config: RunnableConfig) -> ToolContext:
        configurable = config.get("configurable") or {}
        actor = UserId(UUID(str(configurable["user_id"])))
        if configurable.get("thread_id") != thread_id(actor):
            raise RuntimeError("thread does not belong to the acting user")
        user = await get_user(self.deps.uow(), actor)
        return ToolContext(
            user=user, uow=self.deps.uow, now=self.deps.clock(), rates=self.deps.rates
        )

    async def _prompt(self, ctx: ToolContext) -> str:
        local = ctx.now.astimezone(ctx.tz)
        cats = await list_categories(ctx.uow(), ctx.user.id)
        rules = await list_rules(ctx.uow(), ctx.user.id)
        rule_line = (
            "Category rules (they file an expense when you leave its category out): "
            + "; ".join(f"“{v.rule.pattern}” → {v.category.name}" for v in rules[:40])
            + ".\n"
            if rules
            else ""
        )
        return (
            "You are Nexus, a personal finance assistant chatting on a phone.\n"
            f"Now: {local:%A %Y-%m-%d %H:%M} ({ctx.user.timezone}). "
            f"Home currency: {ctx.user.home_currency}.\n"
            f"Categories: {', '.join(c.name for c in cats)}.\n"
            f"{rule_line}\n"
            "Rules:\n"
            "- Use tools for every read or change. Never invent transactions, amounts, "
            "dates or results; report only what tools return.\n"
            "- If an amount or which transaction is meant is unclear, ask one short question.\n"
            "- You never move money: no payments, transfers or cancelling subscriptions. "
            "Say so plainly if asked.\n"
            "- You can't record income; ask the user to phrase it like "
            "'received 50 from Ann' or 'salary 3000'.\n"
            "- Keep replies short and plain. Never show transaction ids.\n\n"
            f"Skills (call load_skill for details):\n{self.deps.skill_index}"
        )

    # --- nodes ------------------------------------------------------------------------

    async def kernel_node(
        self, state: AgentState, config: RunnableConfig
    ) -> Command[Literal["agent", "confirm", "__end__"]]:
        ctx = await self._context(config)
        human: HumanMessage = _last(state["messages"], HumanMessage)
        text = text_of(human.content)
        meta = human.additional_kwargs

        if RECEIPT in meta:
            return self._receipt(ctx, meta[RECEIPT], meta.get(REF))
        if kernel.is_termination(text):
            return _reply("Okay, stopped.")
        if kernel.is_self_diagnosis(text):
            return _reply(await self.deps.health())
        income = kernel.parse_income(text, ctx.user.home_currency)
        if income is not None:
            return await self._income(ctx, income, meta.get(REF))
        intent = kernel.unsupported_intent(text)
        if intent is not None:
            await log_capability_gap(ctx.uow(), ctx.user.id, text, intent, "telegram")
            return _reply(REFUSALS[intent])
        return Command(goto="agent", update={"steps": 0})

    def _receipt(self, ctx: ToolContext, draft: dict[str, Any], ref: str | None) -> Command[Any]:
        amount = draft.get("amount")
        unreadable = (
            "I couldn't read a total from that photo. Tell me the amount, e.g. 'lunch 12.50'."
        )
        if not draft.get("is_receipt") or not amount:
            return _reply(unreadable)
        try:
            Money.of(str(amount).replace(",", ""), draft.get("currency") or ctx.user.home_currency)
        except InvalidInput:
            return _reply(unreadable)
        call = {
            "name": "log_receipt_expense",
            "id": f"receipt-{uuid4()}",
            "args": {
                "amount": str(amount),
                "currency": draft.get("currency"),
                "merchant": draft.get("merchant"),
                "date": draft.get("date"),
                "external_id": ref or f"receipt-{uuid4()}",
                "receipt_id": draft.get("receipt_id"),
            },
        }
        message = AIMessage(content="", tool_calls=[call], additional_kwargs={KERNEL: True})
        return Command(goto="confirm", update={"messages": [message]})

    async def _income(
        self, ctx: ToolContext, income: kernel.IncomeIntent, ref: str | None
    ) -> Command[Any]:
        try:
            if income.counterparty is not None:
                try:
                    result = await split_cases.settle_iou(
                        ctx.uow(),
                        ctx.user.id,
                        income.counterparty,
                        income.amount,
                        ctx.now,
                        notes=income.note,
                        source=Source.TEXT,
                        external_id=ref,
                    )
                except InvalidInput:
                    result = None  # no open IOU: plain income below
                if result is not None:
                    remaining = await split_cases.list_open_ious(
                        ctx.uow(), ctx.user.id, participant_name=income.counterparty
                    )
                    left = [i.outstanding for i in remaining]
                    status = (
                        f"{income.counterparty} still owes {', '.join(map(str, left))}."
                        if left
                        else f"{income.counterparty} is all settled."
                    )
                    return _reply(
                        f"Recorded {income.amount} from {income.counterparty}. {status}", wrote=True
                    )

            category = None
            if income.kind is kernel.IncomeKind.SALARY:
                cats = await list_categories(ctx.uow(), ctx.user.id)
                category = next((c.id for c in cats if c.name.casefold() == "income"), None)
            notes = income.note or ("Salary" if income.kind is kernel.IncomeKind.SALARY else None)
            await tx_cases.log_transaction(
                ctx.uow(),
                ctx.user.id,
                tx_cases.NewTransaction(
                    direction=Direction.IN,
                    amount=income.amount,
                    occurred_at=ctx.now,
                    counterparty=income.counterparty,
                    category_id=category,
                    notes=notes,
                    source=Source.TEXT,
                    external_id=ref,
                ),
            )
        except DuplicateSource:
            return _reply("That was already recorded.")
        except NexusError as exc:
            return _reply(f"I couldn't record that: {exc}")
        what = "salary" if income.kind is kernel.IncomeKind.SALARY else "income"
        source = f" from {income.counterparty}" if income.counterparty else ""
        done = f"Recorded {income.amount} {what}{source}."
        if income.kind is kernel.IncomeKind.SALARY:
            async with ctx.uow() as tx:
                schedule = await tx.planning.get_salary_schedule(ctx.user.id)
            question = salary_cases.baseline_question(schedule, income.amount)
            if question:
                # The usual amount only changes if the user says so.
                amount = f"{income.amount.amount}:{income.amount.currency}"
                return _reply(
                    f"{done} {question}",
                    wrote=True,
                    buttons=[[("Yes, update", f"salary:base:{amount}"), ("No", "salary:keep")]],
                )
        return _reply(done, wrote=True)

    async def agent_node(
        self, state: AgentState, config: RunnableConfig
    ) -> Command[Literal["confirm", "__end__"]]:
        steps = state.get("steps", 0) + 1
        if steps > MAX_STEPS:
            return _reply(
                "Sorry, that's taking too many steps. Could you break it into smaller requests?"
            )
        ctx = await self._context(config)
        prompt = [SystemMessage(content=await self._prompt(ctx)), *_trim(state["messages"])]
        try:
            response = await self._model.ainvoke(prompt)
        except Exception:
            log.exception("model call failed")
            return _reply("Sorry, I can't reach the AI model right now. Nothing was changed.")
        if not isinstance(response, AIMessage):  # pragma: no cover - chat models return AIMessage
            response = AIMessage(content=str(response))
        if response.tool_calls:
            return Command(goto="confirm", update={"messages": [response], "steps": steps})
        if not text_of(response.content):
            return _reply("Sorry, I didn't get that. Could you say it another way?")
        return Command(goto=_END, update={"messages": [response], "steps": steps})

    async def confirm_node(
        self, state: AgentState, config: RunnableConfig
    ) -> Command[Literal["tools", "__end__"]]:
        ctx = await self._context(config)
        request: AIMessage = _last(state["messages"], AIMessage)
        from_kernel = bool(request.additional_kwargs.get(KERNEL))
        summaries: list[str] = []
        for call in request.tool_calls:
            spec = self.deps.tools.get(call["name"])
            if spec is None or spec.confirm is None or not (spec.exposed or from_kernel):
                continue
            try:
                summaries.append(strip_ids(await spec.confirm(ctx, spec.parse(call["args"]))))
            except NexusError:
                continue  # the call will fail the same way in `tools`, changing nothing
        if not summaries:
            return Command(goto="tools")
        decision = interrupt({"summary": "\n".join(summaries)})
        if isinstance(decision, dict) and decision.get("approved") is True:
            return Command(goto="tools")
        declined = [
            ToolMessage(content="The user declined. Nothing was changed.", tool_call_id=call["id"])
            for call in request.tool_calls
        ]
        cancelled = AIMessage(content="Okay, cancelled. Nothing was changed.")
        return Command(goto=_END, update={"messages": [*declined, cancelled]})

    async def tools_node(
        self, state: AgentState, config: RunnableConfig
    ) -> Command[Literal["agent", "kernel_reply"]]:
        ctx = await self._context(config)
        request: AIMessage = _last(state["messages"], AIMessage)
        from_kernel = bool(request.additional_kwargs.get(KERNEL))
        results: list[ToolMessage] = []
        for call in request.tool_calls:
            spec = self.deps.tools.get(call["name"])
            buttons: list[list[tuple[str, str]]] | None = None
            if spec is None or not (spec.exposed or from_kernel):
                content, wrote = f"Error: there is no tool called {call['name']!r}.", False
            else:
                if "user_id" in call["args"]:
                    log.warning("dropped model-supplied user_id on %s", call["name"])
                try:
                    result = await run_tool(spec, ctx, dict(call["args"]))
                    content, wrote, buttons = result.text, result.wrote, result.buttons
                except Exception:
                    log.exception("tool %s failed", call["name"])
                    content, wrote = "Error: something went wrong running that.", False
            kwargs: dict[str, Any] = {WROTE: wrote}
            if buttons:
                kwargs[BUTTONS] = [[list(b) for b in row] for row in buttons]
            results.append(
                ToolMessage(
                    content=content,
                    tool_call_id=call["id"],
                    name=call["name"],
                    additional_kwargs=kwargs,
                )
            )
        return Command(
            goto="kernel_reply" if from_kernel else "agent", update={"messages": results}
        )

    async def kernel_reply_node(self, state: AgentState) -> dict[str, Any]:
        result: ToolMessage = _last(state["messages"], ToolMessage)
        text = strip_ids(text_of(result.content))
        if text.startswith("Error: ") and "already recorded" in text:
            text = "That receipt was already recorded."
        wrote = bool(result.additional_kwargs.get(WROTE))
        return {"messages": [AIMessage(content=text, additional_kwargs={WROTE: wrote})]}

    def compile(
        self, checkpointer: BaseCheckpointSaver[Any]
    ) -> CompiledStateGraph[Any, Any, Any, Any]:
        graph = StateGraph(AgentState)
        graph.add_node("kernel", self.kernel_node)
        graph.add_node("agent", self.agent_node)
        graph.add_node("confirm", self.confirm_node)
        graph.add_node("tools", self.tools_node)
        graph.add_node("kernel_reply", self.kernel_reply_node)
        graph.add_edge(START, "kernel")
        graph.add_edge("kernel_reply", END)
        return graph.compile(checkpointer=checkpointer)


def thread_id(actor: UserId) -> str:
    return f"user:{actor}"
