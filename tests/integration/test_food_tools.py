"""Prime's food tools: logging by chat behind a confirm card, and the day's log for the model.
Every name and figure is made up. Figures in a tool's text come from the application layer."""

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from nexus.agent.tools import READ_ONLY, LogFoodArgs, ToolContext, build_tools, run_tool
from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application import health_consent as consent_cases
from nexus.application import nutrition as nutrition_cases
from nexus.application.users import get_user
from nexus.domain.health import ActivityLevel, ConsentScope, SampleKind, Sex
from nexus.domain.ledger import UserId
from nexus.domain.nutrition import EntrySource, MealSlot
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_nutrition import item, stocked

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def foods(uow: UowFactory) -> None:
    await stocked(uow)


async def run(uow: UowFactory, user: UserId, tool: str, **args: Any) -> tuple[str, str | None]:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW)
    result = await run_tool(build_tools(lambda _: "")[tool], ctx, args)
    return result.text, result.error


async def agree(uow: UowFactory, user: UserId, *, ai: bool = True) -> None:
    await gym_cases.give_consent(uow(), user, now=NOW)
    if ai:
        await consent_cases.grant(uow(), user, ConsentScope.AI_PROCESSING, now=NOW)


PLATE = {"food": "banquet", "portion": "1 plate"}  # 400 kcal: see test_nutrition.FEAST


async def test_without_consent_log_food_says_how_to_turn_health_on(
    uow: UowFactory, alice: UserId
) -> None:
    text, error = await run(uow, alice, "log_food", foods=[PLATE], meal="lunch")
    assert error == "ConsentRequired"
    assert text.startswith("Error: Health is off") and "Health section of the app" in text
    assert await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW) == []


async def test_food_today_needs_ai_processing(uow: UowFactory, alice: UserId) -> None:
    text, error = await run(uow, alice, "food_today")
    assert error == "ConsentRequired" and "AI access to health data is off" in text
    await agree(uow, alice, ai=False)
    await nutrition_cases.log_meal(
        uow(), alice, [item("custom:feast", "400")], MealSlot.LUNCH, None, EntrySource.CHAT, now=NOW
    )
    text, error = await run(uow, alice, "food_today")
    assert error == "ConsentRequired" and "Test Feast" not in text and "400" not in text
    await consent_cases.grant(uow(), alice, ConsentScope.AI_PROCESSING, now=NOW)
    text, error = await run(uow, alice, "food_today")
    assert error is None and "Test Feast" in text and "400 kcal" in text


async def test_a_chat_log_asks_first_then_saves_with_figures_from_the_database(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    model = scripted(call("log_food", foods=[PLATE], meal="lunch"), say("Logged."))
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "had the banquet for lunch", "m1"))
    assert ask.text.startswith("Log lunch: banquet (1 plate, about ") and "kcal" in ask.text
    assert await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW) == []
    done = only(await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True))
    assert "Logged." in done.text
    (meal,) = await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW)
    assert meal.meal is MealSlot.LUNCH and meal.source is EntrySource.CHAT
    assert str(meal.totals.point.kcal) == "400.000"
    assert (await get_user(uow(), alice)).show_health is True


