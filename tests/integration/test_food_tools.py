"""Prime's food tools: logging by chat straight away (with Undo), and the day's log for the model.
Every name and figure is made up. Figures in a tool's text come from the application layer."""

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage

from nexus.agent.tools import READ_ONLY, LogFoodArgs, ToolContext, build_tools, run_tool
from nexus.application import gym as gym_cases
from nexus.application import health as health_cases
from nexus.application import health_consent as consent_cases
from nexus.application import nutrition as nutrition_cases
from nexus.application.users import get_user
from nexus.domain.health import ActivityLevel, ConsentScope, SampleKind, Sex
from nexus.domain.ledger import UserId
from nexus.domain.nutrition import EntrySource, EstimateKind, MealSlot
from tests.fakes import NOW, call, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, ledger, only
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


async def run_ctx(
    uow: UowFactory, user: UserId, tool: str, origin: str | None = None, **args: Any
) -> Any:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW, origin=origin)
    return await run_tool(build_tools(lambda _: "")[tool], ctx, args)


async def test_a_chat_log_is_immediate_with_figures_from_the_database_and_buttons(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    model = scripted(call("log_food", foods=[PLATE], meal="lunch"), say("Logged."))
    agent = build(uow, model)
    done = only(await agent.handle_text(alice, "had the banquet for lunch", "m1"))
    (meal,) = await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW)
    assert meal.meal is MealSlot.LUNCH and meal.source is EntrySource.CHAT
    assert str(meal.totals.point.kcal) == "400.000"
    assert (await get_user(uow(), alice)).show_health is True
    # Its own Undo, not the shared one (which would undo money).
    assert [b.data for row in done.buttons for b in row] == [f"meal:undo:{meal.id}"]
    assert "A rough guide" in tool_text(model)


def tool_text(model: Any) -> str:
    return " ".join(str(m.content) for m in model.seen[-1] if isinstance(m, ToolMessage))


async def test_the_meal_buttons_are_undo_and_an_edit_link_when_the_origin_is_known(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    result = await run_ctx(uow, alice, "log_food", "https://app.test/", foods=[PLATE])
    (meal,) = await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW)
    assert result.own_undo and result.buttons == [
        [
            ("Undo", f"meal:undo:{meal.id}"),
            ("Edit", f"url:https://app.test/health/food?meal={meal.id}"),
        ]
    ]
    bare = await run_ctx(uow, alice, "log_food", foods=[PLATE])
    assert [label for label, _ in bare.buttons[0]] == ["Undo"]


async def test_meal_undo_removes_only_that_meal_and_leaves_the_money_alone(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    model = scripted(
        call("log_expense", amount="5.50", merchant="Starbucks", category="Dining Out"),
        say("Logged 5.50."),
        call("log_food", foods=[PLATE], meal="lunch"),
        say("Logged."),
    )
    agent = build(uow, model)
    await agent.handle_text(alice, "starbucks 5.50", "m1")
    done = only(await agent.handle_text(alice, "had the banquet", "m2"))
    data = done.buttons[0][0].data
    assert data.startswith("meal:undo:")
    removed = only(await agent.press(alice, data))
    assert removed.text == "Removed." and not removed.buttons
    assert await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW) == []
    assert await ledger(uow, alice) == [("out", Decimal("5.5"))]
    again = only(await agent.press(alice, data))
    assert "already gone" in again.text
    other = only(await agent.press(alice, f"meal:undo:{uuid4()}"))
    assert "already gone" in other.text


async def test_a_meal_and_an_expense_in_one_turn_keep_the_shared_undo(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    model = scripted(
        call("log_food", foods=[PLATE], meal="lunch"),
        call("log_expense", amount="5.50", merchant="Starbucks", category="Dining Out"),
        say("Both logged."),
    )
    done = only(await build(uow, model).handle_text(alice, "banquet and a coffee", "m1"))
    data = [b.data for row in done.buttons for b in row]
    assert "act:undo" in data and any(d.startswith("meal:undo:") for d in data)


async def test_undo_last_meal_removes_a_recent_meal_and_says_when_there_is_none(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    text, _ = await run(uow, alice, "undo_last_meal")
    assert "no meal" in text.lower()
    await run(uow, alice, "log_food", foods=[PLATE], meal="lunch")
    model = scripted(call("undo_last_meal"), say("Removed."))
    done = only(await build(uow, model).handle_text(alice, "undo that", "m1"))
    assert "Removed your lunch" in tool_text(model) and not done.buttons
    assert await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW) == []
    # An older meal (logged more than 30 minutes ago) is left alone.
    await nutrition_cases.log_meal(
        uow(),
        alice,
        [item("custom:feast", "400")],
        MealSlot.LUNCH,
        None,
        EntrySource.CHAT,
        now=NOW - timedelta(hours=2),
    )
    text, _ = await run(uow, alice, "undo_last_meal")
    assert "no meal" in text.lower()
    assert len(await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW)) == 1


