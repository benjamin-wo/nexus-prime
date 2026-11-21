"""The app sign-in store: codes expire, work once, are held only as hashes and are bounded."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nexus.application.device_signin import (
    ALPHABET,
    DEVICE_CODE_TTL,
    Approved,
    DeviceSignin,
    Pending,
    StoreFull,
    display_code,
    normalise_code,
)
from nexus.domain.ledger import UserId


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def store(capacity: int = 100) -> tuple[DeviceSignin, Clock]:
    clock = Clock()
    return DeviceSignin(clock, capacity), clock


def test_codes_are_eight_unambiguous_characters() -> None:
    devices, _ = store()
    for _ in range(50):
        started = devices.start()
        assert len(started.code) == 8 and set(started.code) <= set(ALPHABET)
        assert not set(started.code) & set("01OIL")
        assert len(started.poll_id) >= 43
    assert started.expires_in == 300


def test_normalising_accepts_case_and_dash_and_rejects_the_rest() -> None:
    assert normalise_code("abcd-efgh") == "ABCDEFGH"
    assert normalise_code(" ABCD EFGH ") == "ABCDEFGH"
    assert normalise_code("ABCDEFGH") == "ABCDEFGH"
    for bad in ("", "ABCD-EFG", "ABCD-EFGHJ", "ABCD-EFG0", "ABCD-EFGO", "ABCD-EFG!"):
        assert normalise_code(bad) is None
    assert display_code("ABCDEFGH") == "ABCD-EFGH"


def test_approval_is_collected_once() -> None:
    devices, _ = store()
    started = devices.start()
    user = UserId(uuid4())
    assert isinstance(devices.poll(started.poll_id), Pending)
    assert devices.claim(started.code.lower(), 7) == started.code
    assert devices.approve(started.code, 7, user)
    assert devices.poll(started.poll_id) == Approved(user)
    assert devices.poll(started.poll_id) is None
    assert len(devices) == 0


def test_only_the_claiming_telegram_user_can_approve_or_cancel() -> None:
    devices, _ = store()
    started = devices.start()
    assert not devices.approve(started.code, 7, UserId(uuid4()))  # nobody claimed it yet
    assert devices.claim(started.code, 7)
    assert devices.claim(started.code, 8) is None  # someone else can't take it over
    assert not devices.approve(started.code, 8, UserId(uuid4()))
    assert not devices.deny(started.code, 8)
    assert isinstance(devices.poll(started.poll_id), Pending)
    assert devices.deny(started.code, 7)
    assert devices.poll(started.poll_id) is None
    assert devices.claim(started.code, 7) is None


def test_expired_codes_and_polls_are_gone() -> None:
    devices, clock = store()
    started = devices.start()
    assert devices.claim(started.code, 7)
    clock.now += DEVICE_CODE_TTL
    assert devices.claim(started.code, 7) is None
    assert not devices.approve(started.code, 7, UserId(uuid4()))
    assert devices.poll(started.poll_id) is None
    assert not devices.knows_poll(started.poll_id)
    assert len(devices) == 0


def test_unknown_unclaimable_and_expired_look_the_same() -> None:
    devices, clock = store()
    started = devices.start()
    clock.now += DEVICE_CODE_TTL
    assert devices.claim(started.code, 1) is None
    assert devices.claim("23456789", 1) is None
    assert devices.claim("nonsense", 1) is None


def test_only_hashes_are_held() -> None:
    devices, _ = store()
    started = devices.start()
    held = repr(vars(devices)) + repr([vars_of(e) for e in devices._by_code.values()])
    assert started.code not in held and started.poll_id not in held


def vars_of(entry: object) -> dict[str, object]:
    return {name: getattr(entry, name) for name in entry.__slots__}  # type: ignore[attr-defined]


def test_the_store_is_bounded_and_evicts_expired_first() -> None:
    devices, clock = store(capacity=3)
    for _ in range(3):
        devices.start()
    with pytest.raises(StoreFull):
        devices.start()
    clock.now += DEVICE_CODE_TTL + timedelta(seconds=1)
    devices.start()  # the expired ones made room
    assert len(devices) == 1
