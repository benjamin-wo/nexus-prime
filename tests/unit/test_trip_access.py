"""The rules of a shared trip that need no database: names, invites and what a member
is shown. Every name and figure here is made up."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from nexus.channels.web.telegram_login import TelegramIdentity
from nexus.domain.access import token_hash
from nexus.domain.bookings import Booking, BookingDraft
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.trip_access import (
    INVITE_TTL,
    MAX_NAME,
    MAX_SUMMARY,
    TripAccess,
    TripInvite,
    TripRole,
    clean_name,
    clean_summary,
    without_money,
    without_trip_money,
)
from nexus.domain.trips import Trip

NOW = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
ME = UserId(uuid4())


def invite(**changes: object) -> TripInvite:
    base: dict[str, object] = {
        "id": uuid4(),
        "token_hash": token_hash("made-up-token"),
        "trip_id": uuid4(),
        "owner_id": ME,
        "created_at": NOW,
        "expires_at": NOW + INVITE_TTL,
    }
    base.update(changes)
    return TripInvite(**base)  # type: ignore[arg-type]


def test_an_invite_lasts_a_week_and_works_once() -> None:
    assert INVITE_TTL == timedelta(days=7)
    fresh = invite()
    assert fresh.usable(NOW) and fresh.usable(NOW + timedelta(days=6, hours=23))
    assert not fresh.usable(NOW + INVITE_TTL)
    assert not invite(redeemed_at=NOW, redeemed_by=UserId(uuid4())).usable(NOW)
    assert not invite(revoked_at=NOW).usable(NOW)
    assert not fresh.may_create_guest


def test_only_the_owner_sees_money() -> None:
    owner = TripAccess(ME, ME, TripRole.OWNER)
    member = TripAccess(ME, UserId(uuid4()), TripRole.MEMBER)
    assert owner.is_owner and owner.sees_money
    assert not member.is_owner and not member.sees_money


def test_names_are_short_and_plain() -> None:
    assert clean_name("Alex", "T.") == "Alex T."
    assert clean_name(None, None) is None
    assert clean_name("  ", "") is None
    assert clean_name("A\nB‮C​") == "A B C"
    assert len(clean_name("x" * 200) or "") == MAX_NAME


def test_names_and_summaries_lose_every_invisible_or_direction_character() -> None:
    """Characters that show nothing, or turn the line around, would let a name pass for
    another ("T" and "T" + a word joiner look the same) or garble what is near it."""
    invisible = [
        0x00AD,  # soft hyphen
        0x061C,  # Arabic letter mark
        0x180E,  # Mongolian vowel separator
        0x200B, 0x200C, 0x200D, 0x200E, 0x200F,  # zero-width and direction marks
        0x2028, 0x2029,  # line and paragraph separators
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # embeddings and overrides
        0x2060, 0x2061, 0x2062, 0x2063, 0x2064,  # word joiner, invisible operators
        0x2066, 0x2067, 0x2068, 0x2069,  # isolates
        0x206A, 0x206F,  # deprecated format characters
        0xFEFF,  # byte order mark
        0xFFF9, 0xFFFA, 0xFFFB,  # annotation characters
        0xE0041, 0xE007F,  # tag characters
    ]  # fmt: skip
    for code in invisible:
        mark = chr(code)
        assert clean_name("T" + mark) == "T", hex(code)
        assert clean_name("A" + mark + "B") == "A B", hex(code)
        assert clean_summary("moved" + mark + "Dinner") == "moved Dinner", hex(code)
    assert clean_name(chr(0x2060), chr(0xFEFF)) is None


def test_a_telegram_name_is_the_first_name_and_last_initial() -> None:
    def name(first: str | None, last: str | None) -> str | None:
        return TelegramIdentity(1, first, "a_username", last).display_name

    assert name("Alex", "Tan") == "Alex T."
    assert name("Alex", None) == "Alex"
    assert name("Alex", "  ") == "Alex"
    assert name(None, "Tan") == "T."
    assert name(None, None) is None  # the username is never used


def test_activity_is_one_short_line() -> None:
    assert clean_summary("added  Dinner\nat Sushi Ten") == "added Dinner at Sushi Ten"
    long = clean_summary("moved " + "x" * 500)
    assert len(long) == MAX_SUMMARY and long.endswith("…")


def test_a_member_sees_a_trip_and_its_bookings_without_money() -> None:
    owner = ME
    trip = Trip(
        id=uuid4(),
        user_id=owner,
        destination="Exampleland",
        start=date(2026, 12, 10),
        end=date(2026, 12, 12),
        currency="JPY",
        budget=Money.of("2000", "SGD"),
        companions=("Ann",),
        set_aside=Money.of("100", "SGD"),
        planned={"Dining Out": Money.of("600", "SGD")},
        created_at=NOW,
        updated_at=NOW,
        notes="Bring cash",
        split_evenly=False,
        not_split=(uuid4(),),
    )
    seen = without_trip_money(trip)
    assert (seen.budget, seen.set_aside, seen.planned, seen.not_split) == (None, None, {}, ())
    # The plan itself is untouched.
    assert (seen.destination, seen.companions, seen.notes) == (
        "Exampleland",
        ("Ann",),
        "Bring cash",
    )

    draft = BookingDraft.from_dict(
        {"kind": "activity", "name": "Dinner at Sushi Ten", "day": "2026-12-11", "reference": "R-1"}
    )
    assert draft is not None
    booking = Booking(uuid4(), owner, trip.id, None, draft, Money.of("20", "SGD"), uuid4(), NOW)
    plain = without_money(booking)
    assert (plain.cost, plain.transaction_id) == (None, None)
    assert plain.draft.reference == "R-1"  # references stay
