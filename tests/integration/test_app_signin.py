"""Signing in from the iOS app: the code the app shows, the bot's confirmation, the poll, and
the ordinary one-time login link it ends in. Every name and figure here is made up."""

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from nexus.application.device_signin import DEVICE_CODE_TTL
from nexus.application.limits import DEVICE_CLAIMS, DEVICE_STARTS
from nexus.channels.telegram.webhook import DEVICE_REFUSED, DEVICE_TOO_OFTEN, handle_update
from tests.integration.test_web_api import (
    MEMBER,
    ORIGIN,
    OWNER,
    World,
    owner_and_invite,
    world,
)

pytestmark = pytest.mark.integration
fixtures = (world,)

STRANGER = 4242  # never allow-listed


def message(telegram_id: int, number: int, body: str) -> dict[str, Any]:
    return {
        "update_id": number,
        "message": {
            "message_id": number,
            "from": {"id": telegram_id},
            "chat": {"id": telegram_id, "type": "private"},
            "text": body,
        },
    }


def press(telegram_id: int, number: int, data: str, sender: int | None = None) -> dict[str, Any]:
    return {
        "update_id": number,
        "callback_query": {
            "id": f"cb{number}",
            "from": {"id": sender or telegram_id},
            "data": data,
            "message": {"message_id": 9, "chat": {"id": telegram_id, "type": "private"}},
        },
    }


class Steps:
    def __init__(self, world: World) -> None:
        self.world = world
        self.number = 100

    def next(self) -> int:
        self.number += 1
        return self.number

    async def say(self, telegram_id: int, body: str) -> str:
        await handle_update(self.world.app.state.telegram, message(telegram_id, self.next(), body))
        return self.world.telegram.sent[-1].text

    async def tap(self, data: str, telegram_id: int = OWNER, sender: int | None = None) -> None:
        await handle_update(
            self.world.app.state.telegram, press(telegram_id, self.next(), data, sender)
        )


async def start(world: World, **headers: str) -> Any:
    return await world.browser().client.post(
        "/api/auth/device", headers={"Origin": ORIGIN, **headers}
    )


async def poll(world: World, poll_id: str) -> Any:
    return await world.browser().get(f"/api/auth/device/{poll_id}")


async def test_start_poll_approve_and_sign_in(world: World) -> None:
    answer = await start(world)
    assert answer.status_code == 200
    body = answer.json()
    code = body["code"]
    assert len(code) == 9 and code[4] == "-"
    assert body["expires_in"] == 300 and body["bot_username"] == "nexus_test_bot"
    assert "no-store" not in answer.headers.get("set-cookie", "")

    assert (await poll(world, body["poll_id"])).json() == {"status": "pending"}

    steps = Steps(world)
    await steps.say(OWNER, "hello?")  # first contact makes the account (and web access: owner)
    assert (await poll(world, body["poll_id"])).json() == {"status": "pending"}
    reply = await steps.say(OWNER, f"/app {code.lower()}")
    assert code in reply and "your own phone" in reply
    buttons = world.telegram.sent[-1].buttons
    assert buttons is not None and [b.label for b in buttons[0]] == ["Yes, sign in", "No"]
    # Asking is not approving.
    assert (await poll(world, body["poll_id"])).json() == {"status": "pending"}

    await steps.tap(buttons[0][0].data)
    approved = await poll(world, body["poll_id"])
    assert approved.status_code == 200
    assert approved.headers["cache-control"] == "no-store"
    path = approved.json()["login_path"]
    assert approved.json()["status"] == "approved" and path.startswith("/login/link/")
    assert (await poll(world, body["poll_id"])).status_code == 404  # handed over once

    browser = world.browser()
    landed = await browser.get(path)
    assert landed.status_code == 303 and landed.headers["location"] == "/"
    me = await browser.get("/api/me")
    assert me.status_code == 200 and me.json()["user"]["telegram_user_id"] == OWNER
    assert (await world.browser().get(path)).headers["location"] == "/login?error=link"


async def test_start_command_with_the_code_in_the_link(world: World) -> None:
    body = (await start(world)).json()
    steps = Steps(world)
    plain = body["code"].replace("-", "")
    reply = await steps.say(OWNER, f"/start app-{plain}")
    assert body["code"] in reply
    assert world.telegram.sent[-1].buttons is not None


