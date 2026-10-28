"""The system prompt starts with everything that is the same for every user and every turn,
so the provider's prefix cache can serve it; whatever is the user's or the moment's comes
after it. The tools sent with a call are in a fixed order for the same reason. All made-up."""

from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from nexus.agent import graph as graph_module
from nexus.agent.graph import (
    ABOUT_THE_USER,
    CORE_TOOLS,
    AgentDeps,
    AgentGraph,
    AgentState,
    tool_order,
)
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import ToolContext, UowFactory, build_tools
from nexus.domain.ledger import Role, User, UserId
from nexus.domain.voice import Preset, prompt_block, settings_for

SKILLS = SkillLibrary.load()
TOOLS = build_tools(SKILLS.body)


class Recorder:
    """Stands in for the chat model: remembers the tool schemas it was given, in order."""

    def __init__(self) -> None:
        self.bound: list[list[str]] = []

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, Any]:
        self.bound.append([t["function"]["name"] for t in tools])
        return cast(Runnable[Any, Any], self)


async def _health() -> str:
    return "fine"


def build(recorder: Recorder | None = None) -> AgentGraph:
    return AgentGraph(
        AgentDeps(
            uow=cast(UowFactory, lambda: None),
            tools=TOOLS,
            primary=cast(BaseChatModel, recorder or Recorder()),
            fallbacks=(),
            skill_index=SKILLS.index(),
            skill_tools=SKILLS.tools(),
            health=_health,
            clock=lambda: datetime(2026, 10, 28, tzinfo=UTC),
        )
    )


def person(zone: str, currency: str, home: str = "") -> User:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    return User(UserId(uuid4()), 1, 1, zone, currency, Role.MEMBER, created, home_timezone=home)


@pytest.fixture(autouse=True)
def lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Categories and rules as the user's own: set by each test through ``mine``."""

    async def categories(uow: object, user_id: UserId) -> list[Any]:
        return [SimpleNamespace(name=n) for n in MINE[user_id]["categories"]]

    async def rules(uow: object, user_id: UserId) -> list[Any]:
        return [
            SimpleNamespace(rule=SimpleNamespace(pattern=p), category=SimpleNamespace(name=c))
            for p, c in MINE[user_id]["rules"]
        ]

    monkeypatch.setattr(graph_module, "list_categories", categories)
    monkeypatch.setattr(graph_module, "list_rules", rules)
    MINE.clear()


MINE: dict[UserId, dict[str, Any]] = {}


async def prompt(
    user: User, now: datetime, *, categories: list[str], rules: list[tuple[str, str]], **state: Any
) -> str:
    MINE[user.id] = {"categories": categories, "rules": rules}
    ctx = ToolContext(user=user, uow=cast(UowFactory, lambda: None), now=now)
    return await build()._prompt(ctx, cast(AgentState, {"messages": [], "steps": 0, **state}))


async def two_prompts() -> tuple[str, str, str]:
    """Two very different users on two different days, with everything that can differ set;
    the third is the plain prompt of a user with nothing but the defaults."""
    ann = await prompt(
        person("Asia/Singapore", "SGD"),
        datetime(2026, 10, 28, 3, 15, tzinfo=UTC),
        categories=["Coffee Runs", "Transport", "Rent"],
        rules=[("kopi corner", "Coffee Runs")],
        snapshot="Spending this month: 1,204 of 2,000. Wallets: DBS 3,150; Savings 9,000.",
        memories="Ann splits dinners with Ben.",
        summary="Ann asked about a trip to Kamakura.",
        summary_at="2026-10-27T09:00:00+00:00",
        voice=prompt_block(settings_for(Preset.CHILL)),
        open_items=[{"text": "Send Ben 40 for dinner", "since": "2026-10-27T09:00:00+00:00"}],
    )
    ben = await prompt(
        person("Europe/Madrid", "EUR", home="Europe/Lisbon"),
        datetime(2026, 11, 3, 19, 40, tzinfo=UTC),
        categories=["Groceries", "Gifts"],
        rules=[],
        snapshot="Spending this month: 88 of 400.",
    )
    plain = await prompt(
        person("UTC", "USD"),
        datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        categories=[],
        rules=[],
    )
    return ann, ben, plain


def head_of(text: str) -> str:
    head, sep, _ = text.partition(f"\n\n{ABOUT_THE_USER}\n")
    assert sep, "the prompt has no block about the user"
    return head


