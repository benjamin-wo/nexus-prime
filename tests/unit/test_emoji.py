"""Taking emoji out of a text: pictures, joiners, flags and selectors go with the spaces they
leave; ordinary symbols, line breaks and indentation stay. Made-up text only."""

import pytest

from nexus.domain.emoji import strip_emoji

VS16, VS15, ZWJ, KEYCAP = chr(0xFE0F), chr(0xFE0E), chr(0x200D), chr(0x20E3)


@pytest.mark.parametrize(
    ("text", "plain"),
    [
        ("Rent's done for October ✅", "Rent's done for October"),
        ("✅ Rent's done", "Rent's done"),
        ("Dining Out's at 182.20 of 200 — 91% used, 17.80 left ⚠️", None),
        ("Payday 🎉🎉🎉", "Payday"),
        ("a 🎉 b", "a b"),
        ("wow🎉 great", "wow great"),
        ("Done 🎉.", "Done."),
        ("Done! 🎉", "Done!"),
        ("thumbs up 👍🏽 noted", "thumbs up noted"),
        ("with the family 👨‍👩‍👧 today", "with the family today"),
        ("landed 🇸🇬 at last", "landed at last"),
        ("step 1️⃣ then 2️⃣", "step then"),
        ("hearts ❤️ and ❤ and ⭐", "hearts and and"),
        ("📧 From your email: S$12.40 at Kopi Corner", "From your email: S$12.40 at Kopi Corner"),
        ("🧾 3 new in your ledger:", "3 new in your ledger:"),
    ],
)
def test_pictographic_emoji_go_with_the_spaces_they_leave(text: str, plain: str | None) -> None:
    out = strip_emoji(text)
    if plain is not None:
        assert out == plain
    assert out == out.strip()
    assert "  " not in out
    assert not any(ord(c) >= 0x1F000 or c in (VS16, ZWJ, KEYCAP) for c in out)


def test_the_example_from_a_real_reply() -> None:
    reply = "Dining Out's at 182.20 of 200 — 91% used, 17.80 left ⚠️"
    assert strip_emoji(reply) == "Dining Out's at 182.20 of 200 — 91% used, 17.80 left"


@pytest.mark.parametrize(
    "text",
    [
        "• Dining Out: 182.20",
        "Kopi · 2.20 → Dining Out — done",
        "rating 4.6★ and ☆",
        "S$5 €5 £5 ¥500 $5 RM5 ₹5 ₩5",
        "✓ done, 2 ÷ 3, ± 1, ≈ 4, ™ ©",
        "plain text, with punctuation: 1, 2 & 3?",
        "नमस्ते क्" + ZWJ + "ष",  # a zero-width joiner in a script that needs it
        "你好, 请简短一点",
        "  indented\n    more\n\nand a blank line above",
    ],
)
def test_ordinary_symbols_text_and_layout_are_left_alone(text: str) -> None:
    assert strip_emoji(text) == text


def test_line_breaks_and_indentation_survive() -> None:
    text = "November so far:\nSpent S$412.30 ✅\n  Dining Out: S$182.20\n  ✅ Transport: S$40.00\n"
    assert strip_emoji(text) == (
        "November so far:\nSpent S$412.30\n  Dining Out: S$182.20\n  Transport: S$40.00\n"
    )


def test_a_line_of_only_emoji_leaves_an_empty_line() -> None:
    assert strip_emoji("Done\n🎉🎉\nBye") == "Done\n\nBye"
    assert strip_emoji("🎉") == ""


def test_stray_variation_selectors_are_removed() -> None:
    assert strip_emoji("star" + VS16 + " text" + VS15) == "star text"


def test_stripping_twice_changes_nothing() -> None:
    once = strip_emoji("Logged 5 ✅ at Kopi 🎉 Corner ⚠️")
    assert strip_emoji(once) == once


def test_a_text_without_emoji_is_the_same_object() -> None:
    text = "Logged 5.50 at Starbucks."
    assert strip_emoji(text) is text