async def test_a_different_telegram_user_cannot_approve(world: World) -> None:
    _, invite = await owner_and_invite(world)
    await world.browser().login(MEMBER, invite=invite)
    body = (await start(world)).json()
    steps = Steps(world)
    await steps.say(OWNER, f"/app {body['code']}")
    yes = world.telegram.sent[-1].buttons[0][0].data  # type: ignore[index]
    await steps.tap(yes, telegram_id=MEMBER)  # the member presses the owner's button
    assert (await poll(world, body["poll_id"])).json() == {"status": "pending"}
    # And a code the owner holds can't be taken over by claiming it from another account.
    assert await steps.say(MEMBER, f"/app {body['code']}") == DEVICE_REFUSED
    assert (await poll(world, body["poll_id"])).json() == {"status": "pending"}


async def test_no_cancels(world: World) -> None:
    body = (await start(world)).json()
    steps = Steps(world)
    await steps.say(OWNER, f"/app {body['code']}")
    no = world.telegram.sent[-1].buttons[0][1].data  # type: ignore[index]
    await steps.tap(no)
    assert (await poll(world, body["poll_id"])).status_code == 404
    assert "Nobody was signed in" in world.telegram.sent[-1].text


async def test_people_without_web_access_are_refused(world: World) -> None:
    body = (await start(world)).json()
    steps = Steps(world)
    reply = await steps.say(MEMBER, f"/app {body['code']}")  # allow-listed, never invited
    assert reply == "You need an invite to use the web app. Ask the owner for a link."
    assert (await poll(world, body["poll_id"])).json() == {"status": "pending"}
    assert await steps.say(STRANGER, f"/app {body['code']}") == "This is a private assistant."


async def test_unknown_and_expired_codes_get_the_same_refusal(world: World) -> None:
    body = (await start(world)).json()
    steps = Steps(world)
    await steps.say(OWNER, "hello?")
    unknown = await steps.say(OWNER, "/app 2345-6789")
    garbage = await steps.say(OWNER, "/app nonsense")
    world.clock.now += DEVICE_CODE_TTL + timedelta(seconds=1)
    expired = await steps.say(OWNER, f"/app {body['code']}")
    assert unknown == garbage == expired == DEVICE_REFUSED


async def test_an_old_confirmation_does_nothing(world: World) -> None:
    body = (await start(world)).json()
    steps = Steps(world)
    await steps.say(OWNER, f"/app {body['code']}")
    yes = world.telegram.sent[-1].buttons[0][0].data  # type: ignore[index]
    world.clock.now += DEVICE_CODE_TTL + timedelta(seconds=1)
    await steps.tap(yes)
    assert world.telegram.sent[-1].text == DEVICE_REFUSED
    assert (await poll(world, body["poll_id"])).status_code == 404


async def test_expired_and_unknown_polls_are_404(world: World) -> None:
    body = (await start(world)).json()
    assert (await poll(world, "no-such-request")).status_code == 404
    world.clock.now += DEVICE_CODE_TTL + timedelta(seconds=1)
    assert (await poll(world, body["poll_id"])).status_code == 404


async def test_losing_web_access_before_collecting_gives_no_link(
    world: World,
) -> None:
    _, invite = await owner_and_invite(world)
    await world.browser().login(MEMBER, invite=invite)
    body = (await start(world)).json()
    steps = Steps(world)
    await steps.say(MEMBER, f"/app {body['code']}")
    await steps.tap(world.telegram.sent[-1].buttons[0][0].data, telegram_id=MEMBER)  # type: ignore[index]
    async with world.engine.begin() as db:
        await db.execute(
            text("UPDATE users SET web_access_granted_at = NULL WHERE role = 'member'")
        )
    assert (await poll(world, body["poll_id"])).status_code == 404
    async with world.engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM login_links")) == 0


async def test_only_our_own_origin_may_ask_for_a_code(world: World) -> None:
    refused = await world.browser().client.post(
        "/api/auth/device", headers={"Origin": "https://evil.example"}
    )
    assert refused.status_code == 403


async def test_codes_are_limited_per_address(world: World) -> None:
    allowed, _ = DEVICE_STARTS[0]
    for _ in range(allowed):
        assert (await start(world)).status_code == 200
    assert (await start(world)).status_code == 429


async def test_polling_is_limited_per_request(world: World) -> None:
    body = (await start(world)).json()
    codes = [(await poll(world, body["poll_id"])).status_code for _ in range(8)]
    assert codes[:6] == [200] * 6 and codes[-1] == 429


async def test_guessing_codes_is_limited_per_user(world: World) -> None:
    steps = Steps(world)
    await steps.say(OWNER, "hello?")
    allowed, _ = DEVICE_CLAIMS[0]
    for _ in range(allowed):
        assert await steps.say(OWNER, "/app 2345-6789") == DEVICE_REFUSED
    assert await steps.say(OWNER, "/app 2345-6789") == DEVICE_TOO_OFTEN
