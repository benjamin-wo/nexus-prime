"""The meal-photo flow in code, no model: caption routing, turning a draft into food requests, and
reading the user's answer to the one question (how it was cooked, how much, which food).

A photo turn keeps its state in the reply that asked the question (``pending``: plain data, so the
checkpointer can store it). The user's next message is read against it; whatever it can't make
sense of is handed to the chat agent as an ordinary message, with nothing changed.
"""

import re
from decimal import Decimal
from typing import Any

from nexus.agent.meal_reader import CookingHint, MealDraft
from nexus.application.food_entry import FoodRequest, NeedsAnswer
from nexus.domain.nutrition import Cooking, MealSlot, words

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
            }
            for i in draft.items
        ],
        "question": draft.question,
        "meal": slot_in(caption),
        "asked": None,  # None, "question", "food" or "portion"
        "index": None,  # the item a "food" or "portion" question is about
        "options": [],  # the food ids a "which one" question offered, in order
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
            )
        )
    return found


def tool_foods(pending: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    """``log_photo_meal``'s ``foods``: each item by its resolved id, amounts as estimates."""
    foods: list[dict[str, Any]] = []
    for item, food_id in zip(pending["items"], ids, strict=True):
        cooking = CookingHint(item["cooking"]).domain()
        foods.append(
            {
                "food": food_id,
                "shown": item.get("shown") or item["name"],
                "portion": item["portion"] or None,
                "grams": f"{item['grams']:g}" if item["grams"] else None,
                "estimated": True,
                "cooking": cooking.value if cooking else None,
            }
        )
    return foods


def ask_about(
    index: int, pending: dict[str, Any], problem: NeedsAnswer
) -> tuple[str, dict[str, Any]]:
    """The question for an item that could not be resolved, and the pending state that expects
    its answer."""
    name = pending["items"][index]["name"]
    after = {**pending, "index": index, "options": [f.id for f in problem.candidates]}
    if problem.kind == "several":
        listed = "; ".join(f"{n}) {f.name}" for n, f in enumerate(problem.candidates, 1))
        return (
            f"Which one is the {name}? {listed}. Reply with the number, or tell me what it is.",
            {**after, "asked": "food"},
        )
    if problem.kind == "portion":
        return (
            f"How much {name} was it? Say a portion (like 1 bowl) or a weight in grams.",
            {**after, "asked": "portion"},
        )
    return (
        f"I couldn't find {name!r} in the food database. What is it, or what is it made of?",
        {**after, "asked": "food"},
    )


# --- reading the answer --------------------------------------------------------------------

_GRAMS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|gram|grams)\b", re.I)
_NO = re.compile(r"^\s*(?:no|cancel|stop|never ?mind|forget it|skip)\W*$", re.I)
_YES = re.compile(
    r"^\s*(?:yes|yeah|yep|ok|okay|sure|correct|right|fine|go ahead|that'?s right)\W*$", re.I
)
_PLAIN = r"\b(?:not fried|no oil|steamed|boiled|poached|grilled|baked|roasted|soup|plain)\b"
_COOKED = (
    (re.compile(_PLAIN, re.I), CookingHint.NONE),
    (re.compile(r"\bstir[- ]?fried|\bwok\b|\bsauteed?\b", re.I), CookingHint.STIR_FRIED),
    (re.compile(r"\b(?:deep[- ]?fried|fried|oily|oil)\b", re.I), CookingHint.FRIED),
    (re.compile(r"\b(?:curry|gravy|santan|coconut milk|sauce)\b", re.I), CookingHint.CURRY_GRAVY),
)
_SCALES = (
    (re.compile(r"\bhalf\b", re.I), 0.5),
    (re.compile(r"\b(?:small|smaller|little|less)\b", re.I), 0.75),
    (re.compile(r"\b(?:large|big|bigger|double|extra|more)\b", re.I), 1.25),
)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def main_item(pending: dict[str, Any]) -> int:
    """The item an answer about the dish applies to: the one the question names ("Is the egg
    fried?"), else the heaviest, else the first."""
    items = pending["items"]
    asked = str(pending.get("question") or "").lower()
    for n, item in enumerate(items):
        if any(w in asked for w in words(item["name"]) if len(w) > 2):
            return n
    return max(range(len(items)), key=lambda n: items[n]["grams"] or 0)


def _pick_number(text: str, count: int) -> int | None:
    word = text.strip().lower().rstrip(".")
    number = int(word) if word.isdigit() else _ORDINALS.get(word.split()[0] if word else "")
    return number - 1 if number and 1 <= number <= count else None


def read_answer(pending: dict[str, Any], text: str) -> tuple[str, dict[str, Any]]:
    """What the user's message does to a pending photo meal: ``("cancel", _)``, ``("go", new)``
    (resolve and confirm again) or ``("unrelated", _)`` (not an answer: leave it to the chat
    agent). Never touches nutrients: it changes the cooking, a weight or portion, or a name."""
    if _NO.match(text):
        return "cancel", pending
    if pending["asked"] in ("food", "portion") and ("?" in text or len(text) > 80):
        return "unrelated", pending  # a question or a long message is not a food or a portion
    new: dict[str, Any] = {**pending, "items": [dict(i) for i in pending["items"]]}
    new["rounds"] = pending["rounds"] + 1
    asked, index = pending["asked"], pending["index"]
    if asked == "food" and index is not None:
        options: list[str] = pending["options"]
        chosen = _pick_number(text, len(options)) if options else None
        item = new["items"][index]
        # A chosen candidate goes in by its id: ``food_entry`` looks an id up directly.
        item["name"] = options[chosen] if chosen is not None else text.strip()[:120]
        if chosen is None:
            item["shown"] = item["name"]  # what they said it is
        new["asked"] = None
        return "go", new
    if asked == "portion" and index is not None:
        item = new["items"][index]
        grams = _GRAMS.search(text)
        if grams:
            item["grams"] = float(grams.group(1))
        item["portion"] = text.strip()[:120]
        new["asked"] = None
        return "go", new
    # The answer to the clarifying question: how it was cooked, or how much.
    target = new["items"][main_item(new)]
    understood = False
    for pattern, cooking in _COOKED:
        if pattern.search(text):
            target["cooking"] = cooking.value
            understood = True
            break
    grams = _GRAMS.search(text)
    if grams and len(new["items"]) == 1:
        target["grams"] = float(grams.group(1))
        understood = True
    else:
        for pattern, scale in _SCALES:
            if pattern.search(text):
                for item in new["items"]:
                    if item["grams"]:
                        item["grams"] = round(item["grams"] * scale, 1)
                understood = True
                break
    if not understood and not _YES.match(text):
        return "unrelated", pending
    new["question"] = None
    return "go", new
