"""People the user already knows: the list ``known_people`` makes, and the chat tools that
ask instead of making a second person for a near miss ("Anne" when there is an "Ann").
Made-up names and amounts only."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from nexus.agent.tools import ToolContext, build_tools
from nexus.application import split_habits as habit_cases
from nexus.application import trip_split
from nexus.application import trips as trip_cases
from nexus.application.people import MAX_KNOWN, known_people
from nexus.application.splits import list_open_ious, split_bill
from nexus.application.transactions import NewTransaction, log_transaction
from nexus.application.users import get_user
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, ShareRequest, Transaction, UserId
from nexus.domain.money import Money
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only, tool_results
from tests.integration.test_split_habits import HALF, run
from tests.integration.test_trips import draft, sgd

pytestmark = pytest.mark.integration

ASK = "would be a new person; the user already knows"


async def bill(uow: UowFactory, user: UserId, amount: str = "60") -> Transaction:
    return await log_transaction(
        uow(),
        user,
        NewTransaction(Direction.OUT, Money.of(amount, "SGD"), NOW, counterparty="Dinner"),
    )


async def owing(uow: UowFactory, user: UserId) -> dict[str, Decimal]:
    ious = await list_open_ious(uow(), user)
    return {i.split.participant_name: i.outstanding.amount for i in ious}


async def knows_ann(uow: UowFactory, user: UserId) -> None:
    """Ann owes 30 for an earlier dinner."""
    await split_bill(uow(), user, (await bill(uow, user)).id, [ShareRequest("Ann")])


# --- known_people ---------------------------------------------------------------------------


async def test_known_people_come_from_splits_habits_trips_and_payments(
    uow: UowFactory, alice: UserId
) -> None:
    assert await known_people(uow(), alice) == []
    user = await get_user(uow(), alice)
    await knows_ann(uow, alice)
    await habit_cases.set_habit(uow(), alice, "Ben", None, HALF, now=NOW)
    trip = await trip_cases.create_trip(uow(), user, draft(companions=["Cleo", "Dev"]), now=NOW)
    await trip_split.add_paid_by_other(
        uow(), user, trip.id, person="Dev", amount=sgd("50"), note=None,
        paid_on=date(2027, 1, 11), split_with=None, now=NOW,
    )  # fmt: skip
    # Dev now only appears as someone who paid.
    await trip_cases.update_trip(uow(), user, trip.id, draft(companions=["Cleo"]), now=NOW)

    assert sorted(await known_people(uow(), alice)) == ["Ann", "Ben", "Cleo", "Dev"]


async def test_known_people_are_newest_first_and_each_listed_once(
    uow: UowFactory, alice: UserId
) -> None:
    for n, name in enumerate(["Ben", "Cy", "ann", "Dee"]):
        await habit_cases.set_habit(uow(), alice, name, None, HALF, now=NOW + timedelta(hours=n))
    # Ann again, in another case, on another category, and most recently.
    await habit_cases.set_habit(uow(), alice, "Ann", "Groceries", HALF, now=NOW + timedelta(days=1))
    assert await known_people(uow(), alice) == ["Ann", "Dee", "Cy", "Ben"]


async def test_known_people_are_capped(uow: UowFactory, alice: UserId) -> None:
    for n in range(MAX_KNOWN + 5):
        await habit_cases.set_habit(
            uow(), alice, f"Person{'x' * n}", None, HALF, now=NOW + timedelta(minutes=n)
        )
    names = await known_people(uow(), alice)
    assert len(names) == MAX_KNOWN == 30
    assert names[0] == f"Person{'x' * (MAX_KNOWN + 4)}"  # the newest


async def test_known_people_belong_to_their_user(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await knows_ann(uow, alice)
    await habit_cases.set_habit(uow(), bob, "Zoe", None, HALF, now=NOW)
    bobs = await get_user(uow(), bob)
    await trip_cases.create_trip(uow(), bobs, draft(companions=["Yan"]), now=NOW)

    assert await known_people(uow(), alice) == ["Ann"]
    assert sorted(await known_people(uow(), bob)) == ["Yan", "Zoe"]


# --- split_bill -----------------------------------------------------------------------------


async def test_a_near_miss_is_asked_about_not_split(uow: UowFactory, alice: UserId) -> None:
    await knows_ann(uow, alice)
    dinner = await bill(uow, alice, "90")
    model = scripted(
        call("split_bill", transaction_id=str(dinner.id), participants=[{"name": "Anne"}]),
        say("Do you mean Ann?"),
    )
    reply = only(await build(uow, model).handle_text(alice, "split dinner with anne", "tg:1:1"))

    # No confirmation card was shown for the near duplicate: the model just asks.
    assert (reply.text, reply.buttons) == ("Do you mean Ann?", [])
    [error] = tool_results(model)
    assert error == (
        "Error: Anne would be a new person; the user already knows Ann. Ask the user whether "
        "they mean Ann, unless they said Anne is someone new (then call again with "
        "new_person=true)."
    )
    assert await owing(uow, alice) == {"Ann": Decimal("30")}  # nothing written


async def test_new_person_true_makes_the_new_person(uow: UowFactory, alice: UserId) -> None:
    await knows_ann(uow, alice)
    dinner = await bill(uow, alice, "90")
    model = scripted(
        call(
            "split_bill",
            transaction_id=str(dinner.id),
            participants=[{"name": "Anne"}],
            new_person=True,
        ),
        say("Split with Anne."),
    )
    agent = build(uow, model)
    reply = only(await agent.handle_text(alice, "anne is a new friend, split dinner", "tg:1:1"))
    assert "Anne owes 45.00 SGD" in reply.text  # the confirmation card
    await agent.resolve(alice, reply.buttons[0][0].data.split(":")[1], True)
    assert await owing(uow, alice) == {"Ann": Decimal("30"), "Anne": Decimal("45")}


async def test_known_and_clearly_new_names_go_through(uow: UowFactory, alice: UserId) -> None:
    await knows_ann(uow, alice)
    dinner = await bill(uow, alice, "90")
    for name in ("ann", "Zed"):  # the same person in other case; someone nowhere near
        args = {"transaction_id": str(dinner.id), "participants": [{"name": name}]}
        assert (await run(uow, alice, "split_bill", **args)).startswith("Split recorded")
    assert sorted(await owing(uow, alice)) == ["Ann", "Zed"]


async def test_the_confirmation_step_asks_too(uow: UowFactory, alice: UserId) -> None:
    await knows_ann(uow, alice)
    dinner = await bill(uow, alice, "90")
    spec = build_tools(lambda _: "")["split_bill"]
    ctx = ToolContext(await get_user(uow(), alice), uow, NOW)
    args = {"transaction_id": str(dinner.id), "participants": [{"name": "Anne"}]}
    assert spec.confirm is not None
    with pytest.raises(InvalidInput, match=ASK):
        await spec.confirm(ctx, spec.parse(args))
    assert "Zed owes" in await spec.confirm(
        ctx, spec.parse({**args, "participants": [{"name": "Zed"}]})
    )
    assert "Anne owes" in await spec.confirm(ctx, spec.parse({**args, "new_person": True}))


# --- the other tools that name a person -----------------------------------------------------


async def test_set_split_habit_asks_about_a_near_miss(uow: UowFactory, alice: UserId) -> None:
    await habit_cases.set_habit(uow(), alice, "Sarah", None, HALF)

    said = await run(uow, alice, "set_split_habit", person="Sara")
    assert said.startswith("Error: Sara " + ASK + " Sarah.")
    assert [h.person for h in await habit_cases.list_habits(uow(), alice)] == ["Sarah"]

    # A new person on purpose, the same person in another case, and someone else entirely.
    assert "Saved" in await run(uow, alice, "set_split_habit", person="Sara", new_person=True)
    assert "Saved" in await run(uow, alice, "set_split_habit", person="SARAH", share="0.4")
    assert "Saved" in await run(uow, alice, "set_split_habit", person="Zed")
    assert sorted(h.person for h in await habit_cases.list_habits(uow(), alice)) == [
        "SARAH", "Sara", "Zed",
    ]  # fmt: skip


async def test_a_trips_companions_are_checked_too(uow: UowFactory, alice: UserId) -> None:
    await knows_ann(uow, alice)
    trip = {
        "destination": "Tokyo",
        "start": "2027-01-10",
        "end": "2027-01-19",
        "currency": "JPY",
    }
    said = await run(uow, alice, "create_trip", **trip, companions=["Anne", "Zed"])
    assert said.startswith("Error: Anne " + ASK + " Ann.")
    assert "Trip saved" in await run(uow, alice, "create_trip", **trip, companions=["Ann", "Zed"])

    said = await run(uow, alice, "update_trip", companions=["Ann", "Zed", "Anne"])
    assert said.startswith("Error: Anne " + ASK + " Ann.")
    done = await run(uow, alice, "update_trip", companions=["Ann", "Zed", "Anne"], new_person=True)
    assert "Trip updated" in done and "Anne" in done


def test_every_tool_that_can_make_a_person_takes_new_person() -> None:
    tools = build_tools(lambda _: "")
    for name in ("split_bill", "set_split_habit", "create_trip", "update_trip"):
        field = tools[name].args.model_fields["new_person"]
        assert field.default is False, name
        assert field.description == "True only when the user said this is a different, new person"
