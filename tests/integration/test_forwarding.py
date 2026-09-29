"""Forwarding addresses: made when the user asks, read like any mailbox, with the
provider's confirmation and the user's test email answered in chat."""

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import email as email_cases
from nexus.application import notifications as notify_cases
from nexus.domain.email import ConnectionStatus, EmailConnection
from nexus.domain.ledger import User
from nexus.domain.notifications import Frequency
from nexus.infra.db.tables import jobs
from tests.fakes import NOW, FakeEmailReader, FakeForwarding, fake_email
from tests.integration.conftest import UowFactory
from tests.integration.test_email import CIPHER, GRAB, messages, person, statuses

pytestmark = pytest.mark.integration


def runtime(forwarding: FakeForwarding) -> email_cases.EmailRuntime:
    return email_cases.EmailRuntime(
        None, FakeEmailReader(), CIPHER, "https://nexus.test", forwarding=forwarding
    )


async def sweep(
    uow: UowFactory, user: User, forwarding: FakeForwarding, *, at: Any
) -> email_cases.SweepResult:
    [connection] = await current(uow, user)
    return await email_cases.sweep(
        uow, forwarding, FakeEmailReader(), CIPHER, None, user, connection, now=at
    )


async def current(uow: UowFactory, user: User) -> list[EmailConnection]:
    async with uow() as tx:
        return await tx.email.list_connections(user.id)


async def test_one_address_per_user_made_on_first_ask(uow: UowFactory) -> None:
    ann, ben = await person(uow, 1), await person(uow, 2)
    forwarding = FakeForwarding()
    first = await email_cases.set_up_forwarding(uow, forwarding, CIPHER, ann, now=NOW)
    again = await email_cases.set_up_forwarding(uow, forwarding, CIPHER, ann, now=NOW)
    other = await email_cases.set_up_forwarding(uow, forwarding, CIPHER, ben, now=NOW)
    assert first.id == again.id and first.address == again.address
    assert other.address != first.address
    assert first.synced_until == NOW  # a new address has nothing to look back on
    assert CIPHER.decrypt(first.token) == "inbox-1"
    found = await email_cases.forwarding_address(uow(), ann.id)
    assert found is not None and found.address == first.address


async def test_forwarded_receipts_are_read_like_any_mailbox(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await notify_cases.set_frequency(uow(), user.id, Frequency.INSTANT, now=NOW)
    forwarding = FakeForwarding()
    await email_cases.set_up_forwarding(uow, forwarding, CIPHER, user, now=NOW)
    arrived = NOW + timedelta(minutes=5)
    forwarding.emails["m1"] = fake_email("m1", "Fwd: Grab receipt", GRAB, at=arrived)
    result = await sweep(uow, user, forwarding, at=NOW + timedelta(minutes=10))
    assert (result.read, result.waiting, result.first) == (1, 1, False)
    assert await statuses(uow, user) == {"m1": "pending"}
    [question] = await messages(engine)
    assert question["text"].startswith("📧 From your email: 18.50 SGD at Grab")
    [connection] = await current(uow, user)
    assert connection.last_received_at == arrived


async def test_the_providers_confirmation_and_a_test_email_are_answered_in_chat(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    forwarding = FakeForwarding()
    await email_cases.set_up_forwarding(uow, forwarding, CIPHER, user, now=NOW)
    forwarding.emails["c1"] = fake_email(
        "c1",
        "(#123456789) Gmail Forwarding Confirmation - Receive Mail from ann@gmail.com",
        "Click https://mail-settings.google.com/mail/vf-abc to allow.",
        at=NOW + timedelta(minutes=1),
        sender="forwarding-noreply@google.com",
    )
    forwarding.emails["t1"] = fake_email(
        "t1", "Nexus test receipt", "hello", at=NOW + timedelta(minutes=2), sender="ann@gmail.com"
    )
    await sweep(uow, user, forwarding, at=NOW + timedelta(minutes=5))
    confirmation, test = await messages(engine)
    assert "Confirmation code: 123456789" in confirmation["text"]
    assert confirmation["buttons"] == [
        [
            {
                "label": "Confirm forwarding",
                "data": "url:https://mail-settings.google.com/mail/vf-abc",
            }
        ]
    ]
    assert test["text"].startswith("✅ Your test email from ann@gmail.com arrived.")
    # Neither is read as a receipt, and neither is answered twice.
    assert await statuses(uow, user) == {"c1": "not_receipt", "t1": "not_receipt"}
    await sweep(uow, user, forwarding, at=NOW + timedelta(minutes=20))
    assert len(await messages(engine)) == 2


async def test_testing_checks_again_within_minutes(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    await email_cases.test_setup(uow(), user.id, now=NOW)
    async with engine.connect() as db:
        rows = (
            await db.execute(select(jobs.c.run_at).where(jobs.c.kind == email_cases.SWEEP_JOB))
        ).all()
    assert sorted(r.run_at for r in rows) == [NOW + timedelta(minutes=m) for m in (1, 3, 6)]


async def test_a_quiet_address_gets_one_nudge(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    forwarding = FakeForwarding()
    await email_cases.set_up_forwarding(uow, forwarding, CIPHER, user, now=NOW)
    await sweep(uow, user, forwarding, at=NOW + timedelta(days=13))
    assert await messages(engine) == []
    await sweep(uow, user, forwarding, at=NOW + timedelta(days=14))
    await sweep(uow, user, forwarding, at=NOW + timedelta(days=15))
    [nudge] = await messages(engine)
    assert nudge["text"].startswith(
        "I haven't received any forwarded emails at nexus-inbox-1@agentmail.test "
        "since you set it up."
    )


async def test_disconnecting_deletes_the_address(uow: UowFactory) -> None:
    user = await person(uow)
    forwarding = FakeForwarding()
    connection = await email_cases.set_up_forwarding(uow, forwarding, CIPHER, user, now=NOW)
    await email_cases.disconnect(uow, runtime(forwarding), user.id, connection.id)
    assert forwarding.deleted == ["inbox-1"]
    assert await current(uow, user) == []
    # Asking again makes a working address.
    fresh = await email_cases.set_up_forwarding(uow, forwarding, CIPHER, user, now=NOW)
    assert fresh.status is ConnectionStatus.ACTIVE


def test_steps_for_each_provider_name_the_address() -> None:
    for provider in email_cases.FORWARDING_PROVIDERS:
        steps = email_cases.forwarding_steps(provider, "nexus-x@agentmail.test")
        assert "nexus-x@agentmail.test" in steps
        assert steps.startswith("1. ")
    assert "Subject includes" in email_cases.forwarding_steps("outlook", "a@b.test")
    assert email_cases.forwarding_steps("hotmail", "a@b.test") == email_cases.forwarding_steps(
        "other", "a@b.test"
    )
