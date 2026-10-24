"""Where the user is, as a time zone: the rules that turn a signal from the phone, the chat
or a trip into a change of zone, and how a zone is named. Pure, no database. Every place
here is made up apart from the zone names."""

from datetime import UTC, datetime, timedelta

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import ZoneSource
from nexus.domain.whereabouts import (
    Change,
    Chat,
    Phone,
    Trip,
    city_name,
    clock_there,
    decide,
    known_zone,
    label,
    switched_text,
    utc_offset,
    valid_zone,
    zone_named,
)

HOME = "Asia/Singapore"
MADRID = "Europe/Madrid"
TOKYO = "Asia/Tokyo"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
HOME_SRC, PHONE, CHAT, TRIP = (
    ZoneSource.HOME,
    ZoneSource.PHONE,
    ZoneSource.CHAT,
    ZoneSource.TRIP,
)


def rule(
    current: str = HOME,
    source: ZoneSource = HOME_SRC,
    set_at: datetime | None = None,
    signal: Phone | Chat | Trip | None = None,
    home: str = HOME,
) -> Change | None:
    return decide(current, home, source, set_at, signal or Phone(HOME), NOW)


# --- the phone and the user: applied at once -----------------------------------------------


def test_a_phone_in_another_zone_moves_the_user_at_once() -> None:
    assert rule(signal=Phone(MADRID)) == Change(MADRID, PHONE, NOW, switched=True)


def test_the_user_saying_where_they_are_moves_them_at_once() -> None:
    assert rule(signal=Chat(MADRID)) == Change(MADRID, CHAT, NOW, switched=True)


def test_the_newest_of_the_phone_and_the_user_wins() -> None:
    first = rule(signal=Chat(MADRID))
    assert first is not None
    later = decide(MADRID, HOME, first.source, first.set_at, Phone(TOKYO), NOW + timedelta(hours=1))
    assert later == Change(TOKYO, PHONE, NOW + timedelta(hours=1), switched=True)
    back = decide(TOKYO, HOME, PHONE, NOW, Chat(MADRID), NOW + timedelta(minutes=5))
    assert back is not None and back.zone == MADRID and back.source is CHAT


def test_a_phone_in_the_zone_they_are_in_only_refreshes_when_it_said_so() -> None:
    long_ago = NOW - timedelta(days=3)
    change = rule(MADRID, PHONE, long_ago, Phone(MADRID))
    assert change == Change(MADRID, PHONE, NOW, switched=False)


def test_a_phone_at_home_refreshes_without_a_change() -> None:
    assert rule(signal=Phone(HOME)) == Change(HOME, HOME_SRC, NOW, switched=False)


def test_the_user_saying_the_zone_they_are_in_changes_nothing_but_the_time() -> None:
    assert rule(MADRID, TRIP, None, Chat(MADRID)) == Change(MADRID, CHAT, NOW, switched=False)


def test_a_phone_in_the_home_zone_is_home_not_phone() -> None:
    change = rule(MADRID, PHONE, NOW - timedelta(days=2), Phone(HOME))
    assert change == Change(HOME, HOME_SRC, NOW, switched=True)


def test_back_home_in_chat_goes_to_the_home_zone() -> None:
    change = rule(MADRID, CHAT, NOW - timedelta(hours=2), Chat(None))
    assert change == Change(HOME, HOME_SRC, NOW, switched=True)


def test_back_home_when_already_home_is_no_switch() -> None:
    assert rule(signal=Chat(None)) == Change(HOME, HOME_SRC, NOW, switched=False)


def test_naming_the_home_zone_in_chat_is_back_home_too() -> None:
    assert rule(MADRID, CHAT, None, Chat(HOME)) == Change(HOME, HOME_SRC, NOW, switched=True)


# --- the trip -----------------------------------------------------------------------------


def test_a_trip_moves_a_user_nobody_has_spoken_for() -> None:
    assert rule(signal=Trip(MADRID)) == Change(MADRID, TRIP, None, switched=True)


def test_a_trip_follows_its_next_stop_and_leaves_set_at_alone() -> None:
    said = NOW - timedelta(days=5)
    change = rule(MADRID, TRIP, said, Trip(TOKYO))
    assert change == Change(TOKYO, TRIP, said, switched=True)