async def test_the_tool_result_reports_what_was_logged(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_food", foods=[PLATE], meal="snack")
    assert error is None and text.startswith("Logged snack: banquet (1 plate, about ")
    assert text.endswith(".")


async def test_an_earlier_day_and_the_default_meal_from_the_time_of_day(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await run(uow, alice, "log_food", foods=[PLATE], when="yesterday")
    yesterday = NOW.date() - timedelta(days=1)
    (meal,) = await nutrition_cases.meals(uow(), alice, day=yesterday, now=NOW)
    assert meal.meal is MealSlot.LUNCH  # logged at noon local time


async def test_a_dish_not_in_the_database_asks_for_its_parts(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_food", foods=[{"food": "zzzz laksa"}], meal="lunch")
    assert error == "NeedsAnswer" and text.startswith("Error: no food matching")
    assert "Singapore database" in text and "Never estimate calories" in text
    assert await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW) == []


async def test_a_missing_amount_is_asked_for(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_food", foods=[{"food": "banquet"}], meal="lunch")
    assert error == "NeedsAnswer" and "How much of Test Feast" in text


async def test_numbers_free_mode_has_no_numbers_in_confirm_log_or_day(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await health_cases.save_profile(uow(), alice, numbers_free=True, now=NOW)
    model = scripted(call("log_food", foods=[PLATE], meal="lunch"), say("Logged."))
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "had the banquet for lunch", "m1"))
    assert ask.text == "Log lunch: banquet (1 plate)?"
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    text, _ = await run(uow, alice, "food_today")
    assert "banquet (1 plate)" in text and "kcal" not in text and "protein" not in text


async def test_the_model_cannot_set_the_photo_source(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    model = scripted(say("ok"))
    agent = build(uow, model)
    await agent.handle_text(alice, "hello", "m1")
    offered = set().union(*model.bound)
    assert "log_photo_meal" not in offered
    assert "from_photo" not in json.dumps(LogFoodArgs.model_json_schema())
    assert build_tools(lambda _: "")["log_photo_meal"].exposed is False


async def test_a_logged_meal_keeps_the_users_word_and_the_usda_id(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    foods = [{"food": "rice", "grams": "150"}, {"food": "chicken breast", "grams": "150"}]
    text, error = await run(uow, alice, "log_food", foods=foods, meal="lunch")
    assert error is None and text.startswith("Logged lunch: rice (150 g, about ")
    assert "chicken breast (150 g, about " in text
    (entry,) = await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW)
    assert [(i.name, i.food_id) for i in entry.items] == [
        ("rice", "usda:168878"),
        ("chicken breast", "usda:171477"),
    ]
    day, _ = await run(uow, alice, "food_today")
    assert "rice (150 g)" in day and "chicken breast (150 g)" in day
    by_id, _ = await run(uow, alice, "log_food", foods=[{"food": "usda:168878", "grams": "100"}])
    assert "rice, white, long-grain" in by_id  # an id has no words of the user's: the USDA name


async def profiled(uow: UowFactory, user: UserId, **fields: Any) -> None:
    """A steady 80 kg for two weeks and a complete profile (a 36-year-old man, 180 cm)."""
    for days_ago in range(14, 0, -1):
        await health_cases.log_sample(
            uow(), user, SampleKind.WEIGHT, Decimal(80),
            start_at=NOW - timedelta(days=days_ago), now=NOW,
        )  # fmt: skip
    base: dict[str, Any] = {
        "sex_for_equations": Sex.MALE,
        "birth_year": NOW.year - 36,
        "height_cm": Decimal(180),
        "activity_level": ActivityLevel.MODERATE,
    }
    await health_cases.save_profile(uow(), user, now=NOW, **{**base, **fields})


async def test_energy_estimate_needs_ai_processing(uow: UowFactory, alice: UserId) -> None:
    text, error = await run(uow, alice, "energy_estimate")
    assert error == "ConsentRequired" and "AI access to health data is off" in text
    assert "energy_estimate" in READ_ONLY


async def test_energy_estimate_asks_for_the_missing_inputs(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "energy_estimate")
    assert error == "NeedsProfile" and text.startswith("Error:")
    for needed in ("height", "birth year", "activity level", "Health profile"):
        assert needed in text
    assert "sex" not in text  # unspecified uses the mean of the two equations
    await health_cases.save_profile(
        uow(), alice, sex_for_equations=Sex.FEMALE, birth_year=NOW.year - 30, now=NOW
    )
    text, _ = await run(uow, alice, "energy_estimate")
    assert text.startswith("Error:") and "height" in text and "birth year" not in text
    assert "sex" not in text


async def test_energy_estimate_needs_a_weigh_in(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    await health_cases.save_profile(
        uow(), alice, sex_for_equations=Sex.MALE, birth_year=NOW.year - 36,
        height_cm=Decimal(180), activity_level=ActivityLevel.MODERATE, now=NOW,
    )  # fmt: skip
    text, error = await run(uow, alice, "energy_estimate")
    assert error == "NeedsWeighIn" and text.startswith("Error:") and "weigh-in" in text


async def test_energy_estimate_gives_a_range_its_provenance_and_targets(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await profiled(uow, alice)
    text, error = await run(uow, alice, "energy_estimate")
    assert error is None
    # 1750 x 1.55 = 2713 from the profile, 15% either side: the same figures as the web read.
    assert "estimated from your profile" in text
    assert "about 2306-3120 kcal" in text and "point 2713 kcal" in text
    assert "Today's targets: 2713 kcal" in text and "128 g protein" in text
    assert "switched off" not in text


async def test_energy_estimate_in_numbers_free_mode_is_words_only(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await profiled(uow, alice, numbers_free=True)
    text, error = await run(uow, alice, "energy_estimate")
    assert error is None and "Numbers-free mode" in text and "steady" in text
    assert "switched off" in text  # numbers-free suspends calorie targets too
    assert "kcal" not in text and "2713" not in text and "targets:" not in text


async def test_energy_estimate_when_suspended_has_no_targets_and_shows_signposts(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await profiled(uow, alice, ed_history=True, numbers_free=False)
    text, error = await run(uow, alice, "energy_estimate")
    assert error is None and "Today's targets" not in text
    assert "switched off" in text and "Samaritans of Singapore" in text
    assert "SGH Eating Disorders Programme" in text
    assert "estimated from your profile" in text  # the estimate is still a range, not a target
