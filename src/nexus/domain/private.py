"""Numbers Kaya shouldn't keep. Pure rules.

``hide_card_numbers`` is what chat (everything a user types, says or captions) is cleaned
with: only card numbers, since a passport or security code in a message means little
alone and is the user's to say. ``hide_private`` is the stricter cleaning for a trip's
notes, packing list, to-dos and covers: card numbers, security codes and passport numbers."""

import re

# Numbers a note shouldn't keep, even the owner's own: a card number (13 to 19 digits,
# starting 2 to 6, that pass the card checksum, so a ticket or order number isn't taken
# for one), a card's security code and a passport number. Booking references, ticket and
# loyalty numbers are kept: they're the user's, and what they need at the counter.
_NUMBER = re.compile(r"(?<![\w+-])(?<!\d[.,])\d+(?:[ -]\d+)*(?!\w)(?![.,]\d)")
_GROUP = re.compile(r"\d+")
_PASSPORT = re.compile(
    r"(?i)\b(passport)(?:\s+(?:no\.?|number))?\s*[:#]?\s*(?=[A-Z0-9]*\d)[A-Z0-9]{6,9}\b"
)
_SECURITY_CODE = re.compile(r"(?i)\b(cvv2?|cvc|security code)\s*[:#]?\s*\d{3,4}\b")
_CARD_LENGTHS = range(13, 20)
_CARD_FIRST = "23456"  # Mastercard's 2-series up to UnionPay and Maestro's 6


def _luhn(digits: str) -> bool:
    total = 0
    for n, ch in enumerate(reversed(digits)):
        d = int(ch)
        if n % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _is_card(digits: str) -> bool:
    return len(digits) in _CARD_LENGTHS and digits[0] in _CARD_FIRST and _luhn(digits)


def _mask_cards(match: re.Match[str]) -> str:
    """A run of digit groups (split by spaces or dashes) with any card number in it
    hidden down to its last four. The number may be followed by more digit groups (an
    expiry date), so every stretch of whole groups is tried, longest first."""
    run = match.group(0)
    groups = list(_GROUP.finditer(run))
    out: list[str] = []
    at = i = 0
    while i < len(groups):
        found = None
        digits = ""
        for j in range(i, len(groups)):
            digits += groups[j].group(0)
            if len(digits) > _CARD_LENGTHS[-1]:
                break
            if _is_card(digits):
                found = (j, digits)
        if found is None:
            i += 1
            continue
        j, digits = found
        out += [run[at : groups[i].start()], f"•••• {digits[-4:]}"]
        at = groups[j].end()
        i = j + 1
    return "".join(out) + run[at:]


def hide_card_numbers(text: str) -> str:
    """Hides card numbers (13 to 19 digits, spaces or dashes allowed, passing the card
    checksum), keeping the last four. Phone numbers, amounts, dates, references, IBANs and
    other long numbers that fail the checksum are left as they are."""
    return _NUMBER.sub(_mask_cards, text)


def hide_private(text: str) -> str:
    """Hides card numbers (keeping the last four), security codes and passport numbers."""
    text = hide_card_numbers(text)
    text = _PASSPORT.sub(lambda m: f"{m.group(1)} •••", text)
    return _SECURITY_CODE.sub(lambda m: f"{m.group(1)} •••", text)
