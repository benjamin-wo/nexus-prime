"""Long-term memory: stored per user, written from the user's own words by a small
model after each turn, recalled into the prompt, and forgotten on request."""

from datetime import date, timedelta
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from nexus.agent.memory_writer import MemoryUpdate, MemoryWriter
from nexus.application import memory as memory_cases
from nexus.application.memory import Action, MemoryChange
from nexus.application.users import get_user
from nexus.domain.errors import NotFound
from nexus.domain.ledger import User, UserId
from nexus.domain.memory import MAX_MEMORIES, MemoryKind
from nexus.jobs.handlers import MEMORY_UPDATE
from tests.fakes import NOW, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build

pytestmark = pytest.mark.integration


class FakeWriterModel:
    """Stands in for the memory model: returns scripted updates, records prompts."""

    def __init__(self, *updates: dict[str, Any]) -> None:
        self.updates = list(updates)
        self.seen: list[list[BaseMessage]] = []

    def with_structured_output(self, schema: Any, include_raw: bool = False) -> Any:
        async def reply(messages: list[BaseMessage]) -> dict[str, Any]:
            self.seen.append(messages)
            update = MemoryUpdate.model_validate(self.updates.pop(0) if self.updates else {})
            raw = AIMessage(
                content="",
                usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            )
            return {"raw": raw, "parsed": update, "parsing_error": None}

        return RunnableLambda(reply)


def add(kind: str, text: str, day: str | None = None) -> dict[str, Any]:
    return {"changes": [{"action": "add", "kind": kind, "text": text, "date": day}]}


async def user_of(uow: UowFactory, actor: UserId) -> User:
    return await get_user(uow(), actor)


async def test_the_writer_adds_updates_and_forgets(uow: UowFactory, alice: UserId) -> None:
    user = await user_of(uow, alice)
    model = FakeWriterModel(
        add("fact", "Ann is the user's sister."),
        {"changes": [{"action": "update", "number": 1, "text": "Ann is the user's older sister."}]},
        {"changes": [{"action": "delete", "number": 1}]},
    )
    writer = MemoryWriter(model)  # type: ignore[arg-type]

    assert await writer.remember(uow, user, ["ann is my sister"], NOW) == 1
    [memory] = await memory_cases.list_memories(uow(), alice)
    assert (memory.kind, memory.text) == (MemoryKind.FACT, "Ann is the user's sister.")

    await writer.remember(uow, user, ["she's older than me"], NOW)
    [memory] = await memory_cases.list_memories(uow(), alice)
    assert memory.text == "Ann is the user's older sister."
    # The writer was shown the memory it was asked to change, numbered.
    assert "1. (fact) Ann is the user's sister." in str(model.seen[-1][0].content)

    await writer.remember(uow, user, ["forget that"], NOW)
    assert await memory_cases.list_memories(uow(), alice) == []
    assert writer.input_tokens == 300 and writer.output_tokens == 30


async def test_the_writer_ignores_what_it_cant_use(uow: UowFactory, alice: UserId) -> None:
    user = await user_of(uow, alice)
    model = FakeWriterModel(
        {
            "changes": [
                {"action": "update", "number": 7, "text": "no such memory"},
                {"action": "delete", "number": None},
                {"action": "add", "kind": "fact", "text": "x" * 400},
                {"action": "add", "kind": "episode", "text": "Ride was for work", "date": "27/9"},
            ]
        }
    )
    writer = MemoryWriter(model)  # type: ignore[arg-type]
    assert await writer.remember(uow, user, ["the ride was for work"], NOW) == 1
    [memory] = await memory_cases.list_memories(uow(), alice)
    assert memory.kind is MemoryKind.EPISODE and memory.happened_on is None
    assert await writer.remember(uow, user, ["   "], NOW) == 0  # nothing said, no model call
    assert len(model.seen) == 1


