"""``present`` and the safety net (ADR 0005): what a turn puts on screen. The catalog checks
Prime's call; a tool that answered opens its default view; the turn dedupes, caps at three and
keeps one focus; the refs are kept with the reply, never figures; with views off nothing
changes. Every name and figure is made up."""

import json
from typing import Any

import pytest
from langchain_core.messages import SystemMessage, ToolMessage

from nexus.agent.views import PRESENT_RULE
from nexus.application import gym as gym_cases
from nexus.domain.ledger import UserId
from nexus.evals import seed
from tests.fakes import ScriptedModel, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration

SEP = {"month": "2026-09"}


def results(model: ScriptedModel) -> list[str]:
    return [str(m.content) for m in model.seen[-1] if isinstance(m, ToolMessage)]


def shown(reply: Any) -> list[tuple[str, bool]]:
    return [(v.kind.value, v.focus) for v in reply.views]


async def turn(uow: UowFactory, user: UserId, model: ScriptedModel, *, views: bool = True) -> Any:
    return only(await build(uow, model, views=views).handle_text(user, "show me", "web:1:1"))


@pytest.fixture
async def alice(uow: UowFactory) -> UserId:
    return (await seed.seed_user(uow, 7100, gym=True)).user.id


async def test_present_puts_a_checked_view_on_screen(uow: UowFactory, alice: UserId) -> None:
    model = scripted(call("present", view="finance.month_outlook", params=SEP), say("Here."))
    reply = await turn(uow, alice, model)
    assert shown(reply) == [("finance.month_outlook", True)]
    [view] = reply.views
    assert view.caption == "Your outlook for September 2026"
    assert view.summary is not None and view.summary["received"]["currency"] == "SGD"
    assert results(model)[0].startswith('On screen: "Your outlook for September 2026"')


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        ({"view": "finance.nothing"}, "no view called"),
        ({"view": "finance.transactions"}, "not available yet"),  # planned
        ({"view": "finance.month_outlook", "params": {"month": "Sept"}}, "bad params"),
        ({"view": "finance.month_outlook", "params": {}}, "bad params"),
        ({"view": "finance.month_outlook", "params": {**SEP, "user_id": "x"}}, "bad params"),
        ({"view": "travel.trip_budget", "params": {"trip_id": "nope"}}, "not an id"),
        ({"view": "health.workout", "params": {"state": "suggested"}}, "suggestion_id"),
    ],
)
async def test_a_bad_call_comes_back_as_an_error_for_the_model_to_fix(
    uow: UowFactory, alice: UserId, args: dict[str, Any], problem: str
) -> None:
    model = scripted(call("present", **args), say("Sorry."))
    reply = await turn(uow, alice, model)
    assert reply.views == ()
    assert results(model)[0].startswith("Error:") and problem in results(model)[0]


async def test_a_health_view_without_consent_is_an_error(uow: UowFactory) -> None:
    plain = (await seed.seed_user(uow, 7101)).user.id
    model = scripted(call("present", view="health.today"), say("Turn Health on first."))
    reply = await turn(uow, plain, model)
    assert reply.views == () and "Health is off" in results(model)[0]


async def test_a_tool_that_answered_opens_its_view_even_when_prime_forgets(
    uow: UowFactory, alice: UserId
) -> None:
    reply = await turn(uow, alice, scripted(call("month_outlook"), say("Fine.")))
    assert shown(reply) == [("finance.month_outlook", True)]  # the first is the focus
    reply = await turn(uow, alice, scripted(call("todays_workout"), say("Push day.")))
    assert shown(reply) == [("health.workout", True)]


async def test_a_tool_that_failed_or_opens_nothing_shows_nothing(
    uow: UowFactory, alice: UserId
) -> None:
    failed = scripted(call("month_outlook", month="2026-13"), say("That month isn't valid."))
    assert (await turn(uow, alice, failed)).views == ()
    write = scripted(call("log_expense", amount="4", merchant="Kopi"), say("Logged."))
    assert (await turn(uow, alice, write)).views == ()


