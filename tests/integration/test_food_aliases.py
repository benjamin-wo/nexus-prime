"""Everyday names resolve to one plain food through ``food_entry.resolve``; dishes still ask."""

from decimal import Decimal as D

import pytest

from nexus.application import food_entry
from nexus.application.food_entry import FoodRequest, NeedsAnswer
from tests.integration.conftest import UowFactory
from tests.integration.test_nutrition import stocked

pytestmark = pytest.mark.integration

EVERYDAY = {
    "egg": "usda:173424",
    "toast": "usda:174925",
    "banana": "usda:173944",
    "rice": "usda:168878",
    "chicken breast": "usda:171477",
    "milk": "usda:171265",
    "coffee": "usda:171890",
    "bee hoon": "usda:168914",
}


@pytest.fixture(autouse=True)
async def foods(uow: UowFactory) -> None:
    await stocked(uow)


@pytest.mark.parametrize(("name", "food_id"), EVERYDAY.items())
async def test_an_everyday_name_resolves_to_one_food(
    uow: UowFactory, name: str, food_id: str
) -> None:
    resolved = await food_entry.resolve(uow, [FoodRequest(name, grams=D(100))])
    assert [f.id for f in resolved.foods] == [food_id]


async def test_a_dish_is_not_a_single_food_so_it_still_asks(uow: UowFactory) -> None:
    for dish in ("chicken rice", "laksa", "nasi lemak"):
        with pytest.raises(NeedsAnswer):
            await food_entry.resolve(uow, [FoodRequest(dish, grams=D(100))])