async def test_memories_belong_to_their_user(uow: UowFactory, alice: UserId, bob: UserId) -> None:
    await memory_cases.apply_changes(
        uow(),
        await user_of(uow, alice),
        [MemoryChange(Action.ADD, MemoryKind.FACT, "Ann is the user's sister.")],
        now=NOW,
    )
    [memory] = await memory_cases.list_memories(uow(), alice)
    bob_user = await user_of(uow, bob)
    assert await memory_cases.list_memories(uow(), bob) == []
    assert await memory_cases.recall(uow, bob_user, "ann") == []
    with pytest.raises(NotFound):
        await memory_cases.forget(uow(), bob, memory.id)
    # Bob's writer can't reach it either.
    changed = await memory_cases.apply_changes(
        uow(),
        bob_user,
        [
            MemoryChange(Action.DELETE, target=memory.id),
            MemoryChange(Action.UPDATE, text="x", target=memory.id),
        ],
        now=NOW,
    )
    assert changed == 0
    assert len(await memory_cases.list_memories(uow(), alice)) == 1


async def test_recall_picks_lasting_and_relevant(uow: UowFactory, alice: UserId) -> None:
    user = await user_of(uow, alice)
    changes = [MemoryChange(Action.ADD, MemoryKind.PREFERENCE, "Wants short replies.")]
    changes += [
        MemoryChange(Action.ADD, MemoryKind.EPISODE, f"Note {n} about lunch.", date(2026, 9, n))
        for n in range(1, 10)
    ]
    changes.append(
        MemoryChange(
            Action.ADD, MemoryKind.EPISODE, "The Grab ride was for work.", date(2026, 8, 1)
        )
    )
    for i, change in enumerate(changes):  # one at a time, so each is newer than the last
        await memory_cases.apply_changes(uow(), user, [change], now=NOW + timedelta(seconds=i))
    recalled = await memory_cases.recall(uow, user, "what was that grab ride for?")
    texts = [m.text for m in recalled]
    assert "Wants short replies." in texts
    assert "The Grab ride was for work." in texts  # old, but it matches
    assert "Note 9 about lunch." in texts  # the newest episodes come along
    assert "Note 1 about lunch." not in texts
    block = memory_cases.describe(recalled)
    assert "- (episode) 2026-08-01: The Grab ride was for work." in block


async def test_old_episodes_make_way(uow: UowFactory, alice: UserId) -> None:
    user = await user_of(uow, alice)
    fact = [MemoryChange(Action.ADD, MemoryKind.FACT, "Ann is the user's sister.")]
    await memory_cases.apply_changes(uow(), user, fact, now=NOW - timedelta(days=400))
    episodes = [
        MemoryChange(Action.ADD, MemoryKind.EPISODE, f"Episode {n}.") for n in range(MAX_MEMORIES)
    ]
    await memory_cases.apply_changes(uow(), user, episodes, now=NOW)
    kept = await memory_cases.list_memories(uow(), alice)
    assert len(kept) == MAX_MEMORIES
    assert any(m.kind is MemoryKind.FACT for m in kept)  # the oldest, but not an episode


async def test_the_model_sees_memories_and_the_turn_queues_the_writer(
    uow: UowFactory, alice: UserId
) -> None:
    user = await user_of(uow, alice)
    await memory_cases.apply_changes(
        uow(), user, [MemoryChange(Action.ADD, MemoryKind.FACT, "Goes by Benji.")], now=NOW
    )
    queued: list[tuple[UserId, list[str], str]] = []

    async def after(actor: UserId, messages: list[str], ref: str) -> None:
        queued.append((actor, messages, ref))

    model = scripted(say("Hi Benji."), say("ok"))
    agent = build(uow, model)
    agent._after_turn = after
    await agent.handle_text(alice, "hello", "tg:1:1")
    await agent.handle_text(alice, "ann is my sister", "tg:1:2")
    system = model.seen[0][0]
    assert isinstance(system, SystemMessage)
    assert "- (fact) Goes by Benji." in str(system.content)
    assert queued[-1] == (alice, ["hello", "ann is my sister"], "tg:1:2")


async def test_a_failing_hook_never_reaches_the_user(uow: UowFactory, alice: UserId) -> None:
    async def broken(*_: Any) -> None:
        raise RuntimeError("queue down")

    agent = build(uow, scripted(say("Logged.")))
    agent._after_turn = broken
    [reply] = await agent.handle_text(alice, "coffee 4", "tg:2:1")
    assert reply.text == "Logged."


def test_the_job_kind_is_stable() -> None:
    assert MEMORY_UPDATE == "memory.update"  # queued jobs outlive a deploy
