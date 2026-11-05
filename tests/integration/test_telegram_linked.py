"""``telegram_linked`` on ``GET /api/me``'s user: whether a Telegram chat is linked, which Home's
"Get started" guide shows as its first step. Made-up data only."""

import pytest
from sqlalchemy import text

from tests.integration import test_web_api
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too


async def test_me_says_whether_telegram_is_linked(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    me = (await owner.get("/api/me")).json()
    # Signing in with Telegram links the chat.
    assert me["user"]["telegram_linked"] is True

    async with world.engine.begin() as db:
        await db.execute(
            text("UPDATE users SET telegram_chat_id = NULL WHERE telegram_user_id = :t"),
            {"t": OWNER},
        )
    me = (await owner.get("/api/me")).json()
    assert me["user"]["telegram_linked"] is False
