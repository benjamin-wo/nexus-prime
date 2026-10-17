"""Moves recognised by match words, through the web API: the import preview proposes them and
the import takes the user's choice per row, the Email page carries the wallet an email names
and can log it as a move, and likely moves are listed. Made-up names and figures only."""

from datetime import timedelta
from typing import Any

import pytest

from nexus.application import email as email_cases
from nexus.infra.crypto.fernet import FernetCipher
from nexus.infra.db.uow import SqlUnitOfWork
from tests.fakes import NOW, FakeEmailReader, fake_email
from tests.integration import test_web_api
from tests.integration.test_web_api import OWNER, TEST_KEY, Browser, World, user_id

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

CSV = (
    "Transaction Date,Description,Debit Amount,Credit Amount\n"
    "28 Sep 2026,KOPITIAM,4.20,\n"
    "27 Sep 2026,IBKR TOPUP,800.00,\n"
    "26 Sep 2026,Interactive Brokers WITHDRAWAL,,300.00\n"
)


async def add_ibkr(browser: Browser) -> dict[str, Any]:
    made = await browser.send(
        "POST",
        "/api/wallets",
        {"name": "IBKR", "kind": "investment", "match_words": ["ibkr", "interactive brokers"]},
    )
    assert made.status_code == 201
    wallet: dict[str, Any] = made.json()
    return wallet