async def test_the_tool_result_reports_what_was_logged(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_food", foods=[PLATE], meal="snack")
    assert error is None and text.startswith("Logged snack: banquet, about ")
    assert " · ~" in text and text.endswith("A rough guide.")


async def test_an_earlier_day_and_the_default_meal_from_the_time_of_day(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await run(uow, alice, "log_food", foods=[PLATE], when="yesterday")
    yesterday = NOW.date() - timedelta(days=1)
    (meal,) = await nutrition_cases.meals(uow(), alice, day=yesterday, now=NOW)
    assert meal.meal is MealSlot.LUNCH  # logged at noon local time


async def test_a_dish_with_no_match_and_no_estimate_asks_what_it_is(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_food", foods=[{"food": "zzzz laksa"}], meal="lunch")
    assert error == "NeedsAnswer" and text.startswith("Error: no food matching")
    assert "est_kcal" in text
    assert await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW) == []


HAWKER = {
    "food": "zzzz laksa",
    "portion": "1 bowl",
    "est_kcal": 600,
    "est_protein_g": 25,
    "est_carbs_g": 70,
    "est_fat_g": 25,
}


async def test_a_dish_with_no_match_is_logged_from_the_estimate_as_ai_estimate(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_food", foods=[HAWKER], meal="lunch")
    # 600 kcal, plus or minus 40%: 360 to 840.
    assert error is None and "zzzz laksa, about 360\u2013840 kcal" in text
    assert "~25 g protein · 70 g carbs · 25 g fat" in text
    (entry,) = await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW)
    (it,) = entry.items
    assert it.food_id is None and it.source_detail == "ai_estimate"
    assert it.kind is EstimateKind.AI_ESTIMATE and str(it.nutrients.kcal) == "600.000"
    day, _ = await run(uow, alice, "food_today")
    assert "zzzz laksa (1 bowl)" in day


async def test_the_database_wins_over_the_estimate_and_the_best_match_is_taken(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    row = {**PLATE, "est_kcal": 5, "est_protein_g": 0, "est_carbs_g": 1, "est_fat_g": 0}
    await run(uow, alice, "log_food", foods=[row], meal="lunch")
    # "rice" matches several foods: the top-ranked one is used, nothing is asked.
    text, error = await run(uow, alice, "log_food", foods=[{"food": "rice", "grams": "100"}])
    assert error is None and text.startswith("Logged ")
    # Both are at the same moment, so their order isn't fixed: tell them apart by their kcal.
    first, second = sorted(
        await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW),
        key=lambda m: m.totals.point.kcal,
        reverse=True,
    )
    assert str(first.totals.point.kcal) == "400.000" and second.items[0].source_detail == "db"


async def test_a_weak_database_match_loses_to_the_estimate(uow: UowFactory, alice: UserId) -> None:
    """ "chicken rice" once became "Babyfood, dinner, chicken and rice" at 140-270 kcal: a match
    that doesn't name the food outright must not beat the model's estimate of the dish."""
    await agree(uow, alice)
    dish = {
        "food": "chicken rice",
        "portion": "1 plate",
        "est_kcal": 600,
        "est_protein_g": 30,
        "est_carbs_g": 75,
        "est_fat_g": 20,
    }
    text, error = await run(uow, alice, "log_food", foods=[dish], meal="lunch")
    assert error is None and text.startswith("Logged ")
    (meal,) = await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW)
    item = meal.items[0]
    assert item.source_detail == "ai_estimate" and item.food_id is None
    assert "babyfood" not in text.casefold()


@pytest.mark.parametrize(
    "bad",
    [
        {"est_kcal": 0, "est_protein_g": 0, "est_carbs_g": 0, "est_fat_g": 0},
        {"est_kcal": 2600, "est_protein_g": 100, "est_carbs_g": 300, "est_fat_g": 110},
        {"est_kcal": 600, "est_protein_g": -5, "est_carbs_g": 100, "est_fat_g": 25},
        {"est_kcal": 600, "est_protein_g": 5, "est_carbs_g": 5, "est_fat_g": 5},  # adds to 85
        {"est_kcal": 600},  # the macros are missing
    ],
)
async def test_an_estimate_out_of_bounds_is_rejected_and_the_user_is_asked(
    uow: UowFactory, alice: UserId, bad: dict[str, Any]
) -> None:
    await agree(uow, alice)
    row = {"food": "zzzz laksa", "portion": "1 bowl", **bad}
    text, error = await run(uow, alice, "log_food", foods=[row], meal="lunch")
    assert error == "NeedsAnswer" and "no usable estimate" in text
    assert await nutrition_cases.meals(uow(), alice, day=NOW.date(), now=NOW) == []


async def test_a_missing_amount_is_asked_for(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    text, error = await run(uow, alice, "log_food", foods=[{"food": "banquet"}], meal="lunch")
    assert error == "NeedsAnswer" and "How much of Test Feast" in text


async def test_numbers_free_mode_has_no_numbers_in_the_log_or_day(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await health_cases.save_profile(uow(), alice, numbers_free=True, now=NOW)
    text, _ = await run(uow, alice, "log_food", foods=[PLATE], meal="lunch")
    assert text == "Logged lunch: banquet."
    text, _ = await run(uow, alice, "log_food", foods=[HAWKER], meal="lunch")
    assert text == "Logged lunch: zzzz laksa."
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
    assert error is None and text.startswith("Logged lunch:\n- rice, about ")
    assert "\n- chicken breast, about " in text and "\nTotal: about " in text
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
