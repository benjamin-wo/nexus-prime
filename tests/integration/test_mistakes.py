"""Agent mistake signals through the real graph, tools and database: each leaves one
anonymous "agent" event with safe details only, and the weekly problem becomes one
ticket. Every name, merchant and amount is made up."""

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr

from nexus.agent.graph import MAX_STEPS
from nexus.application import bookings as booking_cases
from nexus.application import mistakes, ops
from nexus.application import undo as undo_cases
from nexus.application.transactions import NewTransaction, log_transaction
from nexus.domain.ledger import Direction, UserId
from nexus.domain.money import Money
from tests.fakes import NOW, call, say, scripted
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build
from tests.integration.test_email import person
from tests.integration.test_trip_undo import chat, plan, spain
from tests.integration.test_web_api import OWNER, World
from tests.unit.test_ops_tickets import Tracker

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

# What an agent event's detail may hold, and nothing else.
ALLOWED = {
    "wrote",
    "tools",
    "recovered",
    "tool",
    "error",
    "crashed",
    "seconds",
    "quick",
    "matched",
}
# Made-up words, merchants and amounts the tests say; none may reach an event.
SAID = ("Kopi Corner", "5.50", "Jamie", "Hilltop", "lunch", "dinner", "card 4111", "20")


@pytest.fixture
def events() -> Iterator[list[ops.Event]]:
    seen: list[ops.Event] = []
    ops.set_sink(seen.append)
    yield seen
    ops.set_sink(None)


def signs(events: list[ops.Event], name: str | None = None) -> list[ops.Event]:
    return [e for e in events if e.kind == mistakes.KIND and (name is None or e.name == name)]


def assert_safe(events: list[ops.Event]) -> None:
    for e in signs(events):
        assert set(e.detail) <= ALLOWED, e
        assert e.name in mistakes.SIGNALS
        shown = json.dumps(e.detail)
        for word in SAID:
            assert word.lower() not in shown.lower(), (word, e)


