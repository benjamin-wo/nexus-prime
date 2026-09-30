"""Runs evaluation cases against a model and grades them.

Each case gets its own freshly seeded user and conversation, then the real agent
(kernel, graph, tools, confirmations) handles its turns. Grading looks at the
tool calls made, the confirmations asked for, the replies, and the user's data
afterwards. Nothing here knows which model it's talking to.
"""

import asyncio
import hashlib
import statistics
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import KERNEL, AgentDeps, AgentGraph, thread_id
from nexus.agent.memory_writer import MemoryWriter
from nexus.agent.receipts import LlmReceiptReader
from nexus.agent.service import RECENT_MESSAGES, AgentService, Reply
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application.fx import Rate
from nexus.application.ports import UnitOfWork
from nexus.domain.ledger import User
from nexus.evals import photos, seed
from nexus.evals.cases import Call, Case, Has, Turn
from nexus.evals.checks import World
from nexus.infra.db import tables
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.infra.llm.factory import text_of

MODEL_DOWN = "Sorry, I can't reach the AI model"
MAX_CONFIRMATIONS = 3  # per turn

# The user's own data. Logs, jobs and sessions don't count as a change.
_DATA_TABLES = (
    "transactions",
    "splits",
    "settlements",
    "budgets",
    "bills",
    "bill_occurrences",
    "categories",
    "category_rules",
    "salary_schedules",
    "subscriptions",
    "notification_settings",
)


class FixedRates:
    """One published rate, USD to SGD, from 1 Sep 2026."""

    async def rate(self, base: str, quote: str, on: Any) -> Rate | None:
        if (base, quote) == ("USD", "SGD"):
            return Rate(base, quote, seed.USD_SGD, seed.NOW.date().replace(day=1))
        if (base, quote) == ("SGD", "USD"):
            return Rate(base, quote, 1 / seed.USD_SGD, seed.NOW.date().replace(day=1))
        return None


@dataclass
class TurnLog:
    text: str
    replies: list[str] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    confirmations: int = 0
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    model_down: bool = False
    memory_failed: bool = False
    memory_input_tokens: int = 0  # the memory writer's, priced as the memory model
    memory_output_tokens: int = 0

    @property
    def last_reply(self) -> str:
        return self.replies[-1] if self.replies else ""


@dataclass
class CaseResult:
    case: Case
    turns: list[TurnLog]
    failures: list[str]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failures and self.error is None

    @property
    def input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def memory_input_tokens(self) -> int:
        return sum(t.memory_input_tokens for t in self.turns)

    @property
    def memory_output_tokens(self) -> int:
        return sum(t.memory_output_tokens for t in self.turns)


class Agent:
    """The production agent wired to one model, for one case's user."""

    def __init__(
        self,
        engine: AsyncEngine,
        model: BaseChatModel,
        photo_cache: Path,
        vision: BaseChatModel | None = None,
        memory: BaseChatModel | None = None,
    ) -> None:
        self.engine = engine
        self.model = model
        # Long-term memory, like MEMORY_MODEL: run after each turn, outside its timing.
        self.memory = MemoryWriter(memory or model)
        self.photo_cache = photo_cache
        # Receipt photos: a separate model if given, like OPENROUTER_VISION_MODEL.
        self.receipts = LlmReceiptReader(vision or model)
        self.skills = SkillLibrary.load()
        self.tools = build_tools(self.skills.body)
        self.new_conversation()

    def uow(self) -> UnitOfWork:
        return SqlUnitOfWork(self.engine)

    def new_conversation(self) -> None:
        async def health() -> str:
            return "All systems fine."

        self.graph = AgentGraph(
            AgentDeps(
                uow=self.uow,
                tools=self.tools,
                primary=self.model,
                fallbacks=(),
                skill_index=self.skills.index(),
                skill_tools=self.skills.tools(),
                health=health,
                clock=lambda: seed.NOW,
                rates=FixedRates(),
            )
        ).compile(InMemorySaver())
        self.service = AgentService(
            self.graph, self.uow, self.receipts, lambda: seed.NOW, None, FixedRates()
        )

    async def messages(self, user: User) -> list[BaseMessage]:
        config = {"configurable": {"thread_id": thread_id(user.id), "user_id": str(user.id)}}
        state = await self.graph.aget_state(config)  # type: ignore[arg-type]
        return list(state.values.get("messages", []))


def _confirmation(replies: Sequence[Reply], approve: bool) -> str | None:
    wanted = ":y" if approve else ":n"
    for reply in replies:
        for row in reply.buttons:
            for button in row:
                if button.data.startswith("hitl:") and button.data.endswith(wanted):
                    return button.data
    return None