async def test_every_users_prompt_starts_with_the_same_fixed_text() -> None:
    ann, ben, plain = await two_prompts()
    assert head_of(ann) == head_of(ben) == head_of(plain)
    head = head_of(ann)
    # The fixed text is the persona, every rule and the skill list: the bulk of the prompt.
    assert head.startswith("You are Nexus, a personal finance assistant")
    for fixed in (
        "Rules:\n",
        "- Use tools for every read or change.",
        "- You never move money",
        "- Reply style:",
        "- A message with <image>",
        "Skills: you start with the core tools.",
        SKILLS.index(),
    ):
        assert fixed in head
    assert len(head) > 6000
    assert len(head) > 2 * len(ann) // 3  # most of even a busy user's prompt


async def test_whatever_is_the_users_or_the_moments_comes_after_the_fixed_text() -> None:
    ann, ben, _ = await two_prompts()
    ann_head, ben_head = head_of(ann), head_of(ben)
    for text in (
        "Now: ",
        "Home currency: ",
        "Categories: ",
        "Category rules",
        "Coffee Runs",
        "Kamakura",
        "Spending this month",
        "How you talk",
        "Ann splits dinners",
        "Send Ben 40",
        "Asia/Singapore",
        "2026-10-28",
        "SGD",
    ):
        assert text not in ann_head, text
    for text in ("Europe/Madrid", "Europe/Lisbon", "EUR", "Groceries", "2026-11-03"):
        assert text not in ben_head, text

    tail = ann.partition(f"\n\n{ABOUT_THE_USER}\n")[2]
    assert "Home currency: SGD.\nCategories: Coffee Runs, Transport, Rent.\n" in tail
    assert "Category rules" in tail and "“kopi corner” → Coffee Runs" in tail
    assert "How you talk" in tail
    for section in (
        "The user's money right now",
        "What you know about the user",
        "Earlier in this conversation (a summary, written",
        "Still open from earlier",
    ):
        assert section in tail
    # The moment is last: it changes every minute and nothing after it could be cached.
    assert tail.endswith("Now: Wednesday 2026-10-28 11:15 (Asia/Singapore).")
    assert ben.endswith("Now: Tuesday 2026-11-03 20:40 (Europe/Madrid, home: Europe/Lisbon).")
    # The fixed rule that points at it points the right way.
    assert "from Now below" in ann_head


async def test_the_fixed_part_is_most_of_every_prompt() -> None:
    for text in await two_prompts():
        assert len(head_of(text)) / len(text) > 0.8


def test_tools_are_sent_core_first_in_their_fixed_order_then_by_name() -> None:
    names = {n for n, s in TOOLS.items() if s.exposed}
    loaded = {
        n
        for skill in ("trips", "wallets")
        for n in SKILLS.tools().get(skill, ())
        if n in names and n not in CORE_TOOLS
    }
    assert loaded, "the bundled skills have tools beyond the core ones"
    wanted = set(CORE_TOOLS) | loaded
    ordered = tool_order(wanted)
    assert ordered[: len(CORE_TOOLS)] == list(CORE_TOOLS)
    assert ordered[len(CORE_TOOLS) :] == sorted(loaded)
    # However the set was built, the order is the same.
    assert tool_order(sorted(wanted, reverse=True)) == tool_order(frozenset(wanted)) == ordered
    # Fewer core tools (an image turn): the rest keep their places.
    fewer = tool_order(wanted - {"log_expense", "load_skill"})
    assert fewer == [n for n in ordered if n not in {"log_expense", "load_skill"}]


def test_the_model_is_bound_to_the_same_tools_in_the_same_order_every_time() -> None:
    names = frozenset(
        n for n, s in TOOLS.items() if s.exposed and (n in CORE_TOOLS or n.startswith("trip"))
    )
    first, second = Recorder(), Recorder()
    build(first)._model(names)
    build(second)._model(frozenset(reversed(sorted(names))))
    assert first.bound == second.bound == [tool_order(names)]
    assert first.bound[0][: len(CORE_TOOLS)] == list(CORE_TOOLS)
    assert set(first.bound[0]) == names  # the same tools are offered, only in a fixed order


def test_offered_tools_are_unchanged_by_the_ordering() -> None:
    state = cast(AgentState, {"messages": [], "steps": 0, "skills": {"wallets": 3}})
    offered = build().offered(state)
    assert set(CORE_TOOLS) <= offered
    assert offered - set(CORE_TOOLS) == set(SKILLS.tools()["wallets"]) & {
        n for n, s in TOOLS.items() if s.exposed
    } - set(CORE_TOOLS)