async def test_the_import_preview_proposes_moves_and_the_import_follows_the_users_choice(
    world: World,
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await add_ibkr(owner)
    shown = (await owner.send("POST", "/api/imports/preview", {"csv": CSV})).json()
    kopitiam, topup, back = shown["rows"]
    assert (kopitiam["move_to"], kopitiam["move_from"]) == (None, None)
    assert kopitiam["category"] == "Other"
    assert topup["move_to"] == ibkr and topup["move_from"] is None and topup["category"] is None
    assert back["move_from"] == ibkr and back["move_to"] is None and back["category"] is None
    assert (await owner.get("/api/transactions")).json()["total"] == 0

    body = {
        "csv": CSV,
        "layout": shown["layout"],
        "include": [0, 1, 2],
        "file_name": "sept.csv",
        # The user switched the top-up back to an ordinary entry and made the first row a move.
        "moves": [
            {"row": 0, "as_move": ibkr["id"]},
            {"row": 1, "as_move": None},
            {"row": 2, "as_move": ibkr["id"]},
        ],
    }
    done = await owner.send("POST", "/api/imports", body)
    assert done.status_code == 201 and done.json()["added"] == 3
    items = {t["counterparty"]: t for t in (await owner.get("/api/transactions")).json()["items"]}
    assert items["KOPITIAM"]["direction"] == "move"
    assert items["KOPITIAM"]["to_wallet"]["name"] == "IBKR"
    assert items["IBKR TOPUP"]["direction"] == "out" and items["IBKR TOPUP"]["to_wallet"] is None
    assert items["Interactive Brokers WITHDRAWAL"]["from_wallet"]["name"] == "IBKR"
    assert items["Interactive Brokers WITHDRAWAL"]["source"] == "import"

    [record] = (await owner.get("/api/imports")).json()
    assert (await owner.send("POST", f"/api/imports/{record['id']}/undo")).json() == {"removed": 3}
    # Without `moves` (an older page) every row is an ordinary entry, as before. The undone
    # rows stay claimed, though, so nothing is added the second time.
    plain = {k: v for k, v in body.items() if k != "moves"}
    assert (await owner.send("POST", "/api/imports", plain)).json()["added"] == 0

    # A wallet that isn't the user's is refused.
    other = {**body, "moves": [{"row": 0, "as_move": "00000000-0000-0000-0000-000000000000"}]}
    assert (await owner.send("POST", "/api/imports", other)).status_code == 404


async def test_likely_moves_are_listed_and_converted_with_the_usual_route(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await add_ibkr(owner)
    assert (await owner.get("/api/wallets/likely-moves")).json() == []
    for day in ("2026-07-25", "2026-08-25", "2026-09-25"):
        await owner.send(
            "POST",
            "/api/transactions",
            {"direction": "out", "amount": "500", "counterparty": "Acme Holdings", "date": day},
        )
    await owner.send(
        "POST",
        "/api/transactions",
        {"direction": "out", "amount": "800", "counterparty": "IBKR", "date": "2026-09-20"},
    )
    found = (await owner.get("/api/wallets/likely-moves")).json()
    first = next(f for f in found if f["wallet"])
    rest = [f for f in found if not f["wallet"]]
    assert first["wallet"] == ibkr and first["reason"] == "matches 'ibkr'"
    assert first["transaction"]["counterparty"] == "IBKR"
    assert first["transaction"]["direction"] == "out"  # listing changes nothing
    assert [f["transaction"]["occurred_at"][:10] for f in found] == sorted(
        (f["transaction"]["occurred_at"][:10] for f in found), reverse=True
    )  # newest first
    assert len(rest) == 3
    assert rest[0]["reason"].startswith("looks like a regular transfer: 500.00 SGD")
    assert (await owner.get("/api/transactions")).json()["total"] == 4

    converted = await owner.send(
        "POST", f"/api/transactions/{first['transaction']['id']}/move", {"wallet_id": ibkr["id"]}
    )
    assert converted.json()["direction"] == "move"
    left = (await owner.get("/api/wallets/likely-moves")).json()
    assert [f["transaction"]["counterparty"] for f in left] == ["Acme Holdings"] * 3

    other = world.browser()
    assert (await other.get("/api/wallets/likely-moves")).status_code == 401


async def test_the_email_page_shows_the_wallet_an_email_names_and_logs_it_as_a_move(
    world: World,
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await add_ibkr(owner)
    me = await user_id(world, OWNER)

    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(world.engine)

    token = await email_cases.create_link(uow(), (await _user(world, me)), now=NOW)
    connection = await email_cases.finish_connect(
        uow, world.mailbox, FernetCipher(TEST_KEY), token=token, code="ok",
        redirect_uri="https://x/cb", now=NOW,
    )  # fmt: skip
    world.mailbox.emails["m1"] = fake_email(
        "m1", "Receipt for your top-up", "Merchant: IBKR\nTotal: 800.00", at=NOW - timedelta(days=1)
    )
    world.mailbox.emails["m2"] = fake_email(
        "m2", "Grab receipt", "Merchant: Grab\nTotal: 18.50", at=NOW - timedelta(days=1)
    )
    user = await _user(world, me)
    await email_cases.sweep(
        uow,
        world.mailbox,
        FakeEmailReader(),
        FernetCipher(TEST_KEY),
        None,
        user,
        connection,
        now=NOW,
    )
    page = (await owner.get("/api/email")).json()
    by_merchant = {e["merchant"]: e for e in page["emails"]}
    assert by_merchant["IBKR"]["move_wallet"] == "IBKR"
    assert by_merchant["IBKR"]["move_wallet_id"] == ibkr["id"]
    assert (
        by_merchant["Grab"]["move_wallet"] is None and by_merchant["Grab"]["move_wallet_id"] is None
    )
    assert by_merchant["IBKR"]["actionable"] is True  # the existing fields are unchanged

    email_id = by_merchant["IBKR"]["id"]
    assert (await owner.send("POST", f"/api/email/{email_id}/move", {})).status_code == 204
    [row] = (await owner.get("/api/transactions")).json()["items"]
    assert (row["direction"], row["source"], row["to_wallet"]["name"]) == ("move", "email", "IBKR")
    after = {e["merchant"]: e for e in (await owner.get("/api/email")).json()["emails"]}
    assert after["IBKR"]["status"] == "logged" and after["IBKR"]["move_wallet"] is None
    # An email that names no wallet needs one to be picked.
    grab = by_merchant["Grab"]["id"]
    assert (await owner.send("POST", f"/api/email/{grab}/move", {})).status_code == 422
    picked = await owner.send("POST", f"/api/email/{grab}/move", {"wallet_id": ibkr["id"]})
    assert picked.status_code == 204


async def _user(world: World, user_id_: Any) -> Any:
    async with SqlUnitOfWork(world.engine) as tx:
        return await tx.ledger.get_user(user_id_)
