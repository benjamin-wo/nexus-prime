"""A trip's Prep tab: to-dos, cover and documents, the suggestions worked out in code and
the reminder for a to-do that is due. Every name, number and place here is made up."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from nexus.domain.bookings import todo_reminders
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.prep import (
    Cover,
    CoverDraft,
    CoverKind,
    Todo,
    TripFacts,
    clean_cover,
    clean_list,
    country_of,
    from_rows,
    suggestions,
)
from nexus.domain.trip_access import without_cover_money
from nexus.domain.trips import Trip

USER = UserId(uuid4())
MADE = datetime(2026, 9, 28, tzinfo=UTC)


def trip(**changes: object) -> Trip:
    base = Trip(
        uuid4(), USER, "Tokyo, Japan", date(2026, 12, 10), date(2026, 12, 18), "JPY", None, (),
        None, {}, MADE, MADE,
    )  # fmt: skip
    return replace(base, **changes)  # type: ignore[arg-type]


def cover(kind: CoverKind = CoverKind.INSURANCE, **changes: object) -> Cover:
    draft = CoverDraft(kind, "Harbour Cover", "TX-4471", "+65 6123 4567")
    return Cover(uuid4(), USER, uuid4(), replace(draft, **changes), None, MADE, MADE)  # type: ignore[arg-type]


FACTS = TripFacts("Tokyo, Japan", nights=8, abroad=True)


# --- to-dos ----------------------------------------------------------------------------


def test_todo_lists_are_cleaned_and_capped() -> None:
    items = [
        Todo("a1", " Get  yen ", date(2026, 12, 8)),
        Todo("a2", "get yen"),  # the same words, ignoring case
        Todo("a3", "  "),
        Todo("a1", "Book the airport train", None, True),  # a repeated id gets a new one
        Todo("", "Pay with 4111 1111 1111 1111"),
        Todo("b b", "Print tickets\x00‮"),
    ]
    kept = clean_list(items)
    assert [t.text for t in kept] == [
        "Get yen",
        "Book the airport train",
        "Pay with •••• 1111",
        "Print tickets",
    ]
    assert kept[0] == Todo("a1", "Get yen", date(2026, 12, 8))
    assert kept[1].done and kept[1].id != "a1"
    assert len({t.id for t in kept}) == 4 and all(1 <= len(t.id) <= 16 for t in kept)
    assert len(clean_list([Todo("x", "y" * 200)])[0].text) == 80
    with pytest.raises(InvalidInput):
        clean_list([Todo(f"i{n}", f"thing {n}") for n in range(51)])
    assert len(clean_list([Todo(f"i{n}", f"thing {n}") for n in range(50)])) == 50


def test_stored_todos_skip_what_is_malformed() -> None:
    rows = [
        {"id": "a1", "text": "Get yen", "due": "2026-12-08", "done": 1},
        {"id": "a2", "text": "No date", "due": "not a date"},
        {"id": "a3", "text": " "},
        {"id": "bad id!", "text": "Odd id"},
        {"text": "No id"},
        "x",
    ]
    assert from_rows(rows) == (
        Todo("a1", "Get yen", date(2026, 12, 8), True),
        Todo("a2", "No date"),
    )
    assert from_rows(None) == ()
    assert Todo("a1", "Get yen", date(2026, 12, 8)).to_dict() == {
        "id": "a1",
        "text": "Get yen",
        "due": "2026-12-08",
        "done": False,
    }


# --- cover and documents ---------------------------------------------------------------


def test_a_cover_is_checked_and_tidied() -> None:
    draft = CoverDraft(
        CoverKind.INSURANCE, "  Harbour   Cover ", " TX-4471 ", "+65 (0) 6123-4567",
        date(2026, 12, 10), date(2026, 12, 18), Money.of("89", "SGD"), " Call before any claim ",
    )  # fmt: skip
    kept = clean_cover(draft)
    assert kept == replace(
        draft, name="Harbour Cover", reference="TX-4471", note="Call before any claim"
    )
    assert kept.describe() == (
        "Harbour Cover (insurance, ref TX-4471, phone +65 (0) 6123-4567, 10 Dec to 18 Dec)"
    )
    blank = clean_cover(CoverDraft(CoverKind.OTHER, "Cash letter", " ", "", None, None, None, " "))
    assert (blank.reference, blank.phone, blank.note) == (None, None, None)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "  "}, "needs a name"),
        ({"name": "x" * 81}, "longer than 80"),
        ({"reference": "r" * 61}, "longer than 60"),
        ({"phone": "call Sam on 6123"}, "can only have digits"),
        ({"phone": "---"}, "can only have digits"),
        ({"phone": "1" * 31}, "longer than 30"),
        ({"note": "n" * 201}, "longer than 200"),
        ({"reference": "4111 1111 1111 1111"}, "card or passport number"),
        ({"reference": "Passport E1234567"}, "card or passport number"),
        ({"reference": "CVV 123"}, "card or passport number"),
        ({"name": "My passport", "reference": "E1234567"}, "passport's number isn't kept"),
        ({"starts": date(2026, 12, 18), "ends": date(2026, 12, 10)}, "end before it starts"),
        ({"cost": Money.of("0", "SGD")}, "more than zero"),
    ],
)
def test_a_cover_refuses_what_it_should_not_keep(change: dict[str, object], message: str) -> None:
    draft = replace(CoverDraft(CoverKind.INSURANCE, "Harbour Cover"), **change)  # type: ignore[arg-type]
    with pytest.raises(InvalidInput, match=message):
        clean_cover(draft)


def test_a_name_and_note_have_card_and_passport_numbers_hidden() -> None:
    kept = clean_cover(
        CoverDraft(
            CoverKind.DOCUMENT, "Paid 4111 1111 1111 1111", note="Passport E1234567 is in the safe"
        )
    )
    assert kept.name == "Paid •••• 1111" and kept.note == "Passport ••• is in the safe"


def test_what_a_cover_cost_is_removed_for_a_member() -> None:
    logged = replace(
        cover(cost=Money.of("89", "SGD")),
        logged_transaction_id=uuid4(),
    )
    seen = without_cover_money(logged)
    assert seen.cost is None and seen.logged_transaction_id is None
    assert (seen.draft.reference, seen.draft.phone) == ("TX-4471", "+65 6123 4567")
    assert logged.cost == Money.of("89", "SGD")  # the owner's own is untouched


# --- suggestions -----------------------------------------------------------------------


def keys(found: list) -> list[str]:  # type: ignore[type-arg]
    return [s.key for s in found]


def test_a_trip_abroad_gets_the_four_suggestions_in_order() -> None:
    found = suggestions(FACTS, [], [], [])
    assert [(s.key, s.text, s.sub, s.action) for s in found] == [
        (
            "insurance",
            "Travel insurance",
            "Medical and cancellation cover for the dates",
            "add_cover",
        ),
        ("visa", "Check entry rules for Japan", "Visas and passport validity", "add_todo"),
        ("passport", "Passport valid 6 months after you're back", found[2].sub, "add_todo"),
        ("money", "Tell your bank / sort a travel card", found[3].sub, "add_todo"),
    ]


def test_nothing_is_suggested_at_home() -> None:
    assert suggestions(replace(FACTS, abroad=False), [], [], []) == []


def test_a_cover_or_a_to_do_takes_a_suggestion_away() -> None:
    assert "insurance" not in keys(suggestions(FACTS, [cover()], [], []))
    # A visa is not insurance.
    assert "insurance" in keys(suggestions(FACTS, [cover(CoverKind.VISA)], [], []))
    assert "visa" not in keys(suggestions(FACTS, [cover(CoverKind.VISA)], [], []))
    for todo, gone in [
        ("Apply for the visa", "visa"),
        ("Check ENTRY RULES for Japan", "visa"),  # what the suggestion itself adds
        ("Renew passport", "passport"),
        ("Passport valid 6 months after you're back", "passport"),
        ("Get some cash", "money"),
        ("Order a travel card", "money"),
        ("Exchange money", "money"),
        ("Tell your bank / sort a travel card", "money"),
    ]:
        assert gone not in keys(suggestions(FACTS, [], [Todo("t", todo)], [])), todo
        # A done to-do counts: it was dealt with.
        assert gone not in keys(suggestions(FACTS, [], [Todo("t", todo, None, True)], [])), todo
    # A to-do about something else leaves them all.
    assert len(suggestions(FACTS, [], [Todo("t", "Get yen")], [])) == 4


def test_money_is_for_a_trip_of_a_night_or_more() -> None:
    day_trip = suggestions(replace(FACTS, nights=0), [], [], [])
    assert keys(day_trip) == ["insurance", "visa", "passport"]
    assert "money" in keys(suggestions(replace(FACTS, nights=1), [], [], []))


def test_not_needed_is_remembered() -> None:
    assert keys(suggestions(FACTS, [], [], ["insurance", "money", "something else"])) == [
        "visa",
        "passport",
    ]
    assert suggestions(FACTS, [], [], ["insurance", "visa", "passport", "money"]) == []


def test_the_country_is_the_last_part_of_the_destination() -> None:
    assert country_of("Tokyo, Japan") == "Japan"
    assert country_of("Kyoto") == "Kyoto"
    assert country_of(" Osaka ,  Japan ") == "Japan"
    named = suggestions(replace(FACTS, destination="Bali"), [], [], [])
    assert named[1].text == "Check entry rules for Bali"


# --- reminders -------------------------------------------------------------------------


def test_a_to_do_is_reminded_the_morning_before_it_is_due() -> None:
    due = date(2026, 12, 8)
    t = trip(
        todos=(Todo("a1", "Get yen", due), Todo("a2", "No day"), Todo("a3", "Done", due, True))
    )
    before = datetime(2026, 12, 7, 7, 59)
    assert todo_reminders(t, before) == []
    found = todo_reminders(t, datetime(2026, 12, 7, 8, 0))
    assert [(r.key, r.text) for r in found] == [
        (f"todo:{t.id}:a1:2026-12-08", "Tomorrow: Get yen for Tokyo, Japan")
    ]
    assert todo_reminders(t, datetime(2026, 12, 7, 23, 30)) == found
    # On the day itself, "tomorrow" is wrong, so there's none.
    assert todo_reminders(t, datetime(2026, 12, 8, 0, 0)) == []
    assert todo_reminders(t, datetime(2026, 12, 8, 9, 0)) == []
    # A new date is a new reminder (a new key).
    moved = replace(t, todos=(Todo("a1", "Get yen", date(2026, 12, 9)),))
    assert todo_reminders(moved, datetime(2026, 12, 8, 9, 0))[0].key != found[0].key
