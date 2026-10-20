"""Numbers a trip's notes, packing list, to-dos and covers shouldn't keep. Pure rules."""

import re

# Numbers a note shouldn't keep, even the owner's own: a card number (15 or 16
# digits starting 3 to 6 that pass the card checksum, so a ticket number isn't
# taken for one), a card's security code and a passport number. Booking references,
# ticket and loyalty numbers are kept: they're the user's, and what they need at
# the counter.
_CARD = re.compile(r"(?<![\d-])[3-6](?:[ -]?\d){14,15}(?![\d-])")
_PASSPORT = re.compile(
    r"(?i)\b(passport)(?:\s+(?:no\.?|number))?\s*[:#]?\s*(?=[A-Z0-9]*\d)[A-Z0-9]{6,9}\b"
)
_SECURITY_CODE = re.compile(r"(?i)\b(cvv2?|cvc|security code)\s*[:#]?\s*\d{3,4}\b")


def _luhn(digits: str) -> bool:
    total = 0
    for n, ch in enumerate(reversed(digits)):
        d = int(ch)
        if n % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"•••• {digits[-4:]}" if _luhn(digits) else match.group(0)


def hide_private(text: str) -> str:
    """Hides card numbers (keeping the last four), security codes and passport numbers."""
    text = _CARD.sub(_card, text)
    text = _PASSPORT.sub(lambda m: f"{m.group(1)} •••", text)
    return _SECURITY_CODE.sub(lambda m: f"{m.group(1)} •••", text)
