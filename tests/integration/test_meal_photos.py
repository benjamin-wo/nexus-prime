"""Meal photos: read into foods, portions and rough estimates by a (fake) model, looked up in
the food database in code, and logged straight away with source photo (Undo, no question, no
confirm card). Receipts still route as before. Every food and figure is made up or from the
bundled database."""

import pytest

from nexus.agent.image_look import ImageKind, ImageLook
from nexus.agent.meal_reader import MealDraft
from nexus.agent.receipts import ReceiptDraft
from nexus.application import health as health_cases
from nexus.application import nutrition as nutrition_cases
from nexus.domain.ledger import UserId
from nexus.domain.nutrition import EntrySource, EstimateKind
from tests.fakes import NOW, FakeImageLooker, FakeMeals, FakeReceipts, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_food_tools import agree
from tests.integration.test_nutrition import stocked

pytestmark = pytest.mark.integration

IMG = b"\xff\xd8jpeg"


def meal(**second: object) -> MealDraft:
    return MealDraft.model_validate(
        {
            "items": [
                {"name": "white rice", "portion_text": "1 bowl", "grams_estimate": 150},
                {"name": "egg", "grams_estimate": 50, "kcal": 9999, **second},
            ],
        }
    )


@pytest.fixture(autouse=True)
async def foods(uow: UowFactory) -> None:
    await stocked(uow)


async def meals_today(uow: UowFactory, user: UserId):  # type: ignore[no-untyped-def]
    return await nutrition_cases.meals(uow(), user, day=NOW.date(), now=NOW)


async def test_a_photo_is_logged_in_one_turn_as_photo_with_undo(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    reader = FakeMeals(meal(cooking="fried"))
    agent = build(uow, scripted(), meals=reader)
    done = only(await agent.handle_photo(alice, IMG, "image/jpeg", "my lunch", "p1"))
    assert reader.reads == 1
    assert done.text.startswith("Logged lunch:\n- white rice, about ")
    assert "A rough guide from your photo." in done.text and "9999" not in done.text
    (entry,) = await meals_today(uow, alice)
    assert [b.data for row in done.buttons for b in row] == [f"meal:undo:{entry.id}"]
    assert entry.source is EntrySource.PHOTO and entry.meal.value == "lunch"
    assert {i.kind for i in entry.items} == {EstimateKind.ESTIMATED}
    egg = next(i for i in entry.items if i.food_id == "usda:173424")  # egg -> hard-boiled
    assert egg.cooking is not None and egg.cooking.value == "fried"
    assert egg.grams == 50
    assert egg.name == "egg" and any(i.name == "white rice" for i in entry.items)
    removed = only(await agent.press(alice, done.buttons[0][0].data))
    assert removed.text == "Removed." and await meals_today(uow, alice) == []


async def test_a_hawker_dish_with_no_match_uses_the_readers_estimate(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    draft = MealDraft.model_validate(
        {
            "items": [
                {
                    "name": "zzzz laksa",
                    "portion_text": "1 bowl",
                    "est_kcal": 600,
                    "est_protein_g": 25,
                    "est_carbs_g": 70,
                    "est_fat_g": 25,
                }
            ]
        }
    )
    agent = build(uow, scripted(), meals=FakeMeals(draft))
    done = only(await agent.handle_photo(alice, IMG, "image/jpeg", "dinner", "p1"))
    assert done.text.startswith("Logged dinner: zzzz laksa, about 360\u2013840 kcal")
    assert done.text.endswith("A rough guide from your photo.")
    (entry,) = await meals_today(uow, alice)
    (item,) = entry.items
    assert item.food_id is None and item.source_detail == "ai_estimate"
    assert item.kind is EstimateKind.AI_ESTIMATE


async def test_an_item_with_neither_a_match_nor_a_usable_estimate_is_asked_about_then_logged(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    draft = MealDraft.model_validate(
        {"items": [{"name": "zzzz stew", "grams_estimate": 200, "est_kcal": 99999}]}
    )
    agent = build(uow, scripted(), meals=FakeMeals(draft))
    asked = only(await agent.handle_photo(alice, IMG, "image/jpeg", "my lunch", "p1"))
    assert "couldn't place 'zzzz stew'" in asked.text and not asked.buttons
    assert await meals_today(uow, alice) == []
    done = only(await agent.handle_text(alice, "white rice", "m2"))
    assert done.text.startswith("Logged lunch: white rice, about ")
    (entry,) = await meals_today(uow, alice)
    assert entry.items[0].grams == 200


async def test_numbers_free_mode_logs_a_photo_without_numbers(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    await health_cases.save_profile(uow(), alice, numbers_free=True, now=NOW)
    agent = build(uow, scripted(), meals=FakeMeals(meal()))
    done = only(await agent.handle_photo(alice, IMG, "image/jpeg", "my lunch", "p1"))
    assert done.text == "Logged lunch: white rice, egg."


async def test_without_ai_consent_nothing_is_sent_to_the_reader(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice, ai=False)
    reader = FakeMeals(meal())
    agent = build(uow, scripted(), meals=reader)
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", "my lunch", "p1"))
    assert reply.text.startswith("AI access to health data is off") and not reply.buttons
    assert reader.reads == 0 and await meals_today(uow, alice) == []


async def test_a_look_that_says_meal_routes_a_photo_with_no_caption(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    look = ImageLook(ImageKind.MEAL, None, "Rice and egg.", "")
    reader = FakeMeals(meal())
    agent = build(uow, scripted(), meals=reader, looker=FakeImageLooker([look]))
    done = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "p1"))
    assert done.text.startswith("Logged ") and "from your photo" in done.text
    assert reader.reads == 1


async def test_a_meal_caption_skips_the_first_look(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice, ai=False)  # nothing may be sent anywhere, the look included
    looker = FakeImageLooker([ImageLook(ImageKind.OTHER, None, "x", "")])
    agent = build(uow, scripted(), meals=FakeMeals(meal()), looker=looker)
    await agent.handle_photo(alice, IMG, "image/jpeg", "ate this", "p1")
    assert looker.seen == []


async def test_receipts_still_route_as_before(uow: UowFactory, alice: UserId) -> None:
    await agree(uow, alice)
    receipts = FakeReceipts(ReceiptDraft(is_receipt=True, amount="12.40", merchant="Cafe"))
    reader = FakeMeals(meal())
    agent = build(uow, scripted(say("Logged.")), receipts=receipts, meals=reader)
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", "lunch receipt 12.40", "p1"))
    assert "12.40" in reply.text and reader.reads == 0 and receipts.reads == 1
    plain = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "p2"))
    assert "12.40" in plain.text and reader.reads == 0
