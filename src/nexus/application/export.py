"""Export all of one user's data as a zip: their own rows only, readable, no secrets.

Built from ``application.user_data.AREAS`` (what is in each JSON file) and read through the
unit of work, so what is exported is what "Delete my data" removes. The ledger CSV is the
one the Ledger page already exports and is passed in. Receipt photos go in under ``files/``
when they total at most ``FILES_LIMIT_BYTES``; above that ``files.json`` lists them with
short-lived signed links instead.
"""

import json
import logging
import zipfile
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from tempfile import SpooledTemporaryFile
from typing import IO, Any
from uuid import UUID

from nexus.application.ports import ReceiptStore, UnitOfWork
from nexus.application.user_data import AREAS, Area, exported_tables
from nexus.domain.ledger import User, UserId
from nexus.domain.receipts import CONTENT_TYPES

log = logging.getLogger(__name__)

type UowFactory = Callable[[], UnitOfWork]
type Row = dict[str, Any]

# Photos go in the zip up to this much in all; above it they are listed with links.
FILES_LIMIT_BYTES = 50 * 1024 * 1024
# How long the signed links in files.json work when the photos are too many to include.
LINK_TTL = timedelta(hours=1)
# The zip is built in memory up to this size, then on disk.
_SPOOL_BYTES = 8 * 1024 * 1024
# One object, not a list, for tables that hold one row per user.
_SINGLE = {"users": "profile", "salary_schedules": "salary_schedule",
           "notification_settings": "settings"}  # fmt: skip


def _plain(value: object) -> str:
    """JSON for what JSON has no type for: money and quantities as exact strings, dates in
    ISO 8601."""
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    raise TypeError(f"cannot export {type(value).__name__}")


def _json(content: object) -> bytes:
    return json.dumps(content, default=_plain, indent=2, ensure_ascii=False).encode() + b"\n"


def file_name(receipt: Row) -> str:
    return f"receipt-{receipt['id']}.{CONTENT_TYPES.get(receipt['content_type'], 'bin')}"


async def _read(uow: UowFactory, user_id: UserId) -> dict[str, list[Row]]:
    async with uow() as tx:
        return {table: await tx.user_data.rows(user_id, table) for table in exported_tables()}


