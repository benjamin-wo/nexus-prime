"""What a trip still needs, and its day labels. Every place here is made up."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.trips import Stay, Trip, clean_day_label, readiness

MADE = datetime(2026, 9, 28, tzinfo=UTC)


def seoul(budget: Money | None = None) -> Trip:
    return Trip(
        uuid4(), UserId(uuid4()), "Seoul", date(2026, 12, 7), date(2026, 12, 12), "KRW",
        budget, (), None, {}, MADE, MADE,
    )  # fmt: skip


def test_nights_without_a_stay_are_found() -> None:
    trip = seoul()  # 6 days, 5 nights: the 7th to the 11th
    assert readiness(trip, [], False).nights_without_stay == [
        date(2026, 12, d) for d in (7, 8, 9, 10, 11)
    ]
    stays = [Stay(date(2026, 12, 7), date(2026, 12, 10)), Stay(date(2026, 12, 11), None)]
    r = readiness(trip, stays, True)
    assert r.nights_without_stay == [date(2026, 12, 10)]
    assert (r.has_transport, r.has_budget, r.done) == (True, False, 1)
    full = readiness(
        seoul(Money.of("2000", "SGD")), [Stay(date(2026, 12, 6), date(2026, 12, 12))], True
    )
    assert full.nights_without_stay == [] and full.done == full.TOTAL


def test_day_labels_are_kept_to_the_trip_days() -> None:
    trip = seoul()
    labels = clean_day_label(trip, date(2026, 12, 9), "  Busan  ")
    assert labels == {date(2026, 12, 9): "Busan"}
    with pytest.raises(InvalidInput, match="isn't one of the trip's days"):
        clean_day_label(seoul(), date(2026, 12, 13), "Busan")
    assert clean_day_label(seoul(), date(2026, 12, 9), "") == {}
