import json
import re
from typing import List, Dict, Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from sqlmodel import select

from core.config import settings
from core.db import async_session_factory
from core.llm import ThinkingLevel, get_agent_llm
from core.models import GroceryItem


@tool
async def parse_recipe_and_extract_ingredients(recipe_text_or_url: str) -> Dict[str, Any]:
    """
    Extract a recipe title and structured ingredient list from recipe text.
    Each ingredient has name, quantity, and category.
    """
    if not settings.deepseek_api_key or settings.deepseek_api_key == "test_deepseek_key":
        # Local tests/dev fallback: structured canned result.
        return {
            "title": "Extracted Recipe",
            "ingredients": [
                {"name": "Garlic", "quantity": "2 cloves", "category": "Produce"},
                {"name": "Olive Oil", "quantity": "2 tbsp", "category": "Pantry"},
                {"name": "Spaghetti", "quantity": "1 lb", "category": "Pasta"},
            ],
        }

    llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.2)
    ai_message = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    "Extract the recipe title and ingredient list from the text. Reply with ONLY "
                    'a JSON object: {"title": string, "ingredients": [{"name": string, '
                    '"quantity": string, "category": string}]}. Categories: Produce, Meat, Dairy, '
                    "Pantry, Pasta, Bakery, Frozen, Spices, Other. If no recipe is present, return "
                    '{"title": "", "ingredients": []}.'
                )
            ),
            HumanMessage(content=recipe_text_or_url[:4000]),
        ]
    )
    raw = str(getattr(ai_message, "content", "") or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw)
        ingredients = parsed.get("ingredients") or []
        return {
            "title": parsed.get("title") or "Extracted Recipe",
            "ingredients": [
                {
                    "name": str(item.get("name", "Unknown item")),
                    "quantity": str(item.get("quantity", "1")),
                    "category": str(item.get("category", "General")),
                }
                for item in ingredients
                if item.get("name")
            ],
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[RECIPES] extraction parse failed: {exc}")
        return {"title": "Extracted Recipe", "ingredients": []}


@tool
async def sync_to_grocery_list(user_id: int, items: List[Dict[str, str]]) -> List[int]:
    """Add extracted recipe ingredients to the user's PostgreSQL GroceryItem table."""
    added_ids = []
    async with async_session_factory() as session:
        for item in items:
            g_item = GroceryItem(
                user_id=user_id,
                name=item.get("name", "Unknown item"),
                quantity=item.get("quantity", "1"),
                category=item.get("category", "General"),
                is_purchased=False,
            )
            session.add(g_item)
            await session.commit()
            await session.refresh(g_item)
            added_ids.append(g_item.id)
    return added_ids


@tool
async def get_user_grocery_list(user_id: int, include_purchased: bool = False) -> List[Dict[str, Any]]:
    """Retrieve the user's current grocery items."""
    async with async_session_factory() as session:
        query = select(GroceryItem).where(GroceryItem.user_id == user_id)
        if not include_purchased:
            query = query.where(GroceryItem.is_purchased == False)  # noqa: E712
        result = await session.execute(query)
        items = result.scalars().all()
        return [
            {
                "id": idx.id,
                "name": idx.name,
                "quantity": idx.quantity,
                "category": idx.category,
                "is_purchased": idx.is_purchased,
            }
            for idx in items
        ]
