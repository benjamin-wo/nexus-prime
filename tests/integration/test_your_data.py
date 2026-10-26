"""Your data: "Export all my data" and "Delete my data" through the real app. Every user here
has a row in every table that can hold one, so a table the export or the delete missed shows.
Every name and figure is made up."""

import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import Response
from sqlalchemy import ColumnElement, Table, Text, func, insert, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from nexus.agent.graph import thread_id
from nexus.application import erasure, export
from nexus.application import ops as ops_app
from nexus.application.user_data import AREAS, owned_tables
from nexus.application.users import get_user as fetch_user
from nexus.domain.ledger import Role, User, UserId
from nexus.infra.crypto.fernet import FernetCipher
from nexus.infra.db import user_data
from nexus.infra.db.tables import metadata, users
from nexus.infra.db.uow import SqlUnitOfWork
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.test_web_api import (
    MEMBER,
    ORIGIN,
    OWNER,
    TEST_KEY,
    Browser,
    World,
    owner_and_invite,
)

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

CIPHER = FernetCipher(TEST_KEY)
# Values that must never reach an export: the secrets seeded for each user.
SECRET = re.compile(r"token|secret|password|passwd|csrf|hash", re.IGNORECASE)


@dataclass
class Seeded:
    user: UUID
    tag: str  # in every text the user wrote
    trip: UUID
    transaction: UUID
    receipt_keys: list[str]
    gmail_token: str
    inbox: str
    secrets: list[str]


def _tag(user: UUID) -> str:
    return f"zz{str(user)[:6]}"


