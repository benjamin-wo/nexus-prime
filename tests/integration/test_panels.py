"""Domain panels (ADR 0001): the tools say what they resolved, the agent loop reports each
panel after its tool answers, and the web chat stream sends it as ``panel.upsert`` when panels
are on. Every name and figure here is made up."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage

from nexus.agent.panels import PanelRef
from nexus.agent.progress import Step
from nexus.agent.tools import ToolContext, ToolResult, build_tools, run_tool
from nexus.application import trips as trip_cases
from nexus.channels.web.chat_stream import stream_turn
from nexus.domain.ledger import User
from nexus.domain.money import Money
from tests.fakes import NOW, FakeRates, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

EN = "\N{EN DASH}"  # a range of days: 1-30 Sep
RATES = FakeRates({})
TOOLS = build_tools(lambda _: "")


async def use(
    uow: UowFactory, user: User, name: str, args: Mapping[str, object] | None = None
) -> ToolResult:
    ctx = ToolContext(user, uow, NOW, RATES)
    return await run_tool(TOOLS[name], ctx, dict(args or {}))


def one(result: ToolResult) -> PanelRef:
    assert result.panels is not None and len(result.panels) == 1
    return result.panels[0]


async def japan(uow: UowFactory, owner: User) -> UUID:
    trip = await trip_cases.create_trip(
        uow(),
        owner,
        trip_cases.TripDraft(
            "Japan", date(2026, 12, 10), date(2026, 12, 18), "JPY", Money.of("3000", "SGD")
        ),
        now=NOW,
    )
    return trip.id


# --- what each tool resolved ----------------------------------------------------------------


async def test_month_outlook_reports_the_month_it_resolved(uow: UowFactory) -> None:
    user = await person(uow)
    this = one(await use(uow, user, "month_outlook"))  # no month: this one
    assert (this.panel_id, this.params) == ("finance.month_outlook", {"month": "2026-09"})
    assert this.topic == "your outlook for September 2026"
    august = one(await use(uow, user, "month_outlook", {"month": "2026-08"}))
    assert august.params == {"month": "2026-08"}
    assert august.topic == "your outlook for August 2026"


async def test_month_outlook_opens_no_panel_when_it_refuses(uow: UowFactory) -> None:
    user = await person(uow)
    result = await use(uow, user, "month_outlook", {"month": "next tuesday"})
    assert result.text.startswith("Error:") and result.panels is None


async def test_list_budgets_reports_this_month_even_with_none_set(uow: UowFactory) -> None:
    user = await person(uow)
    empty = await use(uow, user, "list_budgets")
    assert empty.text == "No budgets set."
    assert one(empty).params == {"month": "2026-09"}
    await use(uow, user, "set_budget", {"category": "Dining Out", "amount": "800"})
    listed = await use(uow, user, "list_budgets")
    panel = one(listed)
    assert (panel.panel_id, panel.params) == ("finance.budgets", {"month": "2026-09"})
    assert panel.topic == "your budgets for September 2026"


async def test_a_write_tool_opens_nothing(uow: UowFactory) -> None:
    user = await person(uow)
    result = await use(uow, user, "set_budget", {"category": "Dining Out", "amount": "800"})
    assert result.wrote and result.panels is None


async def test_find_transactions_reports_the_category_it_resolved(uow: UowFactory) -> None:
    user = await person(uow)
    result = await use(
        uow,
        user,
        "find_transactions",
        {"category": "dining out", "start_date": "2026-09-01", "end_date": "2026-09-30"},
    )
    panel = one(result)
    categories = (await use(uow, user, "list_categories")).text
    assert "Dining Out" in categories
    assert panel.panel_id == "finance.transactions"
    assert set(panel.params) == {"category_id", "start", "end"}
    UUID(str(panel.params["category_id"]))  # the resolved id, not the name typed
    assert (panel.params["start"], panel.params["end"]) == ("2026-09-01", "2026-09-30")
    assert panel.topic == f"Dining Out, 1{EN}30 Sep"
    assert "user_id" not in panel.params


async def test_find_transactions_passes_search_and_direction_as_the_endpoint_names_them(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    result = await use(uow, user, "find_transactions", {"search": "Grab", "direction": "out"})
    panel = one(result)
    assert result.text == "No matching transactions."  # an empty answer is still the answer
    assert panel.params == {"direction": "out", "search": "Grab"}
    assert panel.topic == "“Grab”"


async def test_find_transactions_opens_no_panel_for_an_unknown_category(uow: UowFactory) -> None:
    user = await person(uow)
    result = await use(uow, user, "find_transactions", {"category": "Spaceships"})
    assert result.text.startswith("Error: unknown category") and result.panels is None


async def test_query_ledger_reports_the_period_it_defaulted(uow: UowFactory) -> None:
    user = await person(uow)
    panel = one(await use(uow, user, "query_ledger"))
    assert panel.params == {"direction": "out", "start": "2026-09-01", "end": "2026-09-28"}
    assert panel.topic == f"Spending, 1{EN}28 Sep"
    dining = one(
        await use(
            uow,
            user,
            "query_ledger",
            {"category": "Dining Out", "start_date": "2026-08-01", "end_date": "2026-08-31"},
        )
    )
    assert set(dining.params) == {"direction", "start", "end", "category_id"}
    assert dining.topic == f"Dining Out, 1{EN}31 Aug"
    uncategorised = one(await use(uow, user, "query_ledger", {"category": "uncategorised"}))
    assert uncategorised.params["uncategorized"] is True
    assert "category_id" not in uncategorised.params


async def test_query_ledger_opens_no_panel_for_filters_the_ledger_page_cannot_show(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    for args in ({"min_amount": "50"}, {"max_amount": "10"}, {"days": ["sat", "sun"]}):
        result = await use(uow, user, "query_ledger", args)
        assert not result.text.startswith("Error:") and result.panels is None, args


async def test_trip_status_reports_the_resolved_trip_id_not_the_name(uow: UowFactory) -> None:
    owner = await person(uow)
    trip_id = await japan(uow, owner)
    panel = one(await use(uow, owner, "trip_status", {"trip": "jap"}))
    assert panel.panel_id == f"travel.trip_budget:{trip_id}"
    assert panel.params == {"trip_id": str(trip_id)}
    assert panel.topic == "the Japan trip's money"
    nameless = one(await use(uow, owner, "trip_status"))  # the one that is on or next
    assert nameless.params == {"trip_id": str(trip_id)}


async def test_trip_status_opens_no_panel_for_a_missing_trip_or_for_a_member(
    uow: UowFactory,
) -> None:
    owner = await person(uow)
    member = await person(uow, 4343)
    trip_id = await japan(uow, owner)
    missing = await use(uow, owner, "trip_status", {"trip": "Atlantis"})
    assert missing.text.startswith("Error:") and missing.panels is None
    async with uow() as tx:
        await tx.trips.add_member(owner.id, trip_id, member.id, None, NOW)
        await tx.commit()
    seen = await use(uow, member, "trip_status", {"trip": "japan"})
    assert "plan, shared with the user" in seen.text
    assert seen.panels is None  # a member never gets the trip's money in a panel


# --- the agent loop -------------------------------------------------------------------------


async def test_the_loop_reports_a_panel_after_its_tool_and_before_the_reply(
    uow: UowFactory,
) -> None:
    owner = await person(uow)
    trip_id = await japan(uow, owner)
    model = scripted(call("trip_status", trip="japan"), say("Japan is on track."))
    seen: list[str] = []

    async def on_step(step: Step) -> None:
        seen.append(f"{step.label}: {step.state}")

    async def on_panel(panel: PanelRef) -> None:
        seen.append(panel.panel_id)

    reply = only(
        await build(uow, model).handle_text(
            owner.id, "how is japan", "web:1:1", on_step=on_step, on_panel=on_panel
        )
    )
    assert reply.text.startswith("Japan is on track.")  # then a note that Travel was added
    assert seen == [
        "Checking the trip: running",
        "Checking the trip: done",
        f"travel.trip_budget:{trip_id}",
    ]
    assert len(model.seen) == 2  # the panel was reported before the second model call


async def test_a_failed_tool_opens_no_panel_and_a_turn_without_a_sink_is_unchanged(
    uow: UowFactory,
) -> None:
    owner = await person(uow)
    heard: list[PanelRef] = []

    async def on_panel(panel: PanelRef) -> None:
        heard.append(panel)

    model = scripted(call("month_outlook", month="someday"), say("Which month?"))
    await build(uow, model).handle_text(owner.id, "outlook", "web:1:1", on_panel=on_panel)
    assert heard == []
    quiet = scripted(call("list_budgets"), say("None yet."))
    reply = only(await build(uow, quiet).handle_text(owner.id, "budgets", "web:1:2"))
    assert reply.text == "None yet."


async def test_a_sink_that_breaks_does_not_stop_the_turn(uow: UowFactory) -> None:
    owner = await person(uow)

    async def broken(panel: PanelRef) -> None:
        raise RuntimeError("the screen is gone")

    model = scripted(call("list_budgets"), say("None yet."))
    reply = only(
        await build(uow, model).handle_text(owner.id, "budgets", "web:1:1", on_panel=broken)
    )
    assert reply.text == "None yet."


# --- the web stream -------------------------------------------------------------------------

AS_OF = datetime(2026, 11, 15, 6, 2, 3, tzinfo=UTC)


async def streamed(
    uow: UowFactory, user: User, model_script: Sequence[AIMessage], *, panels: bool
) -> list[tuple[str, object]]:
    model = scripted(*model_script)
    response = stream_turn(
        build(uow, model),
        user.id,
        "how is japan",
        "web:1:1",
        replies=lambda done: [{"text": r.text} for r in done],
        panels=panels,
        clock=lambda: AS_OF,
    )
    frames: list[tuple[str, object]] = []
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else bytes(chunk).decode()
        if text.startswith(":"):
            continue
        event, data = text.strip().split("\n", 1)
        frames.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return frames


async def test_the_stream_sends_a_panel_upsert_when_panels_are_on(uow: UowFactory) -> None:
    owner = await person(uow)
    trip_id = await japan(uow, owner)
    frames = await streamed(
        uow, owner, [call("trip_status", trip="japan"), say("Japan is on track.")], panels=True
    )
    assert [event for event, _ in frames] == ["step", "step", "panel.upsert", "replies"]
    assert frames[2] == (
        "panel.upsert",
        {
            "panel_id": f"travel.trip_budget:{trip_id}",
            "kind": "travel.trip_budget",
            "version": 1,
            "params": {"trip_id": str(trip_id)},
            "topic": "the Japan trip's money",
            "as_of": "2026-11-15T06:02:03+00:00",
            "message_id": "web:1:1",
        },
    )
    event, data = frames[3]
    assert event == "replies"
    assert isinstance(data, list) and data[0]["text"].startswith("Japan is on track.")


async def test_the_stream_sends_each_panel_a_turn_opens(uow: UowFactory) -> None:
    owner = await person(uow)
    await japan(uow, owner)
    script = [
        call("month_outlook", month="2026-10"),
        call("find_transactions", category="Dining Out", start_date="2026-10-01"),
        say("Here."),
    ]
    frames = await streamed(uow, owner, script, panels=True)
    opened = [data for event, data in frames if event == "panel.upsert"]
    assert [p["panel_id"] for p in opened] == [  # type: ignore[index]
        "finance.month_outlook",
        "finance.transactions",
    ]
    assert opened[0]["params"] == {"month": "2026-10"}  # type: ignore[index]


async def test_the_stream_sends_no_panel_when_panels_are_off(uow: UowFactory) -> None:
    owner = await person(uow)
    await japan(uow, owner)
    frames = await streamed(
        uow, owner, [call("trip_status", trip="japan"), say("Japan is on track.")], panels=False
    )
    assert [event for event, _ in frames] == ["step", "step", "replies"]


async def test_the_stream_sends_no_panel_for_a_tool_that_failed(uow: UowFactory) -> None:
    owner = await person(uow)
    frames = await streamed(
        uow, owner, [call("trip_status", trip="Atlantis"), say("No such trip.")], panels=True
    )
    assert [event for event, _ in frames] == ["step", "step", "replies"]
