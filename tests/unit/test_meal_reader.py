"""Meal photo drafts and routing, no model: what the reader keeps of a reply, which captions
send a photo to the meal reader, and how the user's answer to the question is read."""

import pytest

from nexus.agent.image_look import ImageKind, ImageLook, Route, meal_caption, route
from nexus.agent.meal_photo import food_requests, pending_from, read_answer, slot_in, tool_foods
from nexus.agent.meal_reader import CookingHint, MealDraft

LOOK_MEAL = ImageLook(ImageKind.MEAL, None, "A plate of rice and egg.", "")
LOOK_RECEIPT = ImageLook(ImageKind.RECEIPT, "SGD", "A receipt.", "TOTAL 5.00")
LOOK_OTHER = ImageLook(ImageKind.OTHER, None, "A menu.", "")


def test_a_draft_keeps_items_portions_and_the_question() -> None:
    draft = MealDraft.model_validate(
        {
            "items": [
                {
                    "name": "white rice",
                    "portion_text": "1 bowl",
                    "grams_estimate": 180,
                    "cooking": "none",
                    "confidence": "high",
                },
                {"name": "fried egg", "grams_estimate": "about 50 g", "cooking": "stir-fried"},
            ],
            "question": "Is the egg fried in a lot of oil?",
        }
    )
    assert [i.name for i in draft.items] == ["white rice", "fried egg"]
    assert draft.items[0].grams_estimate == 180 and draft.items[1].grams_estimate == 50
    assert draft.items[1].cooking is CookingHint.STIR_FRIED
    assert draft.question == "Is the egg fried in a lot of oil?"


def test_nutrition_numbers_from_the_model_are_dropped() -> None:
    draft = MealDraft.model_validate(
        {
            "items": [
                {
                    "name": "chicken rice (about 600 kcal)",
                    "portion_text": "1 plate, 25 g protein",
                    "grams_estimate": 400,
                    "kcal": 600,
                    "protein_g": 25,
                    "calories": "600",
                }
            ],
            "question": "Is it roasted? That's roughly 550 calories.",
            "kcal": 900,
        }
    )
    (item,) = draft.items
    assert item.name == "chicken rice" and item.portion_text == "1 plate"
    assert draft.question == "Is it roasted? That's."
    dumped = str(draft.model_dump())
    assert "600" not in dumped and "kcal" not in dumped and "protein_g" not in dumped
    assert "calories" not in dumped.replace("calories?", "")


def test_nonsense_values_fall_back_safely() -> None:
    draft = MealDraft.model_validate(
        {
            "items": [
                {"name": "x", "grams_estimate": 99999, "cooking": "boiled?", "confidence": "?"},
                {"name": "  "},
            ]
        }
    )
    (item,) = draft.items
    assert item.grams_estimate is None and item.cooking is CookingHint.NONE
    assert item.confidence.value == "medium"


@pytest.mark.parametrize(
    "caption", ["my lunch", "just ate this", "dinner tonight", "breakfast", "snack time"]
)
def test_a_caption_naming_a_meal_goes_to_the_meal_reader(caption: str) -> None:
    assert meal_caption(caption)
    assert route(None, caption) is Route.MEAL


@pytest.mark.parametrize(
    "caption", ["lunch receipt", "lunch 12.50", "the bill for dinner", "$8 lunch", "paid for lunch"]
)
def test_a_caption_with_a_price_receipt_or_bill_is_not_a_meal(caption: str) -> None:
    assert not meal_caption(caption)
    assert route(None, caption) is Route.RECEIPT
    assert route(LOOK_RECEIPT, caption) is Route.RECEIPT


def test_without_a_caption_the_look_decides_and_a_meal_class_exists() -> None:
    assert route(LOOK_MEAL, None) is Route.MEAL
    assert route(LOOK_RECEIPT, None) is Route.RECEIPT
    assert route(LOOK_OTHER, None) is Route.CHAT
    assert route(None, None) is Route.RECEIPT  # no look: read as a receipt, as before


def test_a_question_about_a_meal_goes_to_the_chat_agent_and_no_reader_means_no_meals() -> None:
    assert route(LOOK_MEAL, "how healthy is my lunch?") is Route.CHAT
    assert route(LOOK_MEAL, None, meals=False) is Route.CHAT
    assert route(None, "my lunch", meals=False) is Route.RECEIPT


def test_the_meal_a_caption_names() -> None:
    assert slot_in("my lunch") == "lunch" and slot_in("late supper") == "dinner"
    assert slot_in("snack") == "snack" and slot_in("what is this") is None


def pending() -> dict[str, object]:
    draft = MealDraft.model_validate(
        {
            "items": [
                {"name": "noodles", "portion_text": "1 plate", "grams_estimate": 300},
                {"name": "egg", "grams_estimate": 50},
            ],
            "question": "Are the noodles fried?",
        }
    )
    return pending_from(draft, "my lunch")


def test_requests_are_photo_estimates_and_tool_args_carry_ids() -> None:
    p = pending()
    first = food_requests(p)[0]
    assert first.photo and first.estimated and first.grams == 300
    foods = tool_foods(p, ["usda:1", "usda:2"])
    assert foods[0] == {
        "food": "usda:1",
        "shown": "noodles",
        "portion": "1 plate",
        "grams": "300",
        "estimated": True,
        "cooking": None,
    }


def test_the_answer_sets_the_cooking_of_the_main_item_or_proceeds_or_cancels() -> None:
    verdict, new = read_answer(pending(), "yes, stir fried")
    assert verdict == "go" and new["items"][0]["cooking"] == "stir_fried"
    assert new["items"][1]["cooking"] == "none" and new["question"] is None
    assert read_answer(pending(), "not fried, it's steamed")[1]["items"][0]["cooking"] == "none"
    assert read_answer(pending(), "ok")[0] == "go"
    assert read_answer(pending(), "cancel")[0] == "cancel"
    assert read_answer(pending(), "what is the weather")[0] == "unrelated"
    assert read_answer(pending(), "half")[1]["items"][0]["grams"] == 150
