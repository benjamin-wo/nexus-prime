"""Property-based fuzzing for the codebase's hand-written intent-parsing
regexes. #48's bug (WhiteboardPlugin._parse_intent's add_match matching the
"on" buried inside "locati|on|") and PR #17's earlier one (routes' fragment
matcher firing on "buses" via an unbounded "bus") are the same root shape: a
regex missing a word boundary, matching a trigger word as a bare substring
of an unrelated word instead of a real standalone word. One-off regression
tests pin the exact repro string that was found; this file instead states
the general invariant and lets Hypothesis search for any input that breaks
it, sweeping the bug class instead of one instance of it.
"""
from hypothesis import example, given, settings
from hypothesis import strategies as st

from capabilities.routes.tools import is_bare_place_fragment
from orchestrator.router import WhiteboardPlugin

plugin = WhiteboardPlugin()

# Real words that legitimately CONTAIN "to" or "on" as a substring without
# being the standalone word "to"/"on" -- exactly the shape #48's "location"
# was. None of these should ever satisfy a \bto\b or \bon\b match.
TRAP_WORDS = [
    "location", "photo", "into", "wanton", "button", "cotton", "bonus",
    "positive", "motion", "notion", "onion", "tonight", "tomorrow",
    "together", "token", "history", "story", "toy", "town", "top",
    "national", "station", "vacation", "mention", "mansion", "session",
    "topic", "toner", "custom", "montage", "monday", "front", "wonder",
]

FILLER_WORDS = [
    "the", "my", "can", "you", "please", "some", "details", "about",
    "this", "that", "thing", "provide", "info", "from", "web", "quickly",
    "friend", "trip", "party", "photo", "note",
]

# Single-letter/article words collide with add_match's own optional leading
# "(?:a\s+)?" group (meant for "add A NOTE to...") and can leave it having
# consumed the entire intended content, e.g. "add a to my board" -- a real
# but not very meaningful degenerate case, not the property under test here.
# "note" collides too: it's itself one of add_match's recognized `kind`
# keywords (note|checklist|card|todo|to-do), so "add note to X" parses as
# kind="note" with empty content, not content="note" -- also a genuine
# regex ambiguity, not the substring-matching property this file targets.
GENUINE_COMMAND_CONTENT_WORDS = [w for w in FILLER_WORDS if w not in ("a", "note")]


@settings(max_examples=200)
@given(
    trap=st.sampled_from(TRAP_WORDS),
    fillers=st.lists(st.sampled_from(FILLER_WORDS), min_size=0, max_size=5),
)
@example(trap="location", fillers=["can", "you", "provide", "some", "details"])  # #48's exact repro shape
def test_add_match_never_fires_without_a_real_to_or_on_word(trap, fillers):
    """Property: WhiteboardPlugin._parse_intent's add_match must only
    classify a message as add_card when a literal "to"/"on" WORD is
    present -- never merely because it's a substring of another word."""
    text = "add " + trap + " " + " ".join(fillers)
    words = set(text.lower().replace(",", " ").split())
    assert "to" not in words and "on" not in words  # sanity: fixture invariant holds

    intent = plugin._parse_intent(text)
    assert intent.get("action") != "add_card", f"{text!r} -> {intent}"


@settings(max_examples=100)
@given(
    content=st.sampled_from(GENUINE_COMMAND_CONTENT_WORDS),
    board=st.sampled_from(["Bali", "Tokyo", "Coding", "Wedding"]),
    connector=st.sampled_from(["to", "on"]),
)
def test_add_match_still_fires_on_genuine_commands(content, board, connector):
    """Guard rail against over-tightening: a real 'add X to/on Y board'
    command (a literal, standalone to/on) must still match -- the fix
    added a word boundary, it didn't remove the feature."""
    text = f"add {content} {connector} my {board} board"
    intent = plugin._parse_intent(text)
    assert intent.get("action") == "add_card", f"{text!r} -> {intent}"
    assert board.lower() in intent.get("board_ref", "").lower()


@settings(max_examples=100)
@given(
    content=st.sampled_from(GENUINE_COMMAND_CONTENT_WORDS),
    board=st.sampled_from(["Bali", "Tokyo", "Coding"]),
)
def test_pin_match_still_fires_on_genuine_commands(content, board):
    """pin_match already had the correct \\b(?:to|on)\\b guard -- this pins
    that it stays correct as a regression guard alongside add_match's fix."""
    text = f"pin {content} to my {board} board"
    intent = plugin._parse_intent(text)
    assert intent.get("action") == "pin", f"{text!r} -> {intent}"


# --- routes' fragment matcher (PR #17's earlier instance of the same shape) -

PLACE_LIKE_WORDS = ["Buspar", "Etana", "Notown", "Toledo", "Bustan", "Ontario"]


@settings(max_examples=50)
@given(word=st.sampled_from(PLACE_LIKE_WORDS))
def test_is_bare_place_fragment_not_fooled_by_excluded_word_substrings(word):
    """Property: a place-like word that merely CONTAINS an excluded token
    (e.g. "Buspar" contains "bus", "Ontario" contains "on") must still be
    treated as a legitimate place fragment -- word-boundary matching, not
    substring matching, exactly the invariant #48 restored for whiteboard."""
    assert is_bare_place_fragment(word) is True, word


def test_is_bare_place_fragment_still_excludes_real_bus_word():
    """Regression guard (PR #17): the actual standalone word must still be
    excluded -- the fix didn't just remove the exclusion list."""
    assert is_bare_place_fragment("bus") is False
    assert is_bare_place_fragment("buses") is False
