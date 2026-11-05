"""Taking emoji out of a text, for a user who chose "no emoji" in How Nexus talks.

Pure rules, no I/O. Only pictographic emoji go (with the joiners, skin tones, flags and
variation selectors that belong to them); ordinary symbols such as •, ·, —, →, ★, ✓ and
currency signs stay. The spaces an emoji leaves behind go with it, so "Done ✅" is
"Done" and "a 🎉 b" is "a b", while the rest of the text, its line breaks and its
indentation, is exactly as it was.
"""

import re


def _chars(*spans: int | tuple[int, int]) -> str:
    """A regex character class body from code points and inclusive (first, last) spans."""
    return "".join(
        re.escape(chr(span)) if isinstance(span, int) else f"{chr(span[0])}-{chr(span[1])}"
        for span in spans
    )


# Emoji that are always drawn as a picture: the big pictograph blocks (symbols and
# pictographs, emoticons, transport, supplemental symbols, flags, enclosed characters)
# and the ones below them that default to emoji presentation.
_ALWAYS = _chars(
    (0x1F000, 0x1FAFF),
    0x231A, 0x231B, (0x23E9, 0x23EC), 0x23F0, 0x23F3, 0x25FD, 0x25FE, 0x2614, 0x2615,
    (0x2648, 0x2653), 0x267F, 0x2693, 0x26A1, 0x26AA, 0x26AB, 0x26BD, 0x26BE, 0x26C4,
    0x26C5, 0x26CE, 0x26D4, 0x26EA, 0x26F2, 0x26F3, 0x26F5, 0x26FA, 0x26FD, 0x2705,
    0x270A, 0x270B, 0x2728, 0x274C, 0x274E, (0x2753, 0x2755), 0x2757, (0x2795, 0x2797),
    0x27B0, 0x27BF, 0x2B1B, 0x2B1C, 0x2B50, 0x2B55,
)  # fmt: skip
# Emoji that are text symbols until a variation selector makes them a picture, but that
# chat apps draw as a picture anyway: stripped with or without the selector. (Plain
# symbols such as ★, ✓ and the arrows are not here: they stay unless a selector asks.)
_USUALLY_PICTURE = _chars(
    0x2600, 0x260E, 0x2611, 0x261D, 0x2620, 0x2639, 0x263A, 0x2702, 0x2708, 0x2709,
    0x270C, 0x270D, 0x270F, 0x2714, 0x2716, 0x2733, 0x2734, 0x2744, 0x2747, 0x2763,
    0x2764, (0x2B05, 0x2B07),
)  # fmt: skip
_VS16 = "\ufe0f"
_VS15 = "\ufe0e"
_KEYCAP = "\u20e3"
_ZWJ = "\u200d"
_SKIN = "\U0001f3fb-\U0001f3ff"
_TAGS = "\U000e0020-\U000e007f"

# One emoji: a picture (or any non-ASCII symbol made one by VS16), its skin tone, its
# selector, any tag characters; or a keycap such as 1️⃣.
_ONE = (
    rf"(?:[{_ALWAYS}{_USUALLY_PICTURE}]|[^\x00-\x7f]{_VS16})[{_SKIN}]?{_VS16}?[{_TAGS}]*"
    rf"|[0-9#*]{_VS16}?{_KEYCAP}"
)
# Joined by a zero-width joiner into one (family, couple, profession...).
_EMOJI = rf"(?:{_ONE})(?:{_ZWJ}(?:{_ONE}))*"
# A run of them, with the spaces between ("🎉 🎉").
_RUN = rf"{_EMOJI}(?:[ \t]*{_EMOJI})*"

_PATTERN = re.compile(rf"(?P<pre>[ \t]*)(?P<run>{_RUN})(?P<post>[ \t]*)")
# A selector or joiner left with nothing to attach to.
_STRAY = re.compile(f"[{_VS16}{_VS15}]")
_CLOSING = ".,;:!?)]}"


def _gone(found: re.Match[str]) -> str:
    """What stands where an emoji run (and the spaces around it) was."""
    text, start, end = found.string, found.start(), found.end()
    at_start = start == 0 or text[start - 1] == "\n"
    at_end = end == len(text) or text[end] == "\n"
    if at_start:
        return found["pre"]  # keep any indentation, drop the gap before the words
    if at_end:
        return ""
    if not found["post"] and text[end] in _CLOSING:
        return ""  # "Done 🎉." is "Done."
    return " " if found["pre"] or found["post"] else ""


def strip_emoji(text: str) -> str:
    """``text`` without emoji, their joiners and variation selectors, and without the
    double spaces they leave. Everything else is untouched."""
    if text.isascii():
        return text
    return _STRAY.sub("", _PATTERN.sub(_gone, text))
