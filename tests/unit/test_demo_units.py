"""Small pieces of the public demo that need no database: who is asking, and the rate limits."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from starlette.requests import Request

from nexus.application import acting, demo
from nexus.application.limits import RateLimiter
from nexus.channels.web.security import WebRuntime, client_ip
from nexus.domain.demo import forbid
from nexus.domain.errors import Forbidden
from nexus.domain.ledger import Role, User, UserId
from nexus.settings import Settings

NOW = datetime(2026, 9, 28, 4, tzinfo=UTC)


def request(forwarded: str | None, peer: str | None = "10.1.2.3") -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 5000) if peer else None})


def web(hops: int) -> WebRuntime:
    settings = Settings(_env_file=None, database_url="postgresql://x/y", trusted_proxy_hops=hops)
    return cast(WebRuntime, SimpleNamespace(settings=settings))


@pytest.mark.parametrize(
    ("forwarded", "hops", "expected"),
    [
        ("203.0.113.7", 1, "203.0.113.7"),
        # What the visitor wrote is further left than what our own proxy appended.
        ("1.2.3.4, 203.0.113.7", 1, "203.0.113.7"),
        ("1.2.3.4, 203.0.113.7, 10.9.9.9", 2, "203.0.113.7"),
        (None, 1, "10.1.2.3"),  # no proxy header: the peer
        ("", 1, "10.1.2.3"),
        ("not an address", 1, "10.1.2.3"),
        ("203.0.113.7", 2, "10.1.2.3"),  # fewer entries than proxies: not from our proxy
        ("203.0.113.7", 0, "10.1.2.3"),  # headers ignored
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", 1, "2001:db8:1:2::/64"),
        ("2001:db8:1:2:1:1:1:1", 1, "2001:db8:1:2::/64"),  # the same home or phone
    ],
)
def test_the_visitors_address_is_what_our_own_proxy_saw(
    forwarded: str | None, hops: int, expected: str
) -> None:
    assert client_ip(request(forwarded), web(hops)) == expected


def test_a_request_with_no_peer_is_still_counted() -> None:
    assert client_ip(request(None, peer=None), web(1)) == "unknown"


def test_a_demo_gets_a_third_of_every_allowance() -> None:
    limiter = RateLimiter({"web": ((6, timedelta(days=1)),), "one": ((2, timedelta(days=1)),)})
    assert sum(limiter.allow("web", "real", demo=False) for _ in range(10)) == 6
    assert sum(limiter.allow("web", "demo", demo=True) for _ in range(10)) == 2
    assert sum(limiter.allow("one", "demo", demo=True) for _ in range(10)) == 1  # at least one


def test_the_limiter_follows_who_the_work_is_for() -> None:
    limiter = RateLimiter({"web": ((6, timedelta(days=1)),)})
    acting.set_demo(True)
    try:
        assert sum(limiter.allow("web", "someone") for _ in range(10)) == 2
    finally:
        acting.set_demo(False)
    assert sum(limiter.allow("web", "someone-else") for _ in range(10)) == 6


def test_acting_as_forgets_a_demo_when_it_ends() -> None:
    user = UserId(uuid4())
    with acting.acting_as(user):
        acting.set_demo(True)
        assert acting.is_demo()
    assert not acting.is_demo()


def test_a_made_up_telegram_id_is_always_negative() -> None:
    ids = {demo.made_up_telegram_id() for _ in range(200)}
    assert len(ids) == 200 and all(i < 0 for i in ids)


def user(demo_until: datetime | None) -> User:
    return User(
        id=UserId(uuid4()),
        telegram_user_id=-5 if demo_until else 5,
        telegram_chat_id=None,
        timezone="UTC",
        home_currency="SGD",
        role=Role.MEMBER,
        created_at=NOW,
        demo_expires_at=demo_until,
    )


def test_forbid_refuses_a_demo_with_the_next_step_and_nobody_else() -> None:
    forbid(user(None), "Inviting people")
    with pytest.raises(Forbidden, match=r"Inviting people isn't part of the demo.*Telegram"):
        forbid(user(NOW + timedelta(hours=1)), "Inviting people")


def test_the_limit_messages_say_the_demo_limit_and_the_way_on() -> None:
    for text in (*demo.LIMIT_REACHED.values(), demo.CAP_REACHED):
        assert "demo limit is reached" in text and "Telegram" in text
