"""Golden-set regression suite for intent routing.

Every bug fixed this session in the routing/intent-parsing layer (#48's
add_match word-boundary bug, #17's routes fragment-matching, #32/#36's
stale-state re-plan) was found reactively -- a real user hit it, the audit
system reported it, then a one-off regression test got written for that
exact case. This file inverts that: a curated table of representative
messages with their expected routing outcome, run as one fast, deterministic
sweep, so a future change to any of these regexes/keyword lists gets caught
here before it ships, not after a production report.

Two layers are covered, matching the two places routing decisions actually
get made:
  1. _candidate_selections()/deterministic_plan() -- top-level capability
     selection (orchestrator/planner.py).
  2. WhiteboardPlugin._parse_intent() -- the in-plugin action parser that
     #48's bug lived in (orchestrator/router.py).

Extend this table whenever a new routing bug is found and fixed -- the seed
corpus below is deliberately not exhaustive.
"""
import pytest

from orchestrator.planner import _candidate_selections, missing_policy, deterministic_plan
from orchestrator.router import WhiteboardPlugin


# --- Layer 1: top-level capability selection --------------------------------

# (text, expected top capability id, note)
CAPABILITY_GOLDEN_SET = [
    ("spent $15 on lunch", "expenses", "clear expense-logging language"),
    ("how much did I spend this month", "expenses", "expense query"),
    ("what's the capital of France", "general", "factual question"),
    ("what's the weather like tomorrow", "general", "weather question"),
    ("remind me to call mom at 5pm", "reminders", "explicit reminder request"),
    ("remind me to buy groceries tomorrow", "reminders",
     "groceries-as-reminder-content carve-out must NOT also match recipes"),
    ("check my gmail for receipts", "email", "explicit email provider mention"),
    ("route from Tampines to Suntec", "routes", "explicit route request"),
    ("what's the next bus", "routes", "transit token, whole word"),
    ("recipe for pasta with tomatoes", "recipes", "explicit recipe request"),
    ("plan a trip to Bali", "whiteboard", "explicit planning-board intent"),
    ("let's do a packing list for the trip", "whiteboard", "planning-board keyword match"),
    # Word-boundary regressions: a transit token embedded mid-word must never
    # fire the routes capability (the exact class of bug #48 was, one layer
    # up -- see routes' own _has_word guard in planner.py).
    ("book a table at Tembusu Grand for dinner", None,
     "'bus' inside 'Tembusu' must not trigger routes"),
    ("explain the theta function to me", None, "'eta' inside 'theta' must not trigger routes"),
]


@pytest.mark.parametrize("text,expected_id,note", CAPABILITY_GOLDEN_SET, ids=[c[0] for c in CAPABILITY_GOLDEN_SET])
def test_capability_selection_golden_set(text, expected_id, note):
    lowered = text.lower()
    selections = _candidate_selections(lowered, missing_policy(lowered))
    ids = [s.id for s in selections]
    if expected_id is None:
        assert "routes" not in ids, f"{note}: {text!r} -> {ids}"
    else:
        assert ids and ids[0] == expected_id, f"{note}: {text!r} -> {ids}"


def test_routes_fragment_reuse_does_not_misfire_on_negation_followups():
    """Regression (PR #17): a reactive follow-up like "no i want other
    buses" must not be silently treated as a literal place-name fragment
    reusing the active route thread -- "buses" doesn't word-boundary-match
    the exclusion list's "bus"."""
    state = {
        "active_domain": "routes",
        "last_decision": {"ordering": ["routes"], "capabilities": [{"id": "routes"}]},
        "messages": [],
    }
    decision = deterministic_plan("no i want other buses", state, None)
    assert decision.source != "fragment-reuse"


# --- Layer 2: WhiteboardPlugin's in-plugin action parser --------------------

# (text, expected action, note)
WHITEBOARD_INTENT_GOLDEN_SET = [
    ("my boards", "list", "explicit list request"),
    ("what's on my Tokyo board", "summary", "explicit board summary request"),
    ("add lunch to my Bali board", "add_card", "explicit add-to-board command"),
    ("pin this to my Tokyo board", "pin", "explicit pin command"),
    ("plan a trip to Tokyo", "create", "explicit create-board command"),
    # #48's exact production repro: a conversational complaint/feature
    # request about the whiteboard, not a command. Must fall through to
    # None (-> _planning_intake's conversational path), never get
    # misparsed as an add_card with a garbage board_ref.
    (
        "why is the bali bachelor party whiteboard full of stubs, when i ask "
        "you to add the location can you provide some details from the web "
        "and like google maps etc",
        None,
        "#48: 'locati|on|' must not spuriously match add_match's (?:to|on)",
    ),
    ("for friday morning can we put Reload wellness canggu as one of the location", None,
     "freeform planning content with no add/pin/list/summary/create verb"),
    ("this is broken", None, "self-diagnostic complaint, no board verb at all"),
]


@pytest.mark.parametrize(
    "text,expected_action,note",
    WHITEBOARD_INTENT_GOLDEN_SET,
    ids=[c[0][:60] for c in WHITEBOARD_INTENT_GOLDEN_SET],
)
def test_whiteboard_parse_intent_golden_set(text, expected_action, note):
    plugin = WhiteboardPlugin()
    intent = plugin._parse_intent(text)
    assert intent.get("action") == expected_action, f"{note}: {text!r} -> {intent}"
