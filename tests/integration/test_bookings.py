"""Bookings from email: a confirmation lands on the right trip (or asks which),
nothing sensitive is stored, the cost is logged through the usual confirmation and
counts towards the trip, and reminders go out once. Everything here is made up."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import bookings as booking_cases
from nexus.application import email as email_cases
from nexus.application import trips as trip_cases
from nexus.domain.email import EmailStatus
from nexus.domain.ledger import User
from nexus.domain.money import Money
from nexus.infra.db.tables import trip_bookings
from tests.fakes import NOW, FakeMailbox, FakeRates, fake_email
from tests.integration.conftest import UowFactory
from tests.integration.test_email import connect, messages, person, sweep

pytestmark = pytest.mark.integration

RATES = FakeRates({("JPY", "SGD"): {date(2026, 9, 1): "0.0090"}})
FLIGHT = {
    "kind": "flight",
    "provider": "Acme Air",
    "segments": [
        {
            "number": "ZZ12",
            "from": "SIN",
            "to": "NRT",
            "departs": "2026-12-10T08:25",
            "arrives": "2026-12-10T16:05",
        }
    ],
}


def booking_email(message_id: str, booking: dict[str, Any], total: str | None = "820.00") -> Any:
    lines = [
        "Merchant: Acme Air",
        "Booking reference: XK7Q9P",
        "Passport: E1234567",
        f"Booking: {json.dumps(booking)}",
    ]
    if total:
        lines += [f"Total: {total}", "Currency: SGD", "Date: 2026-09-27"]
    subject = "Your booking receipt XK7Q9P" if total else "Your booking itinerary"
    return fake_email(message_id, subject, "\n".join(lines), sender="no-reply@acme-air.test")


async def tokyo(uow: UowFactory, user: User) -> trip_cases.Trip:
    return await trip_cases.create_trip(
        uow(),
        user,
        trip_cases.TripDraft(
            "Tokyo", date(2026, 12, 10), date(2026, 12, 18), "JPY", Money.of("3000", "SGD")
        ),
        now=NOW,
    )


async def test_a_booking_lands_on_its_trip_and_its_cost_counts_once_logged(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    trip = await tokyo(uow, user)
    mailbox = FakeMailbox()
    connection = await connect(uow, user, mailbox)
    mailbox.emails["b1"] = booking_email("b1", FLIGHT)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=5))

    overview = await email_cases.overview(uow(), user.id, now=NOW + timedelta(days=1))
    email = overview.emails[0]
    assert email.status is EmailStatus.PENDING
    text = email_cases.prompt_text(email, ZoneInfo(user.timezone))
    assert "flight booking (ZZ12, SIN → NRT, Thu 10 Dec 08:25)" in text
    assert "It's on your Tokyo trip" in text

    # Nothing sensitive is stored, in the booking or the email.
    async with engine.connect() as db:
        stored = json.dumps(
            [dict(r._mapping) for r in await db.execute(select(trip_bookings))], default=str
        )
    assert "XK7Q9P" not in stored and "E1234567" not in stored
    assert "XK7Q9P" not in json.dumps(email.draft) and "E1234567" not in json.dumps(email.draft)
    assert "XK7Q9P" not in email.subject

    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert [b.draft.title for b in view.bookings] == ["ZZ12 SIN → NRT"]
    assert (view.booked, view.booked_unlogged) == (Money.of("820", "SGD"), Money.of("820", "SGD"))
    assert view.to_spend == Money.of("2180", "SGD") and view.spending.spent.is_zero

    # Logged through the usual confirmation, the cost counts towards the trip
    # though it was paid in September, and isn't counted twice.
    await email_cases.log_email(uow, user, email.id, now=NOW)
    view = await trip_cases.trip_view(uow, RATES, user, trip.id, now=NOW)
    assert view.spending.spent == Money.of("820", "SGD")
    assert view.booked_unlogged == Money.zero("SGD") and view.to_spend == Money.of("2180", "SGD")
    assert any("Bookings: flight booking" in line for line in trip_cases.describe_view(view))


async def test_with_no_clear_trip_the_user_is_asked_which(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    trip = await tokyo(uow, user)
    mailbox = FakeMailbox()
    connection = await connect(uow, user, mailbox)
    hotel = {
        "kind": "hotel",
        "hotel": "Hotel Sakura",
        "check_in": "2026-10-20",
        "check_out": "2026-10-22",
    }
    mailbox.emails["h1"] = booking_email("h1", hotel, total=None)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=5))

    # An itinerary with no payment is kept as a booking, with nothing to log.
    statuses = await email_cases.overview(uow(), user.id, now=NOW + timedelta(days=1))
    assert statuses.emails[0].status is EmailStatus.NOT_RECEIPT
    asked = [m for m in await messages(engine) if "Which trip" in m["text"]]
    assert len(asked) == 1 and "hotel booking (Hotel Sakura, 2 nights" in asked[0]["text"]
    labels = [b["label"] for row in asked[0]["buttons"] for b in row]
    assert labels == ["Tokyo (10 Dec)", "Not for a trip"]
    loose = await booking_cases.unattached(uow(), user.id)
    assert [b.cost for b in loose] == [None]

    choose = asked[0]["buttons"][0][0]["data"]
    booking_id, _, trip_id = choose.removeprefix("trip:book:").partition(":")
    booking, on = await booking_cases.attach(
        uow(), user.id, UUID(booking_id), UUID(trip_id), now=NOW
    )
    assert on is not None and on.id == trip.id
    assert await booking_cases.unattached(uow(), user.id) == []
    # Deleting the trip keeps the booking, without a trip.
    await trip_cases.delete_trip(uow(), user.id, trip.id)
    assert [b.id for b in await booking_cases.unattached(uow(), user.id)] == [booking.id]


async def test_reminders_go_out_once_each(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    await tokyo(uow, user)
    mailbox = FakeMailbox()
    connection = await connect(uow, user, mailbox)
    mailbox.emails["b1"] = booking_email("b1", FLIGHT)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=5))

    month_before = datetime(2026, 11, 10, 2, tzinfo=UTC)  # 10am in Singapore, 30 days out
    assert await booking_cases.remind_everyone(uow, now=month_before) == 1
    assert await booking_cases.remind_everyone(uow, now=month_before + timedelta(hours=1)) == 0
    day_before = datetime(2026, 12, 9, 2, tzinfo=UTC)  # 10am the day before the 08:25 flight
    assert await booking_cases.remind(uow, user, now=day_before) == 1
    sent = [m["text"] for m in await messages(engine)]
    assert any(t.startswith("🛂 Tokyo is 30 days away") for t in sent)
    assert any(t.startswith("✈️ Online check-in for ZZ12") for t in sent)
