"""Bookings: what's kept, what's hidden, which trip they land on,
and when reminders are due. Every name, number and place here is made up."""

from datetime import UTC, date, datetime
from uuid import uuid4

from nexus.domain.bookings import (
    Booking,
    BookingDraft,
    BookingKind,
    booking_reminders,
    matching_trips,
    passport_reminder,
)
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.trips import Trip, hide_private

USER = UserId(uuid4())
MADE = datetime(2026, 9, 28, tzinfo=UTC)


def trip(destination: str, start: date, end: date, currency: str = "JPY") -> Trip:
    return Trip(
        uuid4(), USER, destination, start, end, currency, Money.of("3000", "SGD"), (),
        None, {}, MADE, MADE,
    )  # fmt: skip


FLIGHT = {
    "kind": "flight",
    "provider": "Acme Air",
    "segments": [
        {
            "number": "ZZ 12",
            "from": "SIN",
            "to": "NRT",
            "departs": "2026-12-10T08:25",
            "arrives": "2026-12-10T16:05",
        },
        {"number": "ZZ13", "from": "NRT", "to": "SIN", "departs": "2026-12-18T17:30"},
    ],
}


def test_references_stay_but_card_and_passport_numbers_are_hidden() -> None:
    # The owner's references are what they need at the counter; a card isn't.
    kept = "Booking reference: XK7Q9P, booking ID 1234567890, e-ticket 123-4567890123"
    assert hide_private(kept) == kept
    assert hide_private("Paid with 4111 1111 1111 1111") == "Paid with •••• 1111"
    assert hide_private("amex 378282246310005, CVV 123") == "amex •••• 0005, CVV •••"
    assert "E1234567" not in hide_private("Passport E1234567 on file")
    assert hide_private("Call +81 3-1234-5678") == "Call +81 3-1234-5678"


def test_a_booking_keeps_its_reference_and_where_it_was_booked() -> None:
    d = BookingDraft.from_dict(
        {"kind": "hotel", "hotel": "Hotel Sakura", "check_in": "2026-12-10",
         "check_out": "2026-12-14", "reference": " 1234567890 ", "booked_via": "Agoda"}
    )  # fmt: skip
    assert d is not None and (d.reference, d.booked_via) == ("1234567890", "Agoda")
    assert d.describe() == (
        "hotel booking (Hotel Sakura, 4 nights, 10 Dec to 14 Dec; booked on Agoda, ref 1234567890)"
    )
    assert BookingDraft.from_dict(d.as_dict()) == d
    card = BookingDraft.from_dict({**d.as_dict(), "reference": "4111111111111111"})
    assert card is not None and card.reference is None  # a card number is never a reference


def test_a_flight_keeps_its_numbers_places_and_times() -> None:
    d = BookingDraft.from_dict(FLIGHT)
    assert d is not None and d.kind is BookingKind.FLIGHT
    assert [s.number for s in d.segments] == ["ZZ12", "ZZ13"]
    assert (d.starts, d.ends) == (date(2026, 12, 10), date(2026, 12, 18))
    assert d.title == "ZZ12 SIN → NRT, return"
    assert d.describe().startswith("flight booking (ZZ12, SIN → NRT, Thu 10 Dec 08:25")
    # A "flight number" that's really a reference is dropped, not kept.
    odd = BookingDraft.from_dict(
        {**FLIGHT, "segments": [{"number": "XK7Q9P", "departs": "2026-12-10T08:25"}]}
    )
    assert odd is not None and odd.segments[0].number is None
    assert BookingDraft.from_dict({"kind": "flight", "segments": []}) is None  # no date
    assert BookingDraft.from_dict({"kind": "cruise"}) is None


def test_a_hotel_keeps_its_address() -> None:
    d = BookingDraft.from_dict(
        {
            "kind": "hotel",
            "hotel": "Hotel Sakura",
            "address": "1-2-3 Nishi-Shinjuku, Tokyo 160-0023",
            "check_in": "2026-12-10",
            "check_out": "2026-12-14",
        }
    )
    assert d is not None
    assert d.address == "1-2-3 Nishi-Shinjuku, Tokyo 160-0023"
    assert d.title == "Hotel Sakura, 4 nights"
    assert (d.starts, d.ends) == (date(2026, 12, 10), date(2026, 12, 14))


