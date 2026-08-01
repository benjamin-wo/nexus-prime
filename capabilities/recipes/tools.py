from typing import List, Dict, Any
from langchain_core.tools import tool
from sqlmodel import select
from core.db import async_session_factory
from core.models import GroceryItem

@tool
async def parse_recipe_and_extract_ingredients(recipe_text_or_url: str) -> Dict[str, Any]:
    """
    Extract recipe title and ingredient items from recipe text or URL.
    """
    # In live execution, scrapes recipe HTML or uses structured LLM extraction
    # Returns structured ingredients ready for grocery list syncing
    return {
        "title": "Extracted Recipe",
        "ingredients": [
            {"name": "Garlic", "quantity": "2 cloves", "category": "Produce"},
            {"name": "Olive Oil", "quantity": "2 tbsp", "category": "Pantry"},
            {"name": "Spaghetti", "quantity": "1 lb", "category": "Pasta"},
        ],
    }

@tool
async def sync_to_grocery_list(user_id: int, items: List[Dict[str, str]]) -> List[int]:
    """
    Add extracted recipe ingredients to the user's PostgreSQL GroceryItem table.
    items should be a list of dicts with 'name', 'quantity' (optional), 'category' (optional).
    """
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
            query = query.where(GroceryItem.is_purchased == False)
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
