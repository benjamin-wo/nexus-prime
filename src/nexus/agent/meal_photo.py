"""The meal-photo flow in code, no model: caption routing, turning a draft into food requests, and
reading the user's answer when an item can't be placed at all (no database match and no usable
estimate, or no amount).

A photo is logged straight away. Only when an item can't be placed does the flow ask, and it
keeps its state in the reply that asked (``pending``: plain data, so the checkpointer can store
it). The user's next message is read against it; whatever it can't make sense of is handed to the
chat agent as an ordinary message, with nothing changed.
"""

import re
from decimal import Decimal
from typing import Any

from nexus.agent.meal_reader import CookingHint, MealDraft
from nexus.application.food_entry import FoodRequest, NeedsAnswer, estimate_from
from nexus.domain.nutrition import Cooking, MealSlot

MAX_ROUNDS = 3  # questions about one photo before giving up and asking for words

_SLOT_WORDS = (
    (re.compile(r"\b(?:breakfast|brunch)\b", re.I), MealSlot.BREAKFAST),
    (re.compile(r"\blunch\b", re.I), MealSlot.LUNCH),
    (re.compile(r"\b(?:dinner|supper)\b", re.I), MealSlot.DINNER),
    (re.compile(r"\b(?:snack|dessert)\b", re.I), MealSlot.SNACK),
)


def slot_in(caption: str | None) -> str | None:
    """The meal a caption names ("my lunch"), as ``log_food``'s ``meal`` argument."""
    for pattern, slot in _SLOT_WORDS:
        if caption and pattern.search(caption):
            return slot.value
    return None


def pending_from(draft: MealDraft, caption: str | None) -> dict[str, Any]:
    """The draft as plain data for the first step of the flow."""
    return {
        "items": [
            {
                "name": i.name,
                "shown": i.name,
                "portion": i.portion_text,
                "grams": i.grams_estimate,
                "cooking": i.cooking.value,
                "est": [i.est_kcal, i.est_protein_g, i.est_carbs_g, i.est_fat_g],
            }
            for i in draft.items
        ],
        "meal": slot_in(caption),
        "asked": None,  # None, "food" or "portion"
        "index": None,  # the item a question is about
        "rounds": 0,
    }


def food_requests(pending: dict[str, Any]) -> list[FoodRequest]:
    found: list[FoodRequest] = []
    for item in pending["items"]:
        cooking = CookingHint(item["cooking"]).domain()
        grams = Decimal(str(item["grams"])) if item["grams"] else None
        found.append(
            FoodRequest(
                item["name"],
                item["portion"] or None,
                grams,
                True,
                Cooking(cooking) if cooking else None,
                (),
                True,
                item.get("shown") or item["name"],
                estimate_from(*item.get("est") or [None] * 4),
            )
        )
    return found


def tool_foods(pending: dict[str, Any]) -> list[dict[str, Any]]:
    """``log_photo_meal``'s ``foods``: each item by name, amounts and estimates as the
    reader gave them (the tool checks the estimates)."""
    foods: list[dict[str, Any]] = []
    for item in pending["items"]:
        cooking = CookingHint(item["cooking"]).domain()
        kcal, protein, carbs, fat = item.get("est") or [None] * 4
        foods.append(
            {
                "food": item["name"],
                "shown": item.get("shown") or item["name"],
                "portion": item["portion"] or None,
                "grams": f"{item['grams']:g}" if item["grams"] else None,
                "estimated": True,
                "cooking": cooking.value if cooking else None,
                "est_kcal": kcal,
                "est_protein_g": protein,
                "est_carbs_g": carbs,
                "est_fat_g": fat,
            }
        )
    return foods


def ask_about(
    index: int, pending: dict[str, Any], problem: NeedsAnswer
) -> tuple[str, dict[str, Any]]:
    """The question for an item that could not be resolved, and the pending state that expects
    its answer."""
    name = pending["items"][index]["name"]
    after = {**pending, "index": index}
    if problem.kind == "portion":
        return (
            f"How much {name} was it? Say a portion (like 1 bowl) or a weight in grams.",
            {**after, "asked": "portion"},
        )
    return (
        f"I couldn't place {name!r}. What is it, or what is it made of?",
        {**after, "asked": "food"},
    )


# --- reading the answer --------------------------------------------------------------------

_GRAMS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|gram|grams)\b", re.I)
_NO = re.compile(r"^\s*(?:no|cancel|stop|never ?mind|forget it|skip)\W*$", re.I)


def read_answer(pending: dict[str, Any], text: str) -> tuple[str, dict[str, Any]]:
    """What the user's message does to a pending photo meal: ``("cancel", _)``, ``("go", new)``
    (resolve and log again) or ``("unrelated", _)`` (not an answer: leave it to the chat
    agent). Never touches nutrients: it changes a weight or portion, or a name."""
    if pending["asked"] not in ("food", "portion") or pending["index"] is None:
        return "unrelated", pending
    if _NO.match(text):
        return "cancel", pending
    if "?" in text or len(text) > 80:
        return "unrelated", pending  # a question or a long message is not a food or a portion
    new: dict[str, Any] = {**pending, "items": [dict(i) for i in pending["items"]]}
    new["rounds"] = pending["rounds"] + 1
    item = new["items"][pending["index"]]
    if pending["asked"] == "food":
        item["name"] = item["shown"] = text.strip()[:120]  # what they said it is
        item["est"] = None  # the guess was for the dish the reader saw, not this
    else:
        grams = _GRAMS.search(text)
        if grams:
            item["grams"] = float(grams.group(1))
        item["portion"] = text.strip()[:120]
    new["asked"] = None
    return "go", new
