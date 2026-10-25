"""The reply-style expectations an evaluation case can have: line limits, patterns a
reply must not match, and caps on tool calls. Graded here without a model."""

from typing import Any

from nexus.evals.cases import CASES, AtMost, Case, Has, Turn
from nexus.evals.checks import World
from nexus.evals.runner import TurnLog, grade, opener, openers


def _case(**expect: Any) -> Case:
    return Case("demo", "ask", (Turn("hi"),), **expect)


async def _grade(case: Case, log: TurnLog) -> list[str]:
    world = World(uow=lambda: None, user=None, seeded=frozenset())  # type: ignore[arg-type,return-value]
    return await grade(case, [log], world, changed=False)


async def test_max_lines_counts_non_empty_lines_of_the_last_reply() -> None:
    case = _case(max_lines=2)
    assert await _grade(case, TurnLog("hi", replies=["one\n\ntwo"])) == []
    assert await _grade(case, TurnLog("hi", replies=["a\nb\nc"])) == ["reply longer than 2 lines"]


async def test_never_match_checks_every_reply_in_any_case() -> None:
    case = _case(never_match=(r"\(\d{1,3},\d{3}\)", r"got it\s*[—,-]"))
    assert await _grade(case, TurnLog("hi", replies=["Gion Walk 4.6★"])) == []
    bad = await _grade(case, TurnLog("hi", replies=["Gion 4.4/5 (6,773)"]))
    assert bad == [r"reply matches '\\(\\d{1,3},\\d{3}\\)'"]
    parrot = await _grade(case, TurnLog("hi", replies=["Fine", "Got it — heading in"]))
    assert len(parrot) == 1


async def test_at_most_caps_matching_tool_calls() -> None:
    case = _case(at_most=(AtMost("add_to_itinerary", 1, {"name": Has("gelato")}),))
    one = [
        ("add_to_itinerary", {"name": "Nijo Castle"}),
        ("add_to_itinerary", {"name": "Gelato A"}),
    ]
    assert await _grade(case, TurnLog("hi", calls=one)) == []
    two = [*one, ("add_to_itinerary", {"name": "gelato b"})]
    assert len(await _grade(case, TurnLog("hi", calls=two))) == 1


def test_the_reply_style_cases_exist_and_expect_something() -> None:
    styled = [c for c in CASES if c.max_lines or c.never_match or c.at_most]
    assert {c.id for c in styled} >= {
        "trip-ideas-brief",
        "trip-heading-there-no-parrot",
        "trip-castle-and-one-gelato",
    }


async def test_asking_counts_a_clarifying_question_without_a_question_mark() -> None:
    case = _case(asks=True)
    assert await _grade(case, TurnLog("hi", replies=["Which one did you mean?"])) == []
    listed = "Which one — the 4.20 on 28 Sep or the 7.20 on 15 Sep"
    assert await _grade(case, TurnLog("hi", replies=[listed])) == []
    assert await _grade(case, TurnLog("hi", replies=["Deleted it."])) == ["didn't ask a question"]


def test_openers_count_how_replies_start_ignoring_amounts_and_emoji() -> None:
    assert opener("Logged 60.00 at Din Tai Fung ✅") == "logged at"
    assert opener("✅ Rent's done for October") == "rent's done"
    replies = ["Logged 4.50 at A ✅", "Logged 9.10 at B", "Ann owes you 30", ""]
    assert openers(replies) == [("logged at", 2 / 3), ("ann owes", 1 / 3)]
