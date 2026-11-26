"""Meal photos: read into foods and portions by a (fake) model, asked about once, looked up
in the food database in code, confirmed, then logged with source photo. Receipts still route
as before. Every food and figure is made up or from the bundled database."""

import pytest

from nexus.agent.image_look import ImageKind, ImageLook
from nexus.agent.meal_reader import MealDraft
from nexus.agent.receipts import ReceiptDraft
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


def meal(question: str | None = None, **second: object) -> MealDraft:
    return MealDraft.model_validate(
        {
            "items": [
                {"name": "white rice", "portion_text": "1 bowl", "grams_estimate": 150},
                {"name": "egg", "grams_estimate": 50, "kcal": 9999, **second},
            ],
            "question": question,
        }
    )


@pytest.fixture(autouse=True)
async def foods(uow: UowFactory) -> None:
    await stocked(uow)


async def meals_today(uow: UowFactory, user: UserId):  # type: ignore[no-untyped-def]
    return await nutrition_cases.meals(uow(), user, day=NOW.date(), now=NOW)


async def test_photo_then_question_then_answer_then_confirm_then_logged_as_photo(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    reader = FakeMeals(meal("Is the egg fried in oil?"))
    agent = build(uow, scripted(say("Logged.")), meals=reader)
    asked = only(await agent.handle_photo(alice, IMG, "image/jpeg", "my lunch", "p1"))
    assert asked.text == "Is the egg fried in oil?" and not asked.buttons
    assert reader.reads == 1 and await meals_today(uow, alice) == []

    card = only(await agent.handle_text(alice, "yes, fried", "m2"))
    assert card.text.startswith("Log lunch from your photo: ")
    assert "white rice (1 bowl, about " in card.text and "I estimated the portions." in card.text
    assert "9999" not in card.text and await meals_today(uow, alice) == []
    pending = card.buttons[0][0].data.split(":")[1]
    done = only(await agent.resolve(alice, pending, True))
    assert done.text.startswith("Logged lunch from your photo")

    (entry,) = await meals_today(uow, alice)
    assert entry.source is EntrySource.PHOTO and entry.meal.value == "lunch"
    assert {i.kind for i in entry.items} == {EstimateKind.ESTIMATED}
    egg = next(i for i in entry.items if i.food_id == "usda:173424")  # egg -> hard-boiled
    assert egg.cooking is not None and egg.cooking.value == "fried"
    assert egg.grams == 50
    assert egg.name == "egg" and any(i.name == "white rice" for i in entry.items)
    assert "egg (50 g, about " in card.text


async def test_no_question_goes_straight_to_the_confirm_card_and_cancel_logs_nothing(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    agent = build(uow, scripted(), meals=FakeMeals(meal()))
    card = only(await agent.handle_photo(alice, IMG, "image/jpeg", "dinner", "p1"))
    assert card.text.startswith("Log dinner from your photo: ")
    pending = card.buttons[0][0].data.split(":")[1]
    assert "cancelled" in only(await agent.resolve(alice, pending, False)).text.lower()
    assert await meals_today(uow, alice) == []


async def test_an_item_that_is_not_in_the_database_is_asked_about_then_logged(
    uow: UowFactory, alice: UserId
) -> None:
    await agree(uow, alice)
    draft = MealDraft.model_validate({"items": [{"name": "zzzz stew", "grams_estimate": 200}]})
    agent = build(uow, scripted(say("Logged.")), meals=FakeMeals(draft))
    asked = only(await agent.handle_photo(alice, IMG, "image/jpeg", "my lunch", "p1"))
    assert "couldn't find 'zzzz stew'" in asked.text and not asked.buttons
    card = only(await agent.handle_text(alice, "white rice", "m2"))
    assert card.text.startswith("Log lunch from your photo: white rice (200 g")
    assert await meals_today(uow, alice) == []


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
    card = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "p1"))
    assert card.text.startswith("Log ") and "from your photo" in card.text and reader.reads == 1


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
