"""Prime fills things in: a weight or a profile said in passing is saved at once, with its own
Undo, and a screen is brought up by name. Every name and figure is made up."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.agent.view_links import VIEWS
from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application.users import get_user
from nexus.domain.health import Goal, SampleKind
from nexus.domain.ledger import UserId
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration

ORIGIN = "https://app.test"


async def run(
    uow: UowFactory, user: UserId, tool: str, origin: str | None = ORIGIN, **args: Any
) -> Any:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW, origin=origin)
    return await run_tool(build_tools(lambda _: "")[tool], ctx, args)


async def agree(uow: UowFactory, user: UserId) -> None:
    await gym_cases.give_consent(uow(), user, now=NOW)


async def weights(uow: UowFactory, user: UserId) -> list[Decimal]:
    found = await health_cases.samples(uow(), user, SampleKind.WEIGHT, now=NOW)
    return [s.value for s in found]


async def weigh_in_going_down(uow: UowFactory, user: UserId) -> None:
    """Four weigh-ins in the last two weeks, going down: enough for a trend."""
    for days, kg in ((12, "85.0"), (9, "84.4"), (6, "83.8"), (3, "83.2")):
        await health_cases.log_sample(
            uow(),
            user,
            SampleKind.WEIGHT,
            Decimal(kg),
            start_at=NOW - timedelta(days=days),
            now=NOW,
        )


# --- log_weight -------------------------------------------------------------------------------


async def test_log_weight_without_consent_offers_the_turn_on_button(
    uow: UowFactory, alice: UserId
) -> None:
    result = await run(uow, alice, "log_weight", value="82")
    assert result.error == "ConsentRequired" and result.text.startswith("Error: Health is off")
    assert result.buttons == [[("Turn on Health", "health:on")]]
    assert await weights(uow, alice) == []


async def test_log_weight_logs_at_once_and_says_the_trend_from_code(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await weigh_in_going_down(uow, alice)
    result = await run(uow, alice, "log_weight", value="82.4")
    assert result.wrote and result.own_undo and not result.error
    assert result.text.startswith("Logged 82.4 kg. Your trend is slowly down, about ")
    assert result.text.endswith(" kg a week.")
    assert Decimal("82.4") in await weights(uow, alice)
    (sample,) = [
        s
        for s in await health_cases.samples(uow(), alice, SampleKind.WEIGHT, now=NOW)
        if s.value == Decimal("82.4")
    ]
    assert result.buttons == [
        [("Undo", f"weight:undo:{sample.id}"), ("See trend", f"url:{ORIGIN}/health")]
    ]
    assert (await get_user(uow(), alice)).show_health is True


async def test_log_weight_without_an_origin_has_only_undo_and_takes_pounds(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    result = await run(uow, alice, "log_weight", origin=None, value="180", unit="lb")
    assert result.text.startswith("Logged 180 lb.")
    assert "not enough" in result.text.lower() or "aren't enough" in result.text
    assert [label for row in result.buttons for label, _ in row] == ["Undo"]


async def test_log_weight_checks_the_bounds(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    result = await run(uow, alice, "log_weight", value="5")
    assert result.error and result.text.startswith("Error:")
    assert await weights(uow, alice) == []
    future = await run(uow, alice, "log_weight", value="80", when="2030-01-01")
    assert future.error and await weights(uow, alice) == []


async def test_numbers_free_log_weight_echoes_no_number(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    await health_cases.save_profile(uow(), alice, numbers_free=True, now=NOW)
    await weigh_in_going_down(uow, alice)
    result = await run(uow, alice, "log_weight", value="82.4")
    assert result.text == "Logged. Your trend is slowly down."
    assert not any(ch.isdigit() for ch in result.text)
    assert Decimal("82.4") in await weights(uow, alice)  # still stored


async def test_weight_undo_deletes_only_that_sample(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    await health_cases.log_sample(
        uow(), alice, SampleKind.WEIGHT, Decimal("83"), start_at=NOW - timedelta(days=3), now=NOW
    )
    model = scripted(call("log_weight", value="82.4"), say("Logged."))
    agent = build(uow, model)
    done = only(await agent.handle_text(alice, "I weigh 82.4 today", "m1"))
    data = [b.data for row in done.buttons for b in row]
    assert len(data) == 1 and data[0].startswith("weight:undo:")  # its own, not the shared Undo
    removed = only(await agent.press(alice, data[0]))
    assert removed.text == "Removed."
    assert await weights(uow, alice) == [Decimal("83.000")]
    again = only(await agent.press(alice, data[0]))
    assert again.text == "That weigh-in is already gone."
    other = only(await agent.press(alice, f"weight:undo:{uuid4()}"))
    assert other.text == "That weigh-in is already gone."
    assert only(await agent.press(alice, "weight:undo:nope")).text == "I don't know that button."


# --- update_health_profile -------------------------------------------------------------------


async def test_profile_update_without_consent_offers_the_turn_on_button(
    uow: UowFactory, alice: UserId
) -> None:
    result = await run(uow, alice, "update_health_profile", height_cm="180")
    assert result.error == "ConsentRequired" and result.buttons == [
        [("Turn on Health", "health:on")]
    ]
    assert await health_cases.profile(uow(), alice, now=NOW) is None


async def test_profile_update_saves_at_once_and_undo_restores_the_old_profile(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await health_cases.save_profile(
        uow(), alice, height_cm=Decimal("170"), birth_year=1985, now=NOW
    )
    model = scripted(
        call("update_health_profile", height_cm="180", birth_year=1990),
        say("Saved."),
    )
    agent = build(uow, model)
    done = only(await agent.handle_text(alice, "I'm 180 cm and born in 1990", "m1"))
    saved = await health_cases.profile(uow(), alice, now=NOW)
    assert saved and saved.height_cm == Decimal("180.0") and saved.birth_year == 1990
    data = [b.data for row in done.buttons for b in row]
    assert len(data) == 1 and data[0].startswith("profile:undo:")
    restored = only(await agent.press(alice, data[0]))
    assert restored.text == "Put your profile back."
    back = await health_cases.profile(uow(), alice, now=NOW)
    assert back and back.height_cm == Decimal("170.0") and back.birth_year == 1985
    again = only(await agent.press(alice, data[0]))  # used up
    assert "too old" in again.text
    assert "too old" in only(await agent.press(alice, "profile:undo:nope")).text


async def test_a_partial_update_keeps_the_rest_and_undo_of_a_first_profile_removes_it(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    first = await run(uow, alice, "update_health_profile", height_cm="172")
    assert first.text == "Saved height 172 cm." and first.own_undo
    second = await run(uow, alice, "update_health_profile", activity_level="light")
    assert second.text == "Saved activity level light."
    now_saved = await health_cases.profile(uow(), alice, now=NOW)
    assert now_saved and now_saved.height_cm == Decimal("172.0")
    assert now_saved.activity_level is not None and now_saved.activity_level.value == "light"
    # Undo the first change: there was no profile before it, so none is left.
    token = first.buttons[0][0][1].removeprefix("profile:undo:")
    await health_cases.undo_profile(uow(), alice, token, now=NOW)
    assert await health_cases.profile(uow(), alice, now=NOW) is None


async def test_an_expired_profile_undo_does_nothing(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    first = await run(uow, alice, "update_health_profile", height_cm="172")
    token = first.buttons[0][0][1].removeprefix("profile:undo:")
    assert not await health_cases.undo_profile(uow(), alice, token, now=NOW + timedelta(minutes=31))
    assert await health_cases.profile(uow(), alice, now=NOW) is not None


async def test_one_users_undo_token_is_no_use_to_another(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await agree(uow, alice)
    await agree(uow, bob)
    first = await run(uow, alice, "update_health_profile", height_cm="172")
    token = first.buttons[0][0][1].removeprefix("profile:undo:")
    assert not await health_cases.undo_profile(uow(), bob, token, now=NOW)
    assert await health_cases.profile(uow(), alice, now=NOW) is not None


async def test_an_under_18_birth_year_blocks_a_loss_goal_and_says_why(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    result = await run(uow, alice, "update_health_profile", birth_year=2010, goal="lose")
    assert "weight-loss goal" in result.text and "under 18" in result.text
    assert "goal: lose" not in result.text
    saved = await health_cases.profile(uow(), alice, now=NOW)
    assert saved and saved.goal is Goal.MAINTAIN and saved.birth_year == 2010
    # A birth year that makes an existing loss goal unsafe holds it back too.
    other = await run(uow, alice, "update_health_profile", birth_year=1990, goal="lose")
    assert "Add your height and a weigh-in" in other.text  # the BMI is still unknown


async def test_a_loss_goal_is_saved_when_the_gates_allow_it(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    await health_cases.log_sample(uow(), alice, SampleKind.WEIGHT, Decimal("82"), now=NOW)
    result = await run(
        uow, alice, "update_health_profile", birth_year=1990, height_cm="180", goal="lose"
    )
    assert "goal: lose weight" in result.text and "haven't set" not in result.text
    saved = await health_cases.profile(uow(), alice, now=NOW)
    assert saved and saved.goal is Goal.LOSE


async def test_an_eating_history_hides_numbers_and_blocks_a_loss_goal(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await health_cases.log_sample(uow(), alice, SampleKind.WEIGHT, Decimal("82"), now=NOW)
    result = await run(
        uow,
        alice,
        "update_health_profile",
        birth_year=1990,
        height_cm="180",
        goal="lose",
        ed_history=True,
    )
    saved = await health_cases.profile(uow(), alice, now=NOW)
    assert saved and saved.goal is Goal.MAINTAIN and saved.numbers_free and saved.ed_history
    assert "eating-disorder history" in result.text
    assert not any(ch.isdigit() for ch in result.text)  # numbers-free: none echoed


async def test_nothing_to_save_is_an_error(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    result = await run(uow, alice, "update_health_profile")
    assert result.error and result.text.startswith("Error:")


# --- show -------------------------------------------------------------------------------------


async def test_show_returns_one_line_and_the_right_link_for_every_view(
    uow: UowFactory, alice: UserId
) -> None:
    expected = {
        "health.today": "/health",
        "health.weight_trend": "/health",
        "health.workout": "/health/gym",
        "health.records": "/health/gym/history",
        "finance.month_outlook": "/accounting",
        "finance.budgets": "/accounting/budgets",
        "travel.trips": "/travel",
        "invest.portfolio": "/investment",
    }
    assert set(VIEWS) == set(expected)
    for name, path in expected.items():
        result = await run(uow, alice, "show", view=name)  # no Health consent needed: no data
        assert not result.error and "\n" not in result.text and not result.wrote
        assert result.buttons == [[(VIEWS[name].button, f"url:{ORIGIN}{path}")]]
    assert (await run(uow, alice, "show", view="health.weight_trend")).text == (
        "Here's your weight trend."
    )
    assert (await run(uow, alice, "show", view="nope")).error == "InvalidInput"


async def test_show_without_an_origin_says_where_it_is_in_the_app(
    uow: UowFactory, alice: UserId
) -> None:
    result = await run(uow, alice, "show", origin=None, view="finance.budgets")
    assert result.buttons is None and "Finance" in result.text


async def test_show_reads_nothing_out(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    await health_cases.log_sample(uow(), alice, SampleKind.WEIGHT, Decimal("82.4"), now=NOW)
    result = await run(uow, alice, "show", view="health.weight_trend")
    assert "82" not in result.text


# --- "Open ..." on the Health reads ------------------------------------------------------------


async def test_health_reads_carry_an_open_button_when_the_origin_is_known(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.application import health_consent as consent_cases
    from nexus.domain.health import ConsentScope

    await agree(uow, alice)
    await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    food = await run(uow, alice, "food_today")
    assert food.buttons == [[("Open Today", f"url:{ORIGIN}/health")]]
    records = await run(uow, alice, "personal_records")
    assert records.buttons == [[("Open records", f"url:{ORIGIN}/health/gym/history")]]
    workout = await run(uow, alice, "todays_workout")
    assert workout.buttons == [[("Open workout", f"url:{ORIGIN}/health/gym")]]
    assert (await run(uow, alice, "food_today", origin=None)).buttons is None
