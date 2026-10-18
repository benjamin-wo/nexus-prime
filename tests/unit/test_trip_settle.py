"""Splitting a trip evenly and netting what people owe each other: shares and rounding,
matching names, mixed currencies and a missing exchange rate. Every name and figure is
made up."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from nexus.domain.bookings import Booking, BookingDraft, BookingKind
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.settle import (
    Debt,
    DebtKind,
    Direction,
    PaidByOther,
    check_payment,
    clean_split_with,
    describe_balance,
    match_traveller,
    my_share_of,
    settle_up,
)

DAY = date(2026, 12, 12)
WHO = UserId(UUID(int=1))


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def jpy(amount: str) -> Money:
    return Money.of(amount, "JPY")


def iou(name: str, amount: Money, home: Money | None, label: str | None = None) -> Debt:
    return Debt(DebtKind.IOU, uuid4(), name, amount, home, label, DAY)


def payment(name: str, amount: Money, home: Money | None, label: str | None = None) -> Debt:
    return Debt(DebtKind.PAYMENT, uuid4(), name, amount, home, label, DAY)


def paid(amount: Money, split_with: tuple[str, ...] = ()) -> PaidByOther:
    return PaidByOther(
        uuid4(), WHO, uuid4(), "Alex", amount, "the ryokan", DAY, split_with, None,
        datetime(2026, 12, 12, tzinfo=UTC),
    )  # fmt: skip


# --- the user's share ------------------------------------------------------------------


def test_my_share_is_an_equal_part_and_takes_the_leftover_unit() -> None:
    assert my_share_of(sgd("460"), 2) == sgd("230")
    assert my_share_of(sgd("100"), 3) == sgd("33.34")  # the user's share comes first
    assert my_share_of(sgd("0.01"), 3) == sgd("0.01")
    assert my_share_of(jpy("1000"), 3) == jpy("334")  # no minor unit below the yen
    assert my_share_of(jpy("2"), 3) == jpy("1")


def test_the_share_agrees_with_how_a_bill_is_split() -> None:
    from nexus.domain.ledger import ShareRequest, plan_split

    for amount in ("460", "100", "0.05", "9999.99"):
        plan = plan_split(sgd(amount), [ShareRequest("Alex"), ShareRequest("Sam")])
        assert my_share_of(sgd(amount), 3) == plan.own_share


def test_a_payment_is_shared_by_the_payer_the_user_and_the_others() -> None:
    assert paid(sgd("460")).sharers == 2 and paid(sgd("460")).my_share == sgd("230")
    three = paid(sgd("100"), ("Sam",))
    assert (three.sharers, three.my_share) == (3, sgd("33.34"))
    assert not three.settled


@pytest.mark.parametrize("amount", ["0", "-5", "1000000000000"])
def test_a_payment_must_be_positive_and_a_size_a_trip_can_have(amount: str) -> None:
    with pytest.raises(InvalidInput):
        check_payment(sgd(amount))


def test_a_payment_is_in_whole_minor_units() -> None:
    assert check_payment(sgd("12.34")) == sgd("12.34")
    with pytest.raises(InvalidInput):
        check_payment(jpy("100.5"))
    with pytest.raises(InvalidInput):
        check_payment(sgd("12.345"))


# --- who shares ------------------------------------------------------------------------


def test_travellers_are_matched_as_the_trip_spells_them() -> None:
    people = ["Alex", "Wei Ming", "Sam Tan", "Sam Lee"]
    assert match_traveller(people, "alex") == "Alex"
    assert match_traveller(people, "TAN WEI MING") == "Wei Ming"  # as a bank prints it
    assert match_traveller(people, "Wei") == "Wei Ming"
    assert match_traveller(people, "Sam") is None  # two Sams: not plainly one
    assert match_traveller(people, "Sam Lee") == "Sam Lee"
    assert match_traveller(people, "Zoe") is None


def test_everyone_shares_unless_told_otherwise() -> None:
    people = ["Alex", "Sam", "Ann"]
    assert clean_split_with(people, "Alex", None) == ("Sam", "Ann")
    assert clean_split_with(people, "Alex", ["sam"]) == ("Sam",)
    assert clean_split_with(people, "Alex", ["Alex", "Sam", "SAM"]) == ("Sam",)  # no payer, once
    assert clean_split_with(people, "Alex", []) == ()
    with pytest.raises(InvalidInput, match="Zoe isn't on this trip"):
        clean_split_with(people, "Alex", ["Zoe"])


# --- netting ---------------------------------------------------------------------------


def test_a_person_is_netted_against_what_the_user_owes_them() -> None:
    balances = settle_up(
        [iou("Alex", sgd("768"), sgd("768"), "Hotel")],
        [payment("Alex", sgd("230"), sgd("230"), "the ryokan")],
        "SGD",
    )
    [alex] = balances
    assert alex.net_home == sgd("538") and alex.direction is Direction.OWES_YOU
    assert alex.net_by_currency == [sgd("538")]
    assert describe_balance(alex) == "Alex owes you 538.00 SGD"
    assert len(alex.owes_you) == 1 and len(alex.you_owe) == 1


def test_the_user_can_owe_more_than_they_are_owed() -> None:
    [sam] = settle_up(
        [iou("Sam", sgd("10"), sgd("10"))], [payment("Sam", sgd("50"), sgd("50"))], "SGD"
    )
    assert sam.net_home == sgd("-40") and sam.direction is Direction.YOU_OWE
    assert describe_balance(sam) == "You owe Sam 40.00 SGD"


def test_people_who_are_even_are_still_listed_to_settle() -> None:
    [ann] = settle_up(
        [iou("Ann", sgd("20"), sgd("20"))], [payment("Ann", sgd("20"), sgd("20"))], "SGD"
    )
    assert ann.net_home == sgd("0") and ann.direction is Direction.EVEN
    assert describe_balance(ann) == "You and Ann are even"


def test_names_are_matched_like_everywhere_else_and_written_as_the_trip_spells_them() -> None:
    balances = settle_up(
        [iou("TAN WEI MING", sgd("30"), sgd("30"))],
        [payment("wei ming", sgd("5"), sgd("5")), payment("Alex", sgd("7"), sgd("7"))],
        "SGD",
        travellers=["Wei Ming", "Alex"],
    )
    assert [(b.name, b.net_home) for b in balances] == [
        ("Alex", sgd("-7")),
        ("Wei Ming", sgd("25")),
    ]


def test_without_the_trip_naming_them_the_first_spelling_stands() -> None:
    balances = settle_up(
        [iou("Wei Ming", sgd("30"), sgd("30"))],
        [payment("TAN WEI MING", sgd("5"), sgd("5"))],
        "SGD",
    )
    assert [b.name for b in balances] == ["Wei Ming"] and balances[0].net_home == sgd("25")


def test_people_are_listed_a_to_z_and_nobody_is_made_up() -> None:
    assert settle_up([], [], "SGD") == []
    balances = settle_up(
        [iou("sam", sgd("1"), sgd("1")), iou("Alex", sgd("1"), sgd("1"))],
        [payment("Ben", sgd("1"), sgd("1"))],
        "SGD",
    )
    assert [b.name for b in balances] == ["Alex", "Ben", "sam"]


def test_mixed_currencies_net_in_the_home_currency() -> None:
    # 30,000 yen owed to the user is 270 at 0.009; the user's 50 USD share is 67.50.
    [alex] = settle_up(
        [iou("Alex", jpy("30000"), sgd("270"))],
        [payment("Alex", Money.of("50", "USD"), sgd("67.50"))],
        "SGD",
    )
    assert alex.net_home == sgd("202.50")
    assert alex.net_by_currency == [jpy("30000"), Money.of("-50", "USD")]


def test_a_missing_exchange_rate_leaves_the_total_unknown_but_keeps_the_parts() -> None:
    [alex] = settle_up(
        [iou("Alex", jpy("30000"), None)], [payment("Alex", sgd("10"), sgd("10"))], "SGD"
    )
    assert alex.net_home is None
    assert alex.net_by_currency == [jpy("30000"), sgd("-10")]
    assert alex.direction is None  # two currencies, no rate: can't say who owes more
    assert "no exchange rate" in describe_balance(alex)
    assert "Alex owes you 30000 JPY" in describe_balance(alex)
    assert "you owe Alex 10.00 SGD" in describe_balance(alex)

    # In one currency the direction is still plain.
    [sam] = settle_up([iou("Sam", jpy("500"), None)], [], "SGD")
    assert sam.net_home is None and sam.direction is Direction.OWES_YOU


# --- what a link shows -----------------------------------------------------------------


def booking(draft: BookingDraft, *, email_id: UUID | None = None) -> Booking:
    return Booking(
        id=uuid4(), user_id=WHO, trip_id=uuid4(), email_id=email_id, draft=draft, cost=None,
        transaction_id=None, created_at=datetime(2026, 11, 1, tzinfo=UTC),
    )  # fmt: skip


def draft(kind: BookingKind, **changes: object) -> BookingDraft:
    base: dict[str, object] = {
        "kind": kind, "provider": None, "segments": (), "hotel": None, "address": None,
        "check_in": None, "check_out": None, "name": "Dinner", "day": DAY,
    }  # fmt: skip
    return BookingDraft(**{**base, **changes})  # type: ignore[arg-type]


def test_flights_stays_trains_and_booked_plans_are_bookings_but_own_plans_are_not() -> None:
    assert booking(draft(BookingKind.FLIGHT)).is_booking
    assert booking(draft(BookingKind.HOTEL)).is_booking
    assert booking(draft(BookingKind.RAIL)).is_booking
    assert not booking(draft(BookingKind.ACTIVITY)).is_booking  # "dinner at Sushi Ten"
    assert booking(draft(BookingKind.ACTIVITY), email_id=uuid4()).is_booking  # from an email
    assert booking(draft(BookingKind.ACTIVITY, reference="ABC123")).is_booking
    assert booking(draft(BookingKind.ACTIVITY, booked_via="Klook")).is_booking