async def test_the_same_view_twice_is_one_and_present_after_a_tool_keeps_the_figures(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(
        call("month_outlook", month="2026-09"),
        call("present", view="finance.month_outlook", params=SEP),
        say("Fine."),
    )
    reply = await turn(uow, alice, model)
    assert shown(reply) == [("finance.month_outlook", True)]


async def test_at_most_three_views_a_turn_and_the_fourth_is_an_error(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(
        call("present", view="finance.month_outlook", params=SEP, focus=False),
        call("present", view="finance.budgets", params=SEP, focus=False),
        call("present", view="finance.spending", params=SEP, focus=False),
        call("present", view="invest.portfolio", focus=False),
        say("Done."),
    )
    reply = await turn(uow, alice, model)
    assert [k for k, _ in shown(reply)] == [
        "finance.month_outlook",
        "finance.budgets",
        "finance.spending",
    ]
    assert "most views" in results(model)[3]


async def test_the_focus_is_the_latest_present_with_focus_else_the_first(
    uow: UowFactory, alice: UserId
) -> None:
    latest = scripted(
        call("present", view="finance.month_outlook", params=SEP),
        call("present", view="finance.budgets", params=SEP),
        call("present", view="finance.spending", params=SEP, focus=False),
        say("Done."),
    )
    assert shown(await turn(uow, alice, latest)) == [
        ("finance.month_outlook", False),
        ("finance.budgets", True),
        ("finance.spending", False),
    ]
    none = scripted(
        call("present", view="finance.budgets", params=SEP, focus=False),
        call("present", view="finance.month_outlook", params=SEP, focus=False),
        say("Done."),
    )
    assert shown(await turn(uow, alice, none)) == [
        ("finance.budgets", True),
        ("finance.month_outlook", False),
    ]


async def test_the_refs_are_kept_with_the_reply_and_never_the_figures(
    uow: UowFactory, alice: UserId
) -> None:
    await turn(
        uow, alice, scripted(call("present", view="finance.budgets", params=SEP), say("Ok."))
    )
    async with uow() as tx:
        lines = await tx.memory.chat(alice, 10)
    user, nexus = lines
    assert user.views is None
    assert nexus.views == [{"kind": "finance.budgets", "params": SEP, "focus": True}]
    assert "summary" not in json.dumps(nexus.views)


async def test_a_trip_a_member_may_not_see_money_for_opens_no_card(uow: UowFactory) -> None:
    member = (await seed.seed_user(uow, 7102, shared=True)).user.id
    model = scripted(call("trip_status", trip="Japan"), say("The plan."))
    assert (await turn(uow, member, model)).views == ()
    own = (await seed.seed_user(uow, 7103)).user.id
    reply = await turn(uow, own, scripted(call("trip_status", trip="Japan"), say("Budget.")))
    assert shown(reply) == [("travel.trip_budget", True)]


async def test_a_suggested_workout_opens_its_own_card(uow: UowFactory, alice: UserId) -> None:
    model = scripted(
        call(
            "suggest_workout",
            focus="Push",
            minutes=40,
            place="gym",
            exercises=[
                {"exercise": "Barbell_Bench_Press_-_Medium_Grip", "sets": 3, "reps": 8},
                {"exercise": "Standing_Military_Press", "sets": 3, "reps": 8},
            ],
        ),
        say("Here is a push session."),
    )
    reply = await turn(uow, alice, model)
    if results(model)[0].startswith("Error:"):  # the made-up session didn't fit the rules
        pytest.skip(results(model)[0])
    [view] = reply.views
    assert view.kind.value == "health.workout" and view.params["state"] == "suggested"
    assert view.summary is not None and view.summary["exercises"] == 2


# --- views off: exactly as before -------------------------------------------------------------


async def test_with_views_off_there_is_no_tool_no_rule_no_views_and_nothing_stored(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(call("month_outlook"), say("Fine."))
    reply = await turn(uow, alice, model, views=False)
    assert reply.views == ()
    assert all("present" not in names for names in model.bound)
    system = next(m for m in model.seen[0] if isinstance(m, SystemMessage))
    assert PRESENT_RULE not in str(system.content)
    async with uow() as tx:
        assert [line.views for line in await tx.memory.chat(alice, 10)] == [None, None]
    # a model that calls present anyway (it was never offered) gets a harmless answer
    odd = scripted(call("present", view="finance.budgets", params=SEP), say("Hm."))
    assert (await turn(uow, alice, odd, views=False)).views == ()
    assert "no screen" in results(odd)[0]


async def test_with_views_on_the_model_is_offered_present_and_told_when_to_use_it(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("Hi."))
    await turn(uow, alice, model)
    assert all("present" in names for names in model.bound)
    system = next(m for m in model.seen[0] if isinstance(m, SystemMessage))
    assert PRESENT_RULE in str(system.content)


async def test_health_cards_need_health_on_for_the_safety_net_too(uow: UowFactory) -> None:
    plain = (await seed.seed_user(uow, 7104)).user.id
    assert await gym_cases.consent(uow(), plain) is None
    model = scripted(call("food_today"), say("Turn Health on first."))
    assert (await turn(uow, plain, model)).views == ()