def _group(rows: list[Row], key: str) -> defaultdict[Any, list[Row]]:
    grouped: defaultdict[Any, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def _without(row: Row, *columns: str) -> Row:
    return {k: v for k, v in row.items() if k not in columns}


def _trips(data: dict[str, list[Row]], me: UserId) -> Row:
    """Each trip with what hangs off it. Other people's ids are left out, and so is what you
    did on someone else's trip: its words are theirs."""
    bookings = _group(data["trip_bookings"], "trip_id")
    covers = _group(data["trip_covers"], "trip_id")
    paid = _group(data["trip_paid_by_others"], "trip_id")
    links = _group(data["trip_links"], "trip_id")
    changes = _group(data["trip_changes"], "trip_id")
    shares = {row["trip_id"]: _without(row, "trip_id", "user_id") for row in data["trip_shares"]}
    members = _group([m for m in data["trip_members"] if m["owner_id"] == me], "trip_id")
    activity = _group([a for a in data["trip_activity"] if a["owner_id"] == me], "trip_id")
    trips = []
    for trip in data["trips"]:
        key = trip["id"]
        trips.append(
            {
                **trip,
                "bookings": bookings[key],
                "covers": covers[key],
                "paid_by_others": paid[key],
                "expense_links": links[key],
                "changes": changes[key],
                "share_link": shares.get(key),
                "members_added": [{"added_at": m["added_at"]} for m in members[key]],
                "activity": [
                    {"summary": a["summary"], "at": a["at"], "by_you": a["actor_id"] == me}
                    for a in activity[key]
                ],
            }
        )
    return {
        "trips": trips,
        "bookings_without_a_trip": [b for b in data["trip_bookings"] if b["trip_id"] is None],
        "member_of": [
            {"trip_id": m["trip_id"], "added_at": m["added_at"]}
            for m in data["trip_members"]
            if m["member_id"] == me
        ],
    }


def _area(area: Area, data: dict[str, list[Row]], me: UserId, files: dict[UUID, str]) -> Row:
    if area.file == "trips.json":
        return _trips(data, me)
    out: Row = {}
    for table in area.tables:
        rows = data[table]
        if table == "receipts":
            # The storage key is internal; the file's place in the zip says where it is.
            rows = [{**_without(r, "object_key"), "file": files.get(r["id"])} for r in rows]
        if table in _SINGLE:
            out[_SINGLE[table]] = rows[0] if rows else None
        else:
            out[table] = rows
    return out


def readme(now: datetime) -> str:
    lines = [
        "Your Nexus data",
        f"Exported {now:%Y-%m-%d %H:%M} UTC.",
        "",
        "This zip holds your own data only. It leaves out market data, prices, news, quotes",
        "and exchange rates (shared by everyone), and anything secret: sign-in sessions, email",
        "access grants, one-time links, invite and share-link tokens.",
        "",
        "How to read it",
        "- Dates and times are ISO 8601 (2026-10-24, or 2026-10-24T09:30:00+00:00 in UTC).",
        '- Money is an exact string next to its currency code, for example "amount": "12.5000"',
        '  beside "currency": "SGD". It is never a floating-point number.',
        "- Ids are UUIDs; a row names the others it belongs to (a split has its transaction_id).",
        "",
        "Files",
        "- ledger.csv: your ledger, exactly as the Export CSV button on the Ledger page",
        "  makes it (your latest 10,000 transactions; transactions.json has all of them).",
    ]
    lines += [f"- {area.file}: {area.about}" for area in AREAS]
    lines += [
        "- files.json: your stored files (receipt photos). They are in the files/ folder when",
        "  they are 50 MB or less in all; otherwise files.json lists each with a link that stops",
        "  working after an hour.",
        "- README.txt: this file.",
        "",
    ]
    return "\n".join(lines)


async def _files(
    store: ReceiptStore | None, receipts: list[Row], now: datetime, zf: zipfile.ZipFile
) -> list[Row]:
    """Put the receipt files in the zip, or describe them with links. Returns files.json's
    entries."""
    total = sum(r["size_bytes"] for r in receipts)
    include = store is not None and total <= FILES_LIMIT_BYTES
    entries: list[Row] = []
    for r in receipts:
        name = file_name(r)
        entry: Row = {
            "name": name,
            "receipt_id": r["id"],
            "transaction_id": r["transaction_id"],
            "content_type": r["content_type"],
            "size_bytes": r["size_bytes"],
            "stored_at": r["created_at"],
            "in_zip": None,
            "link": None,
            "link_expires_at": None,
        }
        if store is not None and include:
            try:
                data = await store.get(r["object_key"])
            except Exception as exc:  # a missing or unreadable file must not fail the export
                log.warning("could not read a stored file for an export (%s)", type(exc).__name__)
                entry["note"] = "could not be read from storage"
            else:
                info = zipfile.ZipInfo(f"files/{name}", date_time=_zip_time(now))
                zf.writestr(info, data, compress_type=zipfile.ZIP_STORED)
                entry["in_zip"] = info.filename
        elif store is not None:
            entry["link"] = store.download_url(r["object_key"], filename=name, expires=LINK_TTL)
            entry["link_expires_at"] = now + LINK_TTL
        entries.append(entry)
    return entries


def _zip_time(now: datetime) -> tuple[int, int, int, int, int, int]:
    t = now.timetuple()
    return (max(t.tm_year, 1980), t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


async def build_export(
    uow: UowFactory,
    store: ReceiptStore | None,
    user: User,
    *,
    ledger_csv: str,
    now: datetime,
) -> IO[bytes]:
    """The zip, rewound and ready to read; the caller closes it."""
    data = await _read(uow, user.id)
    receipts = data["receipts"]
    archive = SpooledTemporaryFile(max_size=_SPOOL_BYTES)
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:

            def add(name: str, content: bytes) -> None:
                zf.writestr(zipfile.ZipInfo(name, date_time=_zip_time(now)), content,
                            compress_type=zipfile.ZIP_DEFLATED)  # fmt: skip

            entries = await _files(store, receipts, now, zf)
            included = {e["receipt_id"]: e["in_zip"] for e in entries if e["in_zip"]}
            add("README.txt", readme(now).encode())
            add("ledger.csv", ledger_csv.encode())
            for area in AREAS:
                add(area.file, _json(_area(area, data, user.id, included)))
            add(
                "files.json",
                _json(
                    {
                        "included_in_zip": any(e["in_zip"] for e in entries),
                        "total_bytes": sum(r["size_bytes"] for r in receipts),
                        "limit_bytes": FILES_LIMIT_BYTES,
                        "files": entries,
                    }
                ),
            )
    except BaseException:
        archive.close()
        raise
    archive.seek(0)
    return archive