async def test_running_out_of_steps_is_a_signal(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    model = scripted(*[call("list_categories") for _ in range(MAX_STEPS)])
    await build(uow, model).handle_text(alice, "loop on Kopi Corner 5.50", "tg:1:1")
    [stopped] = signs(events)
    assert stopped.name == "step_limit" and not stopped.ok
    assert stopped.detail == {"wrote": False, "tools": ["list_categories"]}

    events.clear()
    model = scripted(
        call("log_expense", amount="5.50", merchant="Kopi Corner"),
        *[call("list_categories") for _ in range(MAX_STEPS)],
    )
    await build(uow, model).handle_text(alice, "kopi corner 5.50", "tg:1:2")
    [stopped] = signs(events)
    assert stopped.detail == {"wrote": True, "tools": ["list_categories", "log_expense"]}
    assert_safe(events)


async def test_an_empty_reply_says_whether_the_retry_worked(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    await build(uow, scripted(say(""), say("Hi there."))).handle_text(alice, "hello", "tg:1:1")
    [recovered] = signs(events)
    assert recovered.name == "empty_reply" and recovered.detail == {"recovered": True}

    events.clear()
    await build(uow, scripted(say(""), say(""))).handle_text(alice, "hello", "tg:1:2")
    [failed] = signs(events)
    assert failed.detail == {"recovered": False}

    events.clear()
    await build(uow, scripted(say("Hi."))).handle_text(alice, "hello", "tg:1:3")
    assert signs(events) == []


async def test_a_made_up_tool_keeps_only_the_real_one_it_was_near(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    model = scripted(call("log_expense_placeholder", amount="5"), say("Sorry."))
    await build(uow, model).handle_text(alice, "kopi corner 5", "tg:1:1")
    [unknown] = signs(events)
    assert unknown.name == "unknown_tool"
    assert unknown.detail == {"tool": "log_expense"}

    # The made-up name could hold anything ("split_with_jamie"): it is never kept.
    events.clear()
    model = scripted(call("split_with_jamie_tan", amount="5"), say("Sorry."))
    await build(uow, model).handle_text(alice, "lunch 5", "tg:1:2")
    [odd] = signs(events)
    assert "jamie" not in str(odd.detail)
    assert_safe(events)


async def test_a_tool_that_refuses_is_a_signal_with_a_coarse_error(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    model = scripted(
        call("log_expense", amount="lots"),
        call("log_expense", amount="5.50", category="Nonsense"),
        say("Which category?"),
    )
    await build(uow, model).handle_text(alice, "kopi corner 5.50 lots", "tg:1:1")
    first, second = signs(events, "tool_error")
    assert first.detail == {"tool": "log_expense", "error": "InvalidInput"}
    assert second.detail["tool"] == "log_expense"
    assert second.detail["error"] in {"InvalidInput", "NotFound"}
    # The tool's own event still says it was refused, as before.
    assert [e.detail.get("error") for e in events if e.kind == "tool"] == ["refused"] * 2
    assert_safe(events)


async def test_a_crashing_tool_is_a_signal_with_the_class_only(
    uow: UowFactory, alice: UserId, events: list[ops.Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("card 4111 declined for Jamie")

    monkeypatch.setattr("nexus.application.transactions.log_transaction", broken)
    model = scripted(call("log_expense", amount="5.50", merchant="Kopi Corner"), say("Sorry."))
    await build(uow, model).handle_text(alice, "kopi corner 5.50", "tg:1:1")
    [crash] = signs(events, "tool_error")
    assert crash.detail == {"tool": "log_expense", "error": "RuntimeError", "crashed": True}
    assert_safe(events)


async def test_an_undo_names_the_tool_and_how_soon(
    uow: UowFactory, alice: UserId, events: list[ops.Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mistakes, "utcnow", lambda: NOW + timedelta(seconds=45))
    model = scripted(
        call("log_expense", amount="5.50", merchant="Kopi Corner"),
        say("Logged."),
        call("undo_last_change"),
        say("Undone."),
    )
    agent = build(uow, model)
    await agent.handle_text(alice, "kopi corner 5.50", "tg:1:1")
    assert signs(events) == []

    # By the tool ("undo that" in chat).
    await agent.handle_text(alice, "undo that", "tg:1:2")
    [by_tool] = signs(events, "undo")
    assert by_tool.detail["tools"] == ["log_expense"] and by_tool.detail["quick"] is True
    assert 0 <= by_tool.detail["seconds"] <= 45

    # By the button.
    events.clear()
    model.script += [call("log_expense", amount="7", merchant="Kopi Corner"), say("Logged.")]
    await agent.handle_text(alice, "kopi corner 7", "tg:1:3")
    await agent.press(alice, "act:undo")
    [by_button] = signs(events, "undo")
    assert by_button.detail["tools"] == ["log_expense"]
    assert set(by_button.detail) == {"tools", "seconds", "quick"}

    # Nothing to undo: not a signal.
    events.clear()
    await agent.press(alice, "act:undo")
    assert signs(events) == []
    assert_safe(events)


async def test_undoing_a_split_names_split_bill(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    dinner = await log_transaction(
        uow(),
        alice,
        NewTransaction(Direction.OUT, Money.of("90", "SGD"), NOW, counterparty="Kopi Corner"),
    )
    model = scripted(
        call("split_bill", transaction_id=str(dinner.id), participants=[{"name": "Jamie"}]),
        say("Split it."),
    )
    agent = build(uow, model)
    [ask] = await agent.handle_text(alice, "split dinner with Jamie", "tg:1:1")
    await agent.press(alice, ask.buttons[0][0].data)  # Confirm
    events.clear()
    await agent.quick_action(alice, "undo")
    [undone] = signs(events, "undo")
    assert undone.detail["tools"] == ["split_bill"]
    assert_safe(events)


async def test_undoing_an_itinerary_change_names_the_itinerary_tools(
    uow: UowFactory, events: list[ops.Event]
) -> None:
    user = await person(uow)
    trip = await spain(uow, user)
    await booking_cases.add_manual(
        uow(), user.id, trip.id, plan("Hilltop Castle"), None, now=NOW, record=chat(user)
    )
    await undo_cases.undo_latest(uow(), user.id)
    [undone] = signs(events, "undo")
    assert undone.detail["tools"] == ["add_to_itinerary"] and undone.detail["quick"] is True
    assert_safe(events)  # the entry's title is not in it


async def test_a_correction_records_that_it_matched_and_the_tools_before_it(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    model = scripted(
        call("log_expense", amount="5.50", merchant="Kopi Corner"),
        say("Logged 5.50."),
        say("Sorry, changed it."),
        say("Sure."),
        say("OK."),
    )
    agent = build(uow, model)
    await agent.handle_text(alice, "kopi corner 5.50", "tg:1:1")
    await agent.handle_text(alice, "no I meant 20", "tg:1:2")
    [fixed] = signs(events, "correction")
    assert fixed.detail == {"matched": True, "tools": ["log_expense"]}

    # Not a correction: it doesn't start like one.
    events.clear()
    await agent.handle_text(alice, "now log lunch", "tg:1:3")
    assert signs(events) == []

    # A "no" after a turn that used no tool answers a question: nothing to correct.
    await agent.handle_text(alice, "no", "tg:1:4")
    assert signs(events) == []
    assert_safe(events)


async def test_a_correction_in_the_first_message_has_nothing_before_it(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    await build(uow, scripted(say("OK."))).handle_text(alice, "no I meant 20", "tg:1:1")
    assert signs(events) == []


async def test_signals_carry_the_trace_and_user_like_other_events(
    uow: UowFactory, alice: UserId, events: list[ops.Event]
) -> None:
    with ops.scope(trace="tg-9", user=alice, channel="telegram"):
        await build(uow, scripted(say(""), say(""))).handle_text(alice, "hello", "tg:1:1")
    [empty] = signs(events)
    assert (empty.trace, empty.channel) == ("tg-9", "telegram")
    assert empty.user == ops.user_ref(alice) and str(alice) not in json.dumps(empty.detail)


async def test_the_ops_job_opens_one_mistakes_ticket_and_updates_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    tracker = Tracker()
    monkeypatch.setattr("nexus.jobs.ops_tickets.GitHubIssues", lambda http, repo, token: tracker)
    world.app.state.settings = world.app.state.settings.model_copy(
        update={
            "ops_github_token": SecretStr("made-up-github-token"),
            "ops_github_repo": "made-up/nexus",
        }
    )
    ops.set_sink(world.app.state.ops.add)
    try:
        with ops.scope(trace="tg-1", user="made-up-user"):
            for _ in range(4):
                mistakes.undo(["split_bill"], NOW)
            mistakes.tool_error("change_itinerary_entry", "InvalidInput")
    finally:
        ops.set_sink(None)
    await world.app.state.ops.flush()

    report = (await owner.get("/api/ops/report?hours=1")).json()
    [problem] = [p for p in report["problems"] if p["area"] == "agent"]
    assert problem["topic"] == "Agent mistakes this week" and problem["count"] == 5
    assert "- undo after split_bill: 4" in problem["lines"]

    opened = (await owner.send("POST", "/api/ops/tickets")).json()
    assert len(opened["opened"]) == 1
    assert [c[1][0] for c in tracker.calls if c[0] == "open"] == ["[ops] Agent mistakes this week"]

    ops.set_sink(world.app.state.ops.add)
    try:
        with ops.scope(trace="tg-2"):
            mistakes.undo(["split_bill"], NOW)
    finally:
        ops.set_sink(None)
    await world.app.state.ops.flush()
    again = (await owner.send("POST", "/api/ops/tickets")).json()
    assert again["opened"] == [] and len(again["updated"]) == 1
    assert len([c for c in tracker.calls if c[0] == "open"]) == 1