async def _turn(agent: Agent, user: User, turn: Turn, ref: str) -> TurnLog:
    if turn.new_conversation:
        agent.new_conversation()
    log = TurnLog(turn.text)
    before = {m.id for m in await agent.messages(user)}  # by id: long chats drop old ones
    started = time.perf_counter()
    if turn.photo:
        image, media = await photos.load(turn.photo, agent.photo_cache)
        replies = await agent.service.handle_photo(user.id, image, media, turn.text or None, ref)
    else:
        replies = await agent.service.handle_text(user.id, turn.text, ref)
    all_replies = list(replies)
    for _ in range(MAX_CONFIRMATIONS):
        data = _confirmation(replies, turn.approve)
        if data is None:
            break
        log.confirmations += 1
        replies = await agent.service.press(user.id, data)
        all_replies.extend(replies)
    log.seconds = time.perf_counter() - started
    if not turn.photo:  # production queues this as a job once the reply is sent
        said = [
            text_of(m.content)
            for m in await agent.messages(user)
            if isinstance(m, HumanMessage) and text_of(m.content)
        ]
        before_tokens = agent.memory.input_tokens, agent.memory.output_tokens
        try:
            await agent.memory.remember(
                agent.uow, user, said[-RECENT_MESSAGES:] or [turn.text], seed.NOW
            )
        except Exception:
            log.memory_failed = True
        log.memory_input_tokens += agent.memory.input_tokens - before_tokens[0]
        log.memory_output_tokens += agent.memory.output_tokens - before_tokens[1]
    log.replies = [r.text for r in all_replies]
    log.model_down = any(r.text.startswith(MODEL_DOWN) for r in all_replies)
    for message in [m for m in await agent.messages(user) if m.id not in before]:
        if not isinstance(message, AIMessage) or message.additional_kwargs.get(KERNEL):
            continue
        log.calls.extend((c["name"], dict(c["args"])) for c in message.tool_calls)
        if message.usage_metadata:
            log.model_calls += 1
            log.input_tokens += message.usage_metadata.get("input_tokens", 0)
            log.output_tokens += message.usage_metadata.get("output_tokens", 0)
    return log


async def fingerprint(engine: AsyncEngine, user: User) -> str:
    """A hash of the user's data, to tell whether anything changed."""
    digest = hashlib.sha256()
    async with engine.connect() as db:
        for name in _DATA_TABLES:
            table = tables.metadata.tables[name]
            rows = await db.execute(select(table).where(table.c.user_id == user.id))
            for text in sorted(repr(tuple(r)) for r in rows):
                digest.update(f"{name}:{text}\n".encode())
    return digest.hexdigest()


def _same_number(a: str, b: str) -> bool:
    try:
        return Decimal(a.replace(",", "")) == Decimal(b.replace(",", ""))
    except InvalidOperation:
        return False


def _arg_matches(value: Any, wanted: str | Has) -> bool:
    if value is None:
        return False
    text = str(value)
    if isinstance(wanted, Has):
        return wanted.text.casefold() in text.casefold()
    return _same_number(text, wanted) or text.casefold() == wanted.casefold()


def _call_made(calls: list[tuple[str, dict[str, Any]]], wanted: Call) -> bool:
    return any(
        name == wanted.tool and all(_arg_matches(args.get(k), v) for k, v in wanted.args.items())
        for name, args in calls
    )


def _in_reply(reply: str, wanted: str | tuple[str, ...]) -> bool:
    options = (wanted,) if isinstance(wanted, str) else wanted
    text = reply.casefold()
    return any(o.casefold() in text for o in options)


async def grade(case: Case, turns: list[TurnLog], world: World, changed: bool) -> list[str]:
    failures: list[str] = []
    last = turns[-1]
    if any(t.model_down for t in turns):
        failures.append("the model call failed")
    for call in case.calls:
        if not _call_made(last.calls, call):
            failures.append(f"no {call.tool} call with {call.args or 'any arguments'}")
    called = {name for t in turns for name, _ in t.calls}
    for tool in case.forbid:
        if tool in called:
            failures.append(f"called {tool}")
    if case.asks:
        if "?" not in last.last_reply:
            failures.append("didn't ask a question")
        if changed:
            failures.append("changed data instead of asking")
    if case.unchanged and changed:
        failures.append("changed data")
    if case.confirms is not None and (last.confirmations > 0) != case.confirms:
        failures.append("asked to confirm" if last.confirmations else "didn't ask to confirm")
    for wanted in case.reply:
        if not _in_reply(last.last_reply, wanted):
            failures.append(f"reply lacks {wanted!r}")
    for phrase in case.never_say:
        if any(phrase.casefold() in r.casefold() for t in turns for r in t.replies):
            failures.append(f"said {phrase!r}")
    if case.max_reply is not None and len(last.last_reply) > case.max_reply:
        failures.append(f"reply longer than {case.max_reply} characters")
    for check in case.checks:
        try:
            held = await check.holds(world)
        except Exception as exc:  # one broken check fails its case, not the run
            failures.append(f"couldn't check {check.describe()}: {type(exc).__name__}")
            continue
        if not held:
            failures.append(f"expected {check.describe()}")
    return failures