async def seed(world: World, user: UUID, other: UUID) -> Seeded:
    """One row for ``user`` in every table that can hold one, and the rows that link them to
    ``other``: a member of their trip, and someone who acted on it."""
    tag = _tag(user)
    now = NOW
    uid = uuid4
    secrets = [f"secret-{tag}-{n}" for n in range(8)]
    async with world.engine.begin() as db:

        async def add(table: Table, **values: Any) -> None:
            await db.execute(insert(table).values(**values))

        t = metadata.tables
        chat = await db.scalar(select(users.c.telegram_chat_id).where(users.c.id == user))
        category = await db.scalar(
            select(t["categories"].c.id).where(t["categories"].c.user_id == user).limit(1)
        )
        spending = await db.scalar(
            select(t["wallets"].c.id).where(
                t["wallets"].c.user_id == user, t["wallets"].c.kind == "spending"
            )
        )
        savings, rule, tx, tx_in, tx_move, tx_gone = uid(), uid(), uid(), uid(), uid(), uid()
        await add(t["wallets"], id=savings, user_id=user, name=f"Savings {tag}", kind="savings")
        await add(
            t["category_rules"],
            id=rule,
            user_id=user,
            pattern=f"grab {tag}",
            category_id=category,
            explanation=f"you said so {tag}",
            created_at=now,
            updated_at=now,
        )
        common = dict(
            user_id=user,
            currency="SGD",
            occurred_at=now,
            status="confirmed",
            source="manual",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["transactions"],
            id=tx,
            direction="out",
            amount=Decimal("12.50"),
            counterparty=f"Kopi Corner {tag}",
            notes=f"note {tag}",
            category_id=category,
            category_rule_id=rule,
            **common,
        )
        await add(t["transactions"], id=tx_in, direction="in", amount=Decimal("100"), **common)
        await add(
            t["transactions"],
            id=tx_move,
            direction="move",
            amount=Decimal("50"),
            from_wallet_id=spending,
            to_wallet_id=savings,
            **common,
        )
        await add(
            t["transactions"],
            id=tx_gone,
            direction="out",
            amount=Decimal("3"),
            deleted_at=now,
            counterparty=f"Deleted {tag}",
            **common,
        )
        keys = []
        for transaction in (tx, None):
            receipt = uid()
            key = f"receipts/{user}/{receipt}"
            keys.append(key)
            data = f"jpeg-{tag}-{len(keys)}".encode()
            await world.bucket.put(key, data, "image/jpeg")
            await add(
                t["receipts"],
                id=receipt,
                user_id=user,
                transaction_id=transaction,
                object_key=key,
                content_type="image/jpeg",
                size_bytes=len(data),
                created_at=now,
            )
        await add(
            t["transaction_sources"],
            user_id=user,
            source="email",
            external_id=tag,
            transaction_id=tx,
        )
        await add(
            t["transaction_revisions"],
            user_id=user,
            transaction_id=tx,
            kind="create",
            created_at=now,
        )
        split = uid()
        await add(
            t["splits"],
            id=split,
            user_id=user,
            transaction_id=tx,
            participant_name=f"Ann {tag}",
            share_amount=Decimal("5"),
        )
        await add(
            t["settlements"],
            id=uid(),
            user_id=user,
            split_id=split,
            income_transaction_id=tx_in,
            amount=Decimal("5"),
        )
        first, second = sorted((tx, tx_in))
        await add(
            t["duplicate_dismissals"],
            user_id=user,
            first_id=first,
            second_id=second,
            created_at=now,
        )
        await add(
            t["capability_gaps"],
            user_id=user,
            request=f"book me a flight {tag}",
            intent="book",
            channel="web",
        )
        budget = uid()
        await add(
            t["budgets"],
            id=budget,
            user_id=user,
            amount=Decimal("500"),
            currency="SGD",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["budgets"],
            id=uid(),
            user_id=user,
            category_id=category,
            amount=Decimal("80"),
            currency="SGD",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["budget_alerts"],
            budget_id=budget,
            period=date(2026, 9, 1),
            threshold=50,
            user_id=user,
            reached_at=now,
        )
        bill = uid()
        await add(
            t["bills"],
            id=bill,
            user_id=user,
            name=f"Rent {tag}",
            amount=Decimal("1500"),
            currency="SGD",
            cadence="monthly",
            anchor=date(2026, 9, 1),
            created_at=now,
        )
        await add(
            t["bill_occurrences"], id=uid(), user_id=user, bill_id=bill, due=date(2026, 10, 1)
        )
        await add(
            t["salary_schedules"],
            user_id=user,
            rule="monthly_day",
            day=25,
            amount=Decimal("4000"),
            currency="SGD",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["subscriptions"],
            id=uid(),
            user_id=user,
            key=f"netflix-{tag}",
            name=f"Netflix {tag}",
            cadence="monthly",
            amount=Decimal("15"),
            currency="SGD",
            last_charged_on=date(2026, 9, 1),
            status="active",
            created_at=now,
            updated_at=now,
        )
        await add(t["notification_settings"], user_id=user, frequency="daily", updated_at=now)
        await add(
            t["notifications"],
            id=uid(),
            user_id=user,
            kind="budget_alert",
            level="now",
            text=f"Budget {tag}",
            created_at=now,
            status="sent",
            sent_at=now,
        )
        await add(
            t["memories"],
            id=uid(),
            user_id=user,
            kind="fact",
            text=f"likes tea {tag}",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["voice_settings"],
            user_id=user,
            preset="chill",
            emoji="some",
            length="short",
            humour="light",
            note=f"call me boss {tag}",
            updated_at=now,
        )
        await add(
            t["split_habits"],
            id=uid(),
            user_id=user,
            person=f"Ann {tag}",
            applies_to="Dining Out",
            share=Decimal("0.5"),
            created_at=now,
        )
        await add(t["chat_log"], user_id=user, role="user", text=f"hello {tag}", created_at=now)
        await add(
            t["holdings"],
            id=uid(),
            user_id=user,
            symbol="NVDA",
            quantity=Decimal("3"),
            average_cost=Decimal("100"),
            currency="USD",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["holding_drafts"],
            id=uid(),
            user_id=user,
            positions=[],
            status="waiting",
            created_at=now,
        )
        await add(
            t["market_alerts"],
            id=uid(),
            user_id=user,
            symbol="NVDA",
            kind="big_move",
            day=date(2026, 9, 25),
            text=f"NVDA moved {tag}",
            created_at=now,
        )
        await add(
            t["trades"],
            id=uid(),
            user_id=user,
            symbol="NVDA",
            side="buy",
            quantity=Decimal("3"),
            price=Decimal("100"),
            currency="USD",
            traded_on=date(2026, 9, 1),
            created_at=now,
        )
        await add(
            t["dividends"],
            id=uid(),
            user_id=user,
            symbol="NVDA",
            ex_date=date(2026, 9, 5),
            per_share=Decimal("0.5"),
            currency="USD",
            shares=Decimal("3"),
            created_at=now,
        )
        await add(t["watchlist"], id=uid(), user_id=user, symbol="MSFT", created_at=now)
        first_plan = uid()
        plan = dict(
            user_id=user,
            symbol="MSFT",
            verdict="buy",
            as_of=date(2026, 9, 25),
            valid_until=date(2026, 10, 2),
            close=Decimal("400"),
            body={"note": tag},
            status="open",
            created_at=now,
        )
        await add(t["plans"], id=first_plan, **plan)
        await add(t["plans"], id=uid(), refreshed_from=first_plan, **plan)
        await add(
            t["department_runs"],
            id=uid(),
            user_id=user,
            department="investment",
            kind="plan",
            title=f"Plan {tag}",
            status="done",
            task={},
            outputs={},
            steps_done=1,
            steps_total=1,
            progress="done",
            spent=Decimal("0"),
            created_at=now,
            updated_at=now,
        )
        await add(
            t["statement_mappings"],
            id=uid(),
            user_id=user,
            name=f"Bank {tag}",
            header_key=f"k-{tag}",
            mapping={},
            created_at=now,
            updated_at=now,
        )
        await add(
            t["statement_imports"],
            id=uid(),
            user_id=user,
            file_name=f"{tag}.csv",
            transaction_ids=[],
            created_at=now,
        )
        for n, payload in enumerate(
            ({"user_id": str(user), "text": tag}, {"chat_id": chat, "message_id": 7})
        ):
            await add(
                t["jobs"],
                kind="notify.send",
                dedupe_key=f"seed:{tag}:{n}",
                payload=payload,
                run_at=now + timedelta(days=1),
                status="pending",
            )
        gmail, forward = uid(), uid()
        gmail_token, inbox = f"refresh-{tag}", f"inbox-{tag}"
        await add(
            t["email_connections"],
            id=gmail,
            user_id=user,
            provider="gmail",
            address=f"{tag}@gmail.example",
            token=CIPHER.encrypt(gmail_token),
            status="active",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["email_connections"],
            id=forward,
            user_id=user,
            provider="forward",
            address=f"{tag}@forward.example",
            token=CIPHER.encrypt(inbox),
            status="active",
            created_at=now,
            updated_at=now,
        )
        await add(
            t["inbound_emails"],
            id=uid(),
            user_id=user,
            connection_id=gmail,
            provider_message_id=f"m-{tag}",
            received_at=now,
            sender=f"shop@{tag}.example",
            subject=f"Receipt {tag}",
            status="logged",
            transaction_id=tx,
            created_at=now,
        )
        await add(
            t["email_links"],
            id=uid(),
            user_id=user,
            token_hash=secrets[0],
            expires_at=now,
            created_at=now,
        )
        trip = uid()
        await add(
            t["trips"],
            id=trip,
            user_id=user,
            destination=f"Tokyo {tag}",
            start_on=date(2026, 12, 10),
            end_on=date(2026, 12, 18),
            currency="JPY",
            home_currency="SGD",
            budget=Decimal("2000"),
            companions=["Ann"],
            planned={},
            created_at=now,
            updated_at=now,
            todos=[{"id": "1", "text": f"passport {tag}", "due": None, "done": False}],
            stops=[{"name": "Tokyo", "start": "2026-12-10", "end": "2026-12-18"}],
        )
        await add(t["trip_shares"], trip_id=trip, user_id=user, token=secrets[1], created_at=now)
        booking = uid()
        await add(
            t["trip_bookings"],
            id=booking,
            user_id=user,
            trip_id=trip,
            kind="activity",
            title=f"Dinner {tag}",
            start_on=date(2026, 12, 11),
            details={"kind": "activity", "name": f"Dinner {tag}", "day": "2026-12-11"},
            amount=Decimal("300"),
            currency="JPY",
            created_at=now,
        )
        await add(
            t["trip_bookings"],
            id=uid(),
            user_id=user,
            trip_id=None,
            kind="activity",
            title=f"Idea {tag}",
            details={"kind": "activity", "name": f"Idea {tag}"},
            created_at=now,
        )
        await add(
            t["trip_covers"],
            id=uid(),
            user_id=user,
            trip_id=trip,
            kind="insurance",
            name=f"Cover {tag}",
            cost_amount=Decimal("40"),
            cost_currency="SGD",
            logged_transaction_id=tx,
            created_at=now,
            updated_at=now,
        )
        await add(
            t["trip_paid_by_others"],
            id=uid(),
            user_id=user,
            trip_id=trip,
            person=f"Alex {tag}",
            amount=Decimal("460"),
            currency="SGD",
            paid_on=date(2026, 12, 11),
            created_at=now,
        )
        await add(
            t["trip_links"],
            user_id=user,
            trip_id=trip,
            transaction_id=tx,
            included=True,
            created_at=now,
        )
        await add(
            t["trip_changes"],
            id=uid(),
            user_id=user,
            trip_id=trip,
            booking_id=booking,
            kind="add",
            created_at=now,
        )
        await add(t["trip_reminders"], user_id=user, key=f"passport:{tag}", sent_at=now)
        # The other person: a member of this trip who changed it, and the invite they used.
        invite = uid()
        await add(
            t["trip_invites"],
            id=invite,
            token_hash=secrets[2],
            trip_id=trip,
            owner_id=user,
            created_at=now,
            expires_at=now + timedelta(days=7),
            redeemed_at=now,
            redeemed_by=other,
        )
        await add(
            t["trip_invites"],
            id=uid(),
            token_hash=secrets[3],
            trip_id=trip,
            owner_id=user,
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        await add(
            t["trip_members"],
            id=uid(),
            trip_id=trip,
            owner_id=user,
            member_id=other,
            added_at=now,
            added_by_invite=invite,
        )
        await add(
            t["trip_activity"],
            id=uid(),
            trip_id=trip,
            owner_id=user,
            actor_id=other,
            summary=f"added Dinner {tag}",
            at=now,
        )
        await add(
            t["trip_activity"],
            id=uid(),
            trip_id=trip,
            owner_id=user,
            actor_id=user,
            summary=f"added Lunch {tag}",
            at=now,
        )
        await add(
            t["invites"],
            id=uid(),
            token_hash=secrets[4],
            created_by=user,
            created_at=now,
            expires_at=now,
            redeemed_at=now,
            redeemed_by=other,
        )
        await add(
            t["invites"],
            id=uid(),
            token_hash=secrets[5],
            created_by=user,
            created_at=now,
            expires_at=now,
        )
        await add(
            t["web_sessions"],
            token_hash=secrets[6],
            user_id=user,
            csrf_token=secrets[7],
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
        thread = user_thread(user)
        await db.execute(
            text(
                "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, "
                "metadata) VALUES (:t, '', 'c1', '{}', '{}')"
            ),
            {"t": thread},
        )
        await db.execute(
            text(
                "INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type) "
                "VALUES (:t, '', 'messages', '1', 'msgpack')"
            ),
            {"t": thread},
        )
        await db.execute(
            text(
                "INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, "
                "idx, channel, type, blob) VALUES (:t, '', 'c1', 'task', 0, 'messages', "
                "'msgpack', '\\x00')"
            ),
            {"t": thread},
        )
    return Seeded(user, tag, trip, tx, keys, gmail_token, inbox, secrets)


def user_thread(user: UUID) -> str:
    return thread_id(UserId(user))


async def global_rows(world: World) -> None:
    """Shared rows: a job for nobody, and a quote."""
    async with world.engine.begin() as db:
        await db.execute(
            insert(metadata.tables["jobs"]).values(
                kind="budgets.sweep", dedupe_key="global", payload={}, run_at=NOW, status="pending"
            )
        )
        await db.execute(
            insert(metadata.tables["market_quotes"]).values(
                symbol="NVDA", price=1, prev_close=1, quoted_at=NOW, fetched_at=NOW
            )
        )


@dataclass
class Pair:
    world: World
    a: Browser  # the owner of the deployment
    b: Browser  # an invited member
    mine: Seeded
    theirs: Seeded


@pytest.fixture
async def pair(world: World) -> Pair:
    a, invite = await owner_and_invite(world)
    b = world.browser()
    assert (await b.login(MEMBER, invite)).status_code == 200
    ids: dict[int, UUID] = {}
    async with world.engine.connect() as db:
        for telegram_id in (OWNER, MEMBER):
            ids[telegram_id] = (
                await db.execute(select(users.c.id).where(users.c.telegram_user_id == telegram_id))
            ).scalar_one()
    mine = await seed(world, ids[OWNER], ids[MEMBER])
    theirs = await seed(world, ids[MEMBER], ids[OWNER])
    await global_rows(world)
    return Pair(world, a, b, mine, theirs)


# --- what is tied to a user, found from the schema rather than from the code under test ------


def tie_columns(table: Table) -> list[str]:
    if table.name == "users":
        return ["id"]
    names = {c.name for c in table.c if c.name in {"user_id", "owner_id"}}
    names |= {fk.parent.name for fk in table.foreign_keys if fk.column.table.name == "users"}
    return sorted(names)


async def count_for(world: World, user: UUID) -> dict[str, int]:
    """Rows tied to ``user`` in every table, however the table points at them."""
    counts: dict[str, int] = {}
    async with world.engine.connect() as db:
        for table in metadata.tables.values():
            columns = tie_columns(table)
            condition: ColumnElement[bool]
            if table.name == "jobs":
                condition = table.c.payload.cast(Text).like(f"%{user}%")
            elif columns:
                condition = or_(*[table.c[c] == user for c in columns])
            else:
                continue
            counts[table.name] = (
                await db.scalar(select(func.count()).select_from(table).where(condition))
            ) or 0
    return counts


async def own_counts(world: World, user: UUID) -> dict[str, int]:
    """Rows in the user's own tables (the ones with a user_id), for comparing before/after."""
    out = {}
    async with world.engine.connect() as db:
        for table in metadata.tables.values():
            if "user_id" in table.c or table.name == "users":
                column = table.c["user_id" if "user_id" in table.c else "id"]
                out[table.name] = (
                    await db.scalar(select(func.count()).select_from(table).where(column == user))
                ) or 0
    return out


# --- export ---------------------------------------------------------------------------------


def unzip(response: Response) -> zipfile.ZipFile:
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


def load(archive: zipfile.ZipFile, name: str) -> Any:
    return json.loads(archive.read(name))


def keys_of(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


async def test_seed_covers_every_table_that_can_hold_a_user(pair: Pair) -> None:
    """The fixture itself: both users have rows in every owned table, so the tests below can't
    pass by there being nothing to find."""
    for seeded in (pair.mine, pair.theirs):
        counts = await count_for(pair.world, seeded.user)
        empty = [name for name in owned_tables() if counts.get(name, 0) == 0]
        assert empty == []


async def test_export_is_a_zip_of_only_my_rows(pair: Pair) -> None:
    response = await pair.a.get("/api/me/export")
    assert response.headers["content-type"] == "application/zip"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="nexus-export-20260928.zip"'
    )
    assert response.headers["content-length"] == str(len(response.content))
    archive = unzip(response)
    names = set(archive.namelist())
    assert {"README.txt", "ledger.csv", "files.json"} | {a.file for a in AREAS} <= names
    everything = {n: archive.read(n).decode() for n in names if not n.startswith("files/")}

    # Every JSON file parses, and nothing of the other user's appears anywhere in the zip.
    for name in names:
        if name.endswith(".json"):
            load(archive, name)
    blob = "\n".join(everything.values())
    assert pair.theirs.tag not in blob
    assert str(pair.theirs.user) not in blob
    assert pair.mine.tag in blob
    for name in (a.file for a in AREAS):
        assert name in names

    # The ledger is the one the Ledger page exports.
    assert archive.read("ledger.csv").decode() == (await pair.a.get("/api/export.csv")).text

    # Row counts match the database for the user, deleted transactions included.
    counts = await count_for(pair.world, pair.mine.user)
    transactions = load(archive, "transactions.json")
    assert len(transactions["transactions"]) == counts["transactions"] == 4
    assert {tx["id"] for tx in transactions["transactions"]} >= {str(pair.mine.transaction)}
    assert any(tx["deleted_at"] for tx in transactions["transactions"])
    for area in AREAS:
        if area.file == "trips.json":
            continue
        content = load(archive, area.file)
        for table in area.tables:
            key = {
                "users": "profile",
                "salary_schedules": "salary_schedule",
                "notification_settings": "settings",
                "voice_settings": "voice",
            }.get(table, table)
            rows = content[key]
            assert len(rows) if isinstance(rows, list) else rows, table
            if isinstance(rows, list):
                assert len(rows) == counts[table], table


async def test_export_is_readable(pair: Pair) -> None:
    archive = unzip(await pair.a.get("/api/me/export"))
    rows = load(archive, "transactions.json")["transactions"]
    spent = next(r for r in rows if r["id"] == str(pair.mine.transaction))
    assert spent["amount"] == "12.5000" and spent["currency"] == "SGD"
    assert spent["occurred_at"] == "2026-09-28T04:00:00+00:00"
    assert spent["counterparty"] == f"Kopi Corner {pair.mine.tag}"
    bills = load(archive, "bills.json")
    assert bills["bills"][0]["anchor"] == "2026-09-01"
    assert bills["bill_occurrences"][0]["due"] == "2026-10-01"
    profile = load(archive, "profile.json")
    assert profile["profile"]["home_currency"] == "SGD"
    assert profile["salary_schedule"]["amount"] == "4000.0000"
    assert "README.txt" in archive.namelist()
    readme = archive.read("README.txt").decode()
    assert all(area.file in readme for area in AREAS)


async def test_export_trips_hold_what_hangs_off_them(pair: Pair) -> None:
    trips = load(unzip(await pair.a.get("/api/me/export")), "trips.json")
    [trip] = trips["trips"]
    assert trip["id"] == str(pair.mine.trip)
    assert trip["stops"][0]["name"] == "Tokyo"
    assert trip["todos"][0]["text"] == f"passport {pair.mine.tag}"
    assert [b["title"] for b in trip["bookings"]] == [f"Dinner {pair.mine.tag}"]
    assert trip["bookings"][0]["amount"] == "300.0000"
    assert trip["covers"][0]["cost_amount"] == "40.0000"
    assert trip["paid_by_others"][0]["person"] == f"Alex {pair.mine.tag}"
    assert len(trip["expense_links"]) == 1 and len(trip["changes"]) == 1
    assert trip["share_link"]["show_bookings"] is True
    assert len(trip["members_added"]) == 1
    assert sorted(a["by_you"] for a in trip["activity"]) == [False, True]
    assert len(trips["bookings_without_a_trip"]) == 1
    # Their membership on the other user's trip, but nothing of that trip itself.
    assert [m["trip_id"] for m in trips["member_of"]] == [str(pair.theirs.trip)]
    assert "your_changes_on_other_trips" not in trips


async def test_export_has_no_secrets(pair: Pair) -> None:
    archive = unzip(await pair.a.get("/api/me/export"))
    blob = "\n".join(archive.read(n).decode() for n in archive.namelist() if n.endswith("json"))
    for secret in [*pair.mine.secrets, pair.mine.gmail_token, pair.mine.inbox]:
        assert secret not in blob
    # Nor a column that looks like one.
    for name in archive.namelist():
        if name.endswith(".json"):
            assert [k for k in keys_of(load(archive, name)) if SECRET.search(k)] == [], name
    email = load(archive, "email.json")
    assert email["email_connections"][0]["address"].endswith("example")
    assert "object_key" not in blob


async def test_receipt_files_are_in_the_zip(pair: Pair) -> None:
    archive = unzip(await pair.a.get("/api/me/export"))
    stored = sorted(n for n in archive.namelist() if n.startswith("files/"))
    assert len(stored) == 2
    assert sorted(archive.read(n) for n in stored) == sorted(
        pair.world.bucket.objects[key][0] for key in pair.mine.receipt_keys
    )
    files = load(archive, "files.json")
    assert files["included_in_zip"] is True
    assert sorted(f["in_zip"] for f in files["files"]) == stored
    receipts = load(archive, "transactions.json")["receipts"]
    assert sorted(r["file"] for r in receipts) == stored
    assert not any("object_key" in r for r in receipts)


async def test_files_over_the_limit_are_listed_with_short_links(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "FILES_LIMIT_BYTES", 10)
    archive = unzip(await pair.a.get("/api/me/export"))
    assert not [n for n in archive.namelist() if n.startswith("files/")]
    files = load(archive, "files.json")
    assert files["included_in_zip"] is False and files["limit_bytes"] == 10
    assert len(files["files"]) == 2
    for entry in files["files"]:
        assert entry["in_zip"] is None
        assert entry["link"].startswith(f"https://bucket.test/receipts/{pair.mine.user}/")
        assert "expires=3600" in entry["link"]
        assert entry["link_expires_at"] == "2026-09-28T05:00:00+00:00"
        assert entry["stored_at"] == "2026-09-28T04:00:00+00:00"
        assert entry["name"].endswith(".jpg")


async def test_without_storage_files_are_listed_by_name_and_date(pair: Pair) -> None:
    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(pair.world.engine)

    user = await get_user(pair.world, pair.mine.user)
    file = await export.build_export(uow, None, user, ledger_csv="a,b\r\n", now=NOW)
    archive = zipfile.ZipFile(file)
    assert not [n for n in archive.namelist() if n.startswith("files/")]
    [first, _] = load(archive, "files.json")["files"]
    assert first["link"] is None and first["stored_at"] and first["name"]
    assert archive.read("ledger.csv") == b"a,b\r\n"
    file.close()


async def test_a_file_that_cannot_be_read_does_not_fail_the_export(pair: Pair) -> None:
    del pair.world.bucket.objects[pair.mine.receipt_keys[0]]
    archive = unzip(await pair.a.get("/api/me/export"))
    files = load(archive, "files.json")["files"]
    assert sorted(bool(f["in_zip"]) for f in files) == [False, True]
    assert [f["note"] for f in files if not f["in_zip"]] == ["could not be read from storage"]


async def test_export_is_refused_to_guests_and_the_signed_out_and_rate_limited(
    pair: Pair,
) -> None:
    assert (await pair.world.browser().get("/api/me/export")).status_code == 401
    await set_role(pair.world, MEMBER, Role.GUEST)
    assert (await pair.b.get("/api/me/export")).status_code == 403
    # Three an hour for each user.
    for _ in range(3):
        assert (await pair.a.get("/api/me/export")).status_code == 200
    refused = await pair.a.get("/api/me/export")
    assert refused.status_code == 429
    # Another user has their own allowance.
    await set_role(pair.world, MEMBER, Role.MEMBER)
    assert (await pair.b.get("/api/me/export")).status_code == 200


async def get_user(world: World, user: UUID) -> User:
    return await fetch_user(SqlUnitOfWork(world.engine), UserId(user))


async def set_role(world: World, telegram_id: int, role: Role) -> None:
    async with world.engine.begin() as db:
        await db.execute(
            update(users).where(users.c.telegram_user_id == telegram_id).values(role=role.value)
        )


# --- delete ---------------------------------------------------------------------------------


async def test_delete_needs_the_exact_word(pair: Pair) -> None:
    before = await count_for(pair.world, pair.mine.user)
    for body in (
        {"confirm": "delete"},
        {"confirm": " DELETE"},
        {"confirm": "DELETE "},
        {"confirm": ""},
        {"confirm": True},
        {},
        {"confirm": "DELETE", "also": "x"},
        None,
    ):
        response = await pair.a.send("POST", "/api/me/delete", body)
        assert response.status_code == 422, body
    assert await count_for(pair.world, pair.mine.user) == before
    assert (await pair.a.get("/api/me")).status_code == 200


async def test_delete_needs_csrf_and_our_origin_and_a_session(pair: Pair) -> None:
    before = await count_for(pair.world, pair.mine.user)
    body = {"confirm": "DELETE"}
    no_token = await pair.a.client.post("/api/me/delete", json=body, headers={"Origin": ORIGIN})
    assert no_token.status_code == 403
    wrong = await pair.a.send("POST", "/api/me/delete", body, **{"X-CSRF-Token": "nope"})
    assert wrong.status_code == 403
    cross = await pair.a.send("POST", "/api/me/delete", body, Origin="https://evil.test")
    assert cross.status_code == 403
    anonymous = await pair.world.browser().send("POST", "/api/me/delete", body)
    assert anonymous.status_code == 401
    # A GET is not a delete.
    assert (await pair.a.get("/api/me/delete")).status_code in {404, 405}
    assert await count_for(pair.world, pair.mine.user) == before


async def test_guests_cannot_delete(pair: Pair) -> None:
    await set_role(pair.world, MEMBER, Role.GUEST)
    refused = await pair.b.send("POST", "/api/me/delete", {"confirm": "DELETE"})
    assert refused.status_code == 403
    assert (await count_for(pair.world, pair.theirs.user))["users"] == 1


async def test_delete_removes_everything_of_mine_and_leaves_the_rest(
    pair: Pair, caplog: pytest.LogCaptureFixture
) -> None:
    world, me, them = pair.world, pair.mine, pair.theirs
    assert all(n > 0 for n in (await count_for(world, me.user)).values())
    theirs_before = await own_counts(world, them.user)
    my_chat = me.tag

    app_logger = logging.getLogger("nexus")
    app_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="nexus"):
            response = await pair.a.send("POST", "/api/me/delete", {"confirm": "DELETE"})
    finally:
        app_logger.removeHandler(caplog.handler)
    assert response.status_code == 204 and response.content == b""

    # The session cookie is cleared.
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("nexus_session=") and "Max-Age=0" in cookie
    assert (await pair.a.get("/api/me")).status_code == 401

    # Nothing tied to the user is left anywhere: not their rows, nor the rows linking others to
    # them.
    after = await count_for(world, me.user)
    assert {name: n for name, n in after.items() if n} == {}
    async with world.engine.connect() as db:
        assert await db.scalar(select(func.count()).where(users.c.id == me.user)) == 0
        threads = await db.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :t"),
            {"t": user_thread(me.user)},
        )
        assert threads == 0
        for table in ("checkpoint_blobs", "checkpoint_writes"):
            gone = await db.scalar(
                text(f"SELECT count(*) FROM {table} WHERE thread_id = :t"),  # noqa: S608
                {"t": user_thread(me.user)},
            )
            assert gone == 0

    # The other user is whole: their own rows are untouched (including the trip I was a member
    # of and the checkpoints of their chat), and what linked me to them is gone.
    assert await own_counts(world, them.user) == theirs_before
    mine_on_theirs = await count_for(world, them.user)
    assert mine_on_theirs["trips"] == 1 and mine_on_theirs["users"] == 1
    async with world.engine.connect() as db:
        members = await db.scalar(
            select(func.count())
            .select_from(metadata.tables["trip_members"])
            .where(metadata.tables["trip_members"].c.trip_id == them.trip)
        )
        assert members == 0  # I was the member
        mine = await db.scalar(
            select(func.count())
            .select_from(metadata.tables["trip_members"])
            .where(metadata.tables["trip_members"].c.trip_id == me.trip)
        )
        assert mine == 0
        theirs_checkpoint = await db.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :t"),
            {"t": user_thread(them.user)},
        )
        assert theirs_checkpoint == 1
        jobs = (await db.execute(text("SELECT dedupe_key FROM jobs ORDER BY dedupe_key"))).all()
        assert [j[0] for j in jobs] == sorted(["global", *(f"seed:{them.tag}:{n}" for n in (0, 1))])
        assert (
            await db.scalar(select(func.count()).select_from(metadata.tables["market_quotes"])) == 1
        )

    # Files: mine are gone, theirs stay.
    assert not [k for k in world.bucket.objects if k.startswith(f"receipts/{me.user}/")]
    assert sorted(world.bucket.objects) == sorted(them.receipt_keys)

    # Gmail access is revoked and the forwarding inbox deleted, theirs not.
    assert world.mailbox.revocations == [me.gmail_token]
    assert world.forwarding.deleted == [me.inbox]

    # My trip is gone for the person who was on it; theirs still opens for them.
    assert (await pair.b.get(f"/api/travel/trips/{me.trip}")).status_code == 404
    assert (await pair.b.get(f"/api/travel/trips/{them.trip}")).status_code == 200

    # One audit line: a hash and the trace, nothing personal.
    lines = [r.getMessage() for r in caplog.records if "user data deleted" in r.getMessage()]
    assert lines == [f"user data deleted (user {ops_app.user_ref(me.user)})"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert str(me.user) not in logged and my_chat not in logged and str(OWNER) not in logged


async def test_delete_goes_through_when_files_and_mailboxes_cannot_be_reached(
    pair: Pair, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    world = pair.world
    world.bucket.fail_deletes = True

    async def broken(refresh_token: str) -> None:
        raise OSError("provider down")

    monkeypatch.setattr(world.mailbox, "revoke", broken)
    monkeypatch.setattr(world.forwarding, "revoke", broken)
    app_logger = logging.getLogger("nexus")
    app_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="nexus"):
            response = await pair.a.send("POST", "/api/me/delete", {"confirm": "DELETE"})
    finally:
        app_logger.removeHandler(caplog.handler)
    assert response.status_code == 204
    left = await count_for(world, pair.mine.user)
    assert {name: n for name, n in left.items() if n} == {}
    messages = [r.getMessage() for r in caplog.records]
    assert any("2 stored files were not deleted" in m for m in messages)
    assert str(pair.mine.user) not in "\n".join(messages)


async def test_a_failed_delete_changes_nothing(pair: Pair, monkeypatch: pytest.MonkeyPatch) -> None:
    """One transaction: if a step fails, no row is gone and no file is touched."""
    world = pair.world
    before = await count_for(world, pair.mine.user)
    # Skipping the categories leaves the users row held by them.
    monkeypatch.setattr(
        user_data, "ERASE_ORDER", tuple(t for t in user_data.ERASE_ORDER if t != "categories")
    )
    user = await get_user(world, pair.mine.user)
    with pytest.raises(IntegrityError):
        await erasure.delete_user_data(
            lambda: SqlUnitOfWork(world.engine),
            user,
            chat_thread=user_thread(pair.mine.user),
            store=world.bucket,
            email=world.app.state.web.email,
        )
    assert await count_for(world, pair.mine.user) == before
    assert len(world.bucket.objects) == 4
    assert world.mailbox.revocations == [] and world.forwarding.deleted == []


async def test_deleting_twice_is_a_sign_in_problem_not_a_crash(pair: Pair) -> None:
    assert (await pair.a.send("POST", "/api/me/delete", {"confirm": "DELETE"})).status_code == 204
    assert (await pair.a.send("POST", "/api/me/delete", {"confirm": "DELETE"})).status_code == 401


async def test_a_deleted_member_can_come_back_only_with_a_new_invite(pair: Pair) -> None:
    assert (await pair.b.send("POST", "/api/me/delete", {"confirm": "DELETE"})).status_code == 204
    again = pair.world.browser()
    assert (await again.login(MEMBER)).status_code == 403
    # The owner is not locked out: signing in makes a fresh account.
    assert (await pair.a.send("POST", "/api/me/delete", {"confirm": "DELETE"})).status_code == 204
    fresh = pair.world.browser()
    assert (await fresh.login(OWNER)).status_code == 200
    assert (await fresh.get("/api/transactions")).json()["total"] == 0
