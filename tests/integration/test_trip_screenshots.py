"""Screenshots of travel bookings and plans read onto the user's trips, with each
booking's reference kept for its owner. Every name, place and number is made up."""

from datetime import date

import pytest

from nexus.agent.receipts import ReceiptDraft
from nexus.agent.trip_reader import TripShot
from nexus.application import trips as trip_cases
from nexus.domain.bookings import BookingKind
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.domain.trips import Trip
from tests.fakes import NOW, FakeRates, FakeReceipts, FakeTripReader, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_email import person

pytestmark = pytest.mark.integration

RATES = FakeRates({("JPY", "SGD"): {date(2026, 9, 1): "0.0090"}})


async def tokyo(uow: UowFactory, user: User) -> Trip:
    return await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Tokyo", date(2026, 12, 10), date(2026, 12, 18), "JPY", None),
        now=NOW,
    )


async def test_a_booking_screenshot_lands_on_the_trip_with_its_reference(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    trip = await tokyo(uow, user)
    reader = FakeTripReader()
    agent = build(uow, scripted(), trips=reader)
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", "my hotel booking", "p1"))
    assert reply.text.splitlines() == [
        "✈️ Added to your Tokyo trip:",
        "• hotel booking (Hotel Kumo, 3 nights, 10 Dec to 13 Dec; booked on Agoda, ref "
        "9876543210), 64500 JPY",
        "• plan (Dinner at Sushi Ten, Sat 12 Dec 19:00; ref R-55821)",
        "• flight booking (ZZ12, SIN → NRT, Thu 10 Dec 08:25; ref ZK4P7Q)",
    ]
    assert reader.captions == ["my hotel booking"]
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    hotel = next(b for b in view.bookings if b.draft.kind is BookingKind.HOTEL)
    assert (hotel.draft.reference, hotel.draft.booked_via) == ("9876543210", "Agoda")
    assert hotel.cost == Money.of("64500", "JPY") and hotel.transaction_id is None

    # The same screenshot again adds nothing twice.
    again = only(await agent.handle_photo(user.id, b"png", "image/png", "booking", "p2"))
    assert again.text == "3 are already on the itinerary, so I left them."


async def test_a_photo_the_receipt_reader_calls_travel_goes_to_the_trip(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    await tokyo(uow, user)
    reader = FakeTripReader()
    receipts = FakeReceipts(ReceiptDraft(is_receipt=True, is_travel=True, amount="412"))
    agent = build(uow, scripted(), receipts, trips=reader)
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", None, "p1"))
    assert reply.text.startswith("✈️ Added to your Tokyo trip:")
    assert (receipts.reads, reader.reads) == (1, 1)

    # An ordinary receipt never reaches the trip reader.
    plain = FakeReceipts(ReceiptDraft(is_receipt=True, amount="4.20", merchant="Kopi"))
    agent = build(uow, scripted(), plain, trips=reader)
    reply = only(await agent.handle_photo(user.id, b"jpg", "image/jpeg", None, "p2"))
    assert reply.text.startswith("Log 4.20 SGD at Kopi")
    assert reader.reads == 1


async def test_without_a_trip_they_wait_and_join_the_trip_once_made(uow: UowFactory) -> None:
    user = await person(uow)
    agent = build(uow, scripted(), trips=FakeTripReader())
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", "itinerary", "p1"))
    assert reply.text.startswith("No trip covers these dates yet, so they're kept under Trips:")
    trip = await tokyo(uow, user)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert len(view.bookings) == 3


async def test_two_trips_on_those_dates_ask_which(uow: UowFactory) -> None:
    user = await person(uow)
    await tokyo(uow, user)
    await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft("Osaka", date(2026, 12, 9), date(2026, 12, 14), "JPY", None),
        now=NOW,
    )
    agent = build(uow, scripted(), trips=FakeTripReader())
    replies = await agent.handle_photo(user.id, b"png", "image/png", "bookings", "p1")
    asks = [r for r in replies if r.text.startswith("✈️ Which trip")]
    assert len(asks) == 3
    labels = [b.label for row in asks[0].buttons for b in row]
    assert labels == ["Osaka (09 Dec)", "Tokyo (10 Dec)", "Not for a trip"]
    done = only(await agent.press(user.id, asks[0].buttons[1][0].data))
    assert "Tokyo" in done.text


async def test_a_screenshot_with_nothing_to_add(uow: UowFactory) -> None:
    user = await person(uow)
    blank = FakeTripReader(TripShot(is_travel=True, entries=[]))
    agent = build(uow, scripted(), trips=blank)
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", "my trip", "p1"))
    assert reply.text.startswith("I couldn't find any bookings or plans with dates")