async def run_case(
    engine: AsyncEngine,
    model: BaseChatModel,
    case: Case,
    telegram_id: int,
    photo_cache: Path = Path("eval-results/photos"),
    vision: BaseChatModel | None = None,
    memory: BaseChatModel | None = None,
) -> CaseResult:
    seeded = await seed.seed_user(lambda: SqlUnitOfWork(engine), telegram_id)
    user = seeded.user
    agent = Agent(engine, model, photo_cache, vision, memory)
    world = World(agent.uow, user, frozenset(t.id for t in await World(
        agent.uow, user, frozenset()
    ).transactions()))  # fmt: skip
    before = await fingerprint(engine, user)
    turns: list[TurnLog] = []
    try:
        for n, turn in enumerate(case.turns):
            turns.append(await _turn(agent, user, turn, f"eval:{case.id}:{n}"))
    except Exception as exc:  # a crash fails the case, not the run
        return CaseResult(case, turns, [], error=f"{type(exc).__name__}: {exc}")
    changed = await fingerprint(engine, user) != before
    return CaseResult(case, turns, await grade(case, turns, world, changed))


async def run_cases(
    engine: AsyncEngine,
    model_for: Callable[[Case], BaseChatModel],
    cases: Sequence[Case],
    *,
    concurrency: int = 4,
    first_telegram_id: int = 900_000,
    on_result: Callable[[CaseResult], None] | None = None,
    vision: BaseChatModel | None = None,
    memory: BaseChatModel | None = None,
) -> list[CaseResult]:
    """Run the cases, a few at a time, each as its own user."""
    gate = asyncio.Semaphore(concurrency)

    async def one(n: int, case: Case) -> CaseResult:
        async with gate:
            result = await run_case(
                engine,
                model_for(case),
                case,
                first_telegram_id + n,
                vision=vision,
                memory=memory,
            )
        if on_result:
            on_result(result)
        return result

    return list(await asyncio.gather(*(one(n, c) for n, c in enumerate(cases))))


@dataclass(frozen=True, slots=True)
class Pricing:
    prompt: Decimal  # USD per input token
    completion: Decimal  # USD per output token


@dataclass(frozen=True, slots=True)
class Summary:
    model: str
    results: list[CaseResult]
    pricing: Pricing | None
    memory_pricing: Pricing | None = None  # the memory model's; None: priced as the main one

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def rate(self) -> float:
        return self.passed / len(self.results) if self.results else 0.0

    def by(self, key: Callable[[CaseResult], str | None]) -> dict[str, tuple[int, int]]:
        totals: Counter[str] = Counter()
        wins: Counter[str] = Counter()
        for r in self.results:
            k = key(r) or "-"
            totals[k] += 1
            wins[k] += r.passed
        return {k: (wins[k], totals[k]) for k in sorted(totals)}

    def turn_seconds(self) -> list[float]:
        return [t.seconds for r in self.results for t in r.turns]

    def cost(self) -> Decimal | None:
        if self.pricing is None:
            return None
        memory = self.memory_pricing or self.pricing
        return sum(
            (
                r.input_tokens * self.pricing.prompt
                + r.output_tokens * self.pricing.completion
                + r.memory_input_tokens * memory.prompt
                + r.memory_output_tokens * memory.completion
                for r in self.results
            ),
            Decimal(0),
        )

    def markdown(self) -> str:
        seconds = self.turn_seconds()
        median = statistics.median(seconds) if seconds else 0.0
        p90 = statistics.quantiles(seconds, n=10)[-1] if len(seconds) >= 2 else median
        cost = self.cost()
        n = len(self.results) or 1
        lines = [
            f"### {self.model}",
            "",
            f"- Passed: **{self.passed}/{len(self.results)}** ({self.rate:.0%})",
            f"- Reply time per turn: median {median:.1f}s, p90 {p90:.1f}s",
            "- Tokens per case: "
            f"{sum(r.input_tokens for r in self.results) // n} in, "
            f"{sum(r.output_tokens for r in self.results) // n} out; memory writer "
            f"{sum(r.memory_input_tokens for r in self.results) // n} in, "
            f"{sum(r.memory_output_tokens for r in self.results) // n} out",
            "- Cost: "
            + ("unknown" if cost is None else f"${cost:.4f} total, ${cost / n:.5f} a case"),
            f"- Errors: {sum(r.error is not None for r in self.results)}, model failures: "
            f"{sum(any(t.model_down for t in r.turns) for r in self.results)}",
            "",
            "| Area | Passed |",
            "|---|---|",
            *(f"| {k} | {w}/{t} |" for k, (w, t) in self.by(lambda r: r.case.area).items()),
            "",
            "| Expected fix | Passed |",
            "|---|---|",
            *(
                f"| {k if k != '-' else 'already supported'} | {w}/{t} |"
                for k, (w, t) in self.by(lambda r: r.case.target).items()
            ),
        ]
        failed = [r for r in self.results if not r.passed]
        if failed:
            lines += ["", "Failures:", ""]
            for r in failed:
                why = r.error or "; ".join(r.failures)
                lines.append(f"- `{r.case.id}`: {why}")
        return "\n".join(lines)
