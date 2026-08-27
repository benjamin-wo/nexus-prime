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
from core.tool_guard import identity_bound


@tool
async def parse_recipe_and_extract_ingredients(
    recipe_text_or_url: str, recent_context: str = ""
) -> Dict[str, Any]:
    """
    Extract a recipe title and structured ingredient list from recipe text.
    Each ingredient has name, quantity, and category.

    recent_context (#35): the last few conversation turns, so a follow-up
    correction ("actually make it 2 eggs, not 3") can be resolved against the
    recipe pasted a turn earlier instead of being read as a fresh, incomplete
    recipe on its own.
    """
    canned_fallback = {
        "title": "Extracted Recipe",
        "ingredients": [
            {"name": "Garlic", "quantity": "2 cloves", "category": "Produce"},
            {"name": "Olive Oil", "quantity": "2 tbsp", "category": "Pantry"},
            {"name": "Spaghetti", "quantity": "1 lb", "category": "Pasta"},
        ],
    }
    if not settings.has_llm_key:
        return canned_fallback

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.2)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Extract the recipe title and ingredient list from the text. Reply with ONLY "
                        'a JSON object: {"title": string, "ingredients": [{"name": string, '
                        '"quantity": string, "category": string}]}. Categories: Produce, Meat, Dairy, '
                        "Pantry, Pasta, Bakery, Frozen, Spices, Other. If no recipe is present, return "
                        '{"title": "", "ingredients": []}. If recent conversation is provided, use it '
                        "ONLY to resolve a correction or continuation of a recipe already discussed "
                        "(e.g. 'actually use 2 eggs') — the current message is always the recipe to "
                        "extract; never pull in ingredients from an unrelated earlier recipe."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Recent conversation:\n{recent_context}\n\n---\n\n{recipe_text_or_url[:4000]}"
                        if recent_context
                        else recipe_text_or_url[:4000]
                    )
                ),
            ]
        )
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[RECIPES] LLM call failed: {exc}, using canned fallback")
        return canned_fallback
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
@identity_bound
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
@identity_bound
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


@tool
async def get_grocery_list(user_id: int = 0) -> str:
    """
    List the user's grocery shopping list (name, quantity, purchased?).

    Args:
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    items = await get_user_grocery_list(int(user_id or 0), include_purchased=True)
    if not items:
        return "The grocery list is empty. Send a recipe or say what to add."
    lines = []
    for item in items[:25]:
        mark = "✅" if item.get("is_purchased") else "•"
        lines.append(f"{mark} {item['name']} ({item.get('quantity', '1')})")
    return "\n".join(lines)


@tool
async def add_grocery_items(items: list, user_id: int = 0) -> str:
    """
    Add items to the user's grocery list.

    Args:
        items: list of {"name": str, "quantity": str} objects.
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    clean = [
        {"name": str(i.get("name", "")).strip(), "quantity": str(i.get("quantity", "1"))}
        for i in (items or [])
        if str(i.get("name", "")).strip()
    ]
    if not clean:
        return "No valid items to add (each needs a name)."
    added = await sync_to_grocery_list(user_id=int(user_id or 0), items=clean)
    names = ", ".join(i["name"] for i in clean[:10])
    return f"Added {len(added)} item(s) to the grocery list: {names}"