def test_a_booking_lands_on_the_trip_whose_dates_it_falls_in() -> None:
    today = date(2026, 9, 28)
    tokyo = trip("Tokyo", date(2026, 12, 10), date(2026, 12, 18))
    bali = trip("Bali", date(2026, 11, 3), date(2026, 11, 8), "IDR")
    old = trip("Seoul", date(2026, 9, 1), date(2026, 9, 5), "KRW")
    assert matching_trips([tokyo, bali, old], date(2026, 12, 9), today) == [tokyo]  # a day early
    assert matching_trips([tokyo, bali, old], date(2026, 10, 1), today) == []
    assert matching_trips([tokyo, bali, old], date(2026, 9, 2), today) == []  # that trip is over


def test_reminders_come_due_once_at_the_right_time() -> None:
    tokyo = trip("Tokyo", date(2026, 12, 10), date(2026, 12, 18))
    assert passport_reminder(tokyo, date(2026, 11, 10), "SGD") is not None  # 30 days out
    assert passport_reminder(tokyo, date(2026, 11, 1), "SGD") is None
    home = trip("Penang", date(2026, 12, 10), date(2026, 12, 12), "SGD")
    assert passport_reminder(home, date(2026, 11, 10), "SGD") is None  # not abroad

    draft = BookingDraft.from_dict(FLIGHT)
    assert draft is not None
    flight = Booking(uuid4(), USER, tokyo.id, None, draft, None, None, MADE)
    assert booking_reminders(flight, datetime(2026, 12, 9, 7, 0)) == []
    due = booking_reminders(flight, datetime(2026, 12, 9, 9, 0))
    assert [r.key for r in due] == [f"checkin:{flight.id}:0"]
    assert "Acme Air" in due[0].text

    stay = BookingDraft.from_dict(
        {
            "kind": "hotel",
            "hotel": "Hotel Sakura",
            "address": "1-2-3 Nishi-Shinjuku",
            "check_in": "2026-12-10",
        }
    )
    assert stay is not None
    hotel = Booking(uuid4(), USER, tokyo.id, None, stay, None, None, MADE)
    assert booking_reminders(hotel, datetime(2026, 12, 10, 7, 0)) == []
    assert "1-2-3 Nishi-Shinjuku" in booking_reminders(hotel, datetime(2026, 12, 10, 8, 30))[0].text


def test_dates_and_times_written_out_are_read_too() -> None:
    # The reader is asked for ISO, but sometimes writes dates out.
    raw = {
        **FLIGHT,
        "segments": [
            {"number": "ZZ12", "departs": "10 Dec 2026 08:25", "arrives": "Thu, 10 Dec 2026 16:05"}
        ],
    }
    d = BookingDraft.from_dict(raw)
    assert d is not None and d.segments[0].departs == datetime(2026, 12, 10, 8, 25)
    stay = BookingDraft.from_dict(
        {"kind": "hotel", "check_in": "Thu, 10 Dec 2026", "check_out": "14 December 2026"}
    )
    assert stay is not None and (stay.check_in, stay.check_out) == (
        date(2026, 12, 10),
        date(2026, 12, 14),
    )


def test_a_plan_without_a_day_is_a_place_to_visit() -> None:
    d = BookingDraft.from_dict(
        {"kind": "activity", "name": "Namdaemun Market", "category": "Shopping"}
    )
    assert d is not None and d.starts is None and d.category == "Shopping"
    assert d.describe() == "place to visit (Namdaemun Market, Shopping)"
    assert BookingDraft.from_dict({"kind": "activity", "category": "Food"}) is None  # no name
    place = Booking(uuid4(), USER, None, None, d, None, None, MADE)
    assert not place.scheduled