def test_a_phone_or_chat_signal_in_the_last_24_hours_beats_the_trip() -> None:
    for source, signal in ((PHONE, Phone(HOME)), (CHAT, Chat(None))):
        recent = NOW - timedelta(hours=23, minutes=59)
        assert rule(HOME, source, recent, Trip(MADRID)) is None, signal


def test_a_trip_applies_once_the_24_hours_have_passed() -> None:
    change = rule(HOME, HOME_SRC, NOW - timedelta(hours=24), Trip(MADRID))
    assert change == Change(MADRID, TRIP, NOW - timedelta(hours=24), switched=True)


def test_a_trip_can_move_someone_the_phone_put_elsewhere_days_ago() -> None:
    change = rule(TOKYO, PHONE, NOW - timedelta(days=2), Trip(MADRID))
    assert change is not None and change.zone == MADRID and change.source is TRIP


def test_a_trip_in_the_zone_they_are_in_changes_nothing() -> None:
    assert rule(MADRID, CHAT, NOW - timedelta(days=2), Trip(MADRID)) is None
    assert rule(MADRID, TRIP, None, Trip(MADRID)) is None


def test_a_trip_in_the_home_zone_means_home() -> None:
    change = rule(MADRID, TRIP, None, Trip(HOME))
    assert change == Change(HOME, HOME_SRC, None, switched=True)


def test_with_no_trip_on_a_user_the_trip_moved_goes_home() -> None:
    said = NOW - timedelta(days=9)
    assert rule(MADRID, TRIP, said, Trip(None)) == Change(HOME, HOME_SRC, said, switched=True)


def test_with_no_trip_on_nobody_else_moves() -> None:
    for source in (HOME_SRC, PHONE, CHAT):
        assert rule(MADRID, source, NOW - timedelta(days=9), Trip(None)) is None, source


# --- zones that do not exist -------------------------------------------------------------


@pytest.mark.parametrize("signal", [Phone("Mars/Olympus"), Chat("Nowhere"), Trip("")])
def test_an_unknown_zone_is_refused(signal: Phone | Chat | Trip) -> None:
    with pytest.raises(InvalidInput, match="unknown time zone"):
        rule(signal=signal)


@pytest.mark.parametrize("raw", ["", "  ", "../etc/passwd", "Europe", "Europe/Atlantis", None])
def test_only_real_zones_are_known(raw: str | None) -> None:
    assert known_zone(raw) is None
    with pytest.raises(InvalidInput):
        valid_zone(raw)


def test_a_zone_the_user_typed_is_found_in_any_case() -> None:
    assert zone_named("europe/madrid") == MADRID
    assert zone_named("America/Buenos Aires") is None  # the real name has Argentina in it
    assert zone_named("america/argentina/buenos aires") == "America/Argentina/Buenos_Aires"
    assert zone_named("Madrid") is None  # a city is for the geocoder
    assert zone_named("UTC") == "UTC"


# --- naming a zone -------------------------------------------------------------------------


def test_a_zone_gets_a_friendly_city_name() -> None:
    assert city_name("Europe/Madrid") == "Madrid"
    assert city_name("America/Argentina/Buenos_Aires") == "Buenos Aires"
    assert city_name("Asia/Ho_Chi_Minh") == "Ho Chi Minh"
    assert city_name("UTC") == "UTC"


def test_the_offset_is_the_one_in_force_that_day() -> None:
    summer, winter = NOW, datetime(2026, 12, 24, 12, tzinfo=UTC)
    assert utc_offset(MADRID, summer) == "UTC+2"  # daylight time
    assert utc_offset(MADRID, winter) == "UTC+1"
    assert utc_offset(HOME, NOW) == "UTC+8"
    assert utc_offset("America/Argentina/Buenos_Aires", NOW) == "UTC-3"
    assert utc_offset("Asia/Kolkata", NOW) == "UTC+5:30"
    assert utc_offset("Europe/London", winter) == "UTC+0"


def test_a_label_and_the_time_there() -> None:
    assert label(MADRID, NOW) == "Madrid time (UTC+2)"
    assert clock_there(MADRID, NOW) == "14:00"
    assert clock_there(HOME, NOW) == "20:00"


def test_the_one_message_when_the_zone_changes() -> None:
    assert switched_text(MADRID, HOME, NOW) == "🕑 Switched to Madrid time (UTC+2)."
    assert switched_text(HOME, HOME, NOW) == "🕑 Back on Singapore time."
