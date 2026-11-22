"""Web API: statement import."""

import asyncio
import base64
import binascii
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import Field

from nexus.application import demo as demo_cases
from nexus.application import statements as statement_cases
from nexus.application.statements import Verdict
from nexus.channels.web.money_api import WalletOut, wallet_out
from nexus.channels.web.security import (
    Auth,
    Runtime,
    demo_use,
    limit,
)
from nexus.channels.web.shapes import Model
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
)
from nexus.domain.statement_pdf import PAGE_BREAK
from nexus.domain.statements import AmountSign, DateOrder, Mapping, StatementImport
from nexus.infra.pdf.pages import page_images
from nexus.infra.pdf.text import PasswordNeeded, pdf_text

router = APIRouter(prefix="/api")

# --- statement import ----------------------------------------------------------------


class LayoutIn(Model):
    """Which column holds what, by position in the header row."""

    date: int = Field(ge=0)
    description: list[int] = Field(min_length=1, max_length=3)
    amount: int | None = Field(None, ge=0)
    debit: int | None = Field(None, ge=0)
    credit: int | None = Field(None, ge=0)
    currency: int | None = Field(None, ge=0)
    date_order: DateOrder = DateOrder.DMY
    sign: AmountSign = AmountSign.NEGATIVE_IS_OUT

    def mapping(self) -> Mapping:
        return Mapping(
            date=self.date,
            description=tuple(self.description),
            amount=self.amount,
            debit=self.debit,
            credit=self.credit,
            currency=self.currency,
            date_order=self.date_order,
            sign=self.sign,
        )


def layout_out(m: Mapping) -> LayoutIn:
    return LayoutIn(
        date=m.date,
        description=list(m.description),
        amount=m.amount,
        debit=m.debit,
        credit=m.credit,
        currency=m.currency,
        date_order=m.date_order,
        sign=m.sign,
    )


CSV_CHARS = 2_100_000


class PreviewIn(Model):
    csv: str = Field(min_length=1, max_length=CSV_CHARS)
    layout: LayoutIn | None = None


class MatchOut(Model):
    date: date
    description: str | None
    amount: str


class PreviewRowOut(Model):
    index: int
    verdict: Verdict
    cells: list[str]
    date: date | None
    description: str
    amount: str | None
    currency: str | None
    direction: Direction | None
    category: str | None  # null for a proposed move
    problem: str | None
    matches: MatchOut | None
    # Proposed as a move because the description names a wallet: money out goes from
    # the main account to ``move_to``; money in comes from ``move_from`` to the main account.
    move_to: WalletOut | None = None
    move_from: WalletOut | None = None


class PreviewOut(Model):
    headers: list[str]
    layout: LayoutIn | None
    saved_as: str | None
    rows: list[PreviewRowOut]


@router.post("/imports/preview")
async def preview_import(body: PreviewIn, auth: Auth, web: Runtime) -> PreviewOut:
    limit(web, auth, "import")
    shown = await statement_cases.preview(
        web.uow, auth.user, body.csv, body.layout.mapping() if body.layout else None
    )
    tz = ZoneInfo(auth.user.timezone)
    return PreviewOut(
        headers=shown.table.headers,
        layout=layout_out(shown.mapping) if shown.mapping else None,
        saved_as=shown.saved_as,
        rows=[
            PreviewRowOut(
                index=p.row.index,
                verdict=p.verdict,
                cells=p.row.raw,
                date=p.row.day,
                description=p.row.description,
                amount=str(p.money.amount) if p.money else None,
                currency=p.money.currency if p.money else None,
                direction=p.row.direction,
                category=p.category,
                move_to=wallet_out(p.move_to) if p.move_to else None,
                move_from=wallet_out(p.move_from) if p.move_from else None,
                problem=p.row.problem,
                matches=MatchOut(
                    date=p.matches.occurred_at.astimezone(tz).date(),
                    description=p.matches.counterparty,
                    amount=str(p.matches.amount.amount),
                )
                if p.matches
                else None,
            )
            for p in shown.rows
        ],
    )


PDF_SECONDS = 30


PDF_BASE64_CHARS = 14_000_000  # a 10 MB PDF, base64-encoded


class PdfIn(Model):
    pdf: str = Field(min_length=1, max_length=PDF_BASE64_CHARS)  # base64
    password: str | None = Field(None, max_length=200)


class PdfOut(Model):
    needs_password: bool = False
    wrong_password: bool = False
    csv: str | None = None
    layout: LayoutIn | None = None
    kind: str | None = None
    statement_date: date | None = None
    rows: int = 0
    reconciles: bool | None = None
    scanned: bool = False  # read from pictures of the pages: worth checking row by row


@router.post("/imports/pdf")
async def read_pdf_statement(body: PdfIn, auth: Auth, web: Runtime) -> PdfOut:
    """A PDF statement's transactions as CSV, previewed and imported like any CSV. A
    scanned one is read page by page by the photo model first. The PDF, its password
    and a scan's text are only held for this request."""
    limit(web, auth, "import")
    try:
        data = base64.b64decode(body.pdf, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidInput("that file didn't arrive whole; try again") from exc
    try:
        # A crafted PDF can be slow to read; the request gives up rather than hang.
        lines, pages = await asyncio.wait_for(
            asyncio.to_thread(pdf_text, data, body.password, page_break=PAGE_BREAK), PDF_SECONDS
        )
    except TimeoutError as exc:
        raise InvalidInput("that PDF took too long to read") from exc
    except PasswordNeeded as locked:
        return PdfOut(needs_password=True, wrong_password=locked.wrong)
    scanned = statement_cases.looks_scanned(lines, pages)
    if scanned:
        if web.scans is None:
            raise InvalidInput(
                "that PDF is a scan, and reading scans isn't set up. Your bank's CSV export "
                "will work instead"
            )
        await demo_use(web, auth, demo_cases.Use.PHOTO)
        try:
            images = await asyncio.wait_for(
                asyncio.to_thread(page_images, data, body.password), PDF_SECONDS
            )
        except TimeoutError as exc:
            raise InvalidInput("that PDF took too long to read") from exc
        lines = await statement_cases.read_scan(web.scans, images)
    found = statement_cases.read_pdf(lines, scanned=scanned)
    return PdfOut(
        csv=found.csv,
        layout=layout_out(statement_cases.PDF_LAYOUT),
        kind=found.kind.value,
        statement_date=found.statement_date,
        rows=found.rows,
        reconciles=found.reconciles,
        scanned=found.scanned,
    )


class RowMoveIn(Model):
    row: int = Field(ge=0)
    # The wallet to move it to (money out) or from (money in); null: an ordinary entry.
    as_move: UUID | None = None


class ImportIn(Model):
    csv: str = Field(min_length=1, max_length=CSV_CHARS)
    layout: LayoutIn
    include: list[int] = Field(min_length=1, max_length=5000)
    # Which ticked rows are moves, as the preview proposed or the user changed it. A row
    # that isn't listed is an ordinary entry.
    moves: list[RowMoveIn] = Field(default=[], max_length=5000)
    file_name: str = Field(min_length=1, max_length=200)
    save_as: str | None = Field(None, min_length=1, max_length=60)
    # The card (or other wallet) every expense of this import was paid with. Money in and
    # moves are not. Left out or null: none (the usual card is not applied to imports).
    paid_with_wallet_id: UUID | None = None


class ImportOut(Model):
    id: UUID
    file_name: str
    added: int
    created_at: datetime
    undone_at: datetime | None = None


class ImportedOut(ImportOut):
    skipped: int


def import_out(record: StatementImport) -> ImportOut:
    return ImportOut(
        id=record.id,
        file_name=record.file_name,
        added=len(record.transaction_ids),
        created_at=record.created_at,
        undone_at=record.undone_at,
    )


@router.post("/imports", status_code=201)
async def import_statement(body: ImportIn, auth: Auth, web: Runtime) -> ImportedOut:
    limit(web, auth, "import")
    done = await statement_cases.confirm(
        web.uow,
        auth.user,
        body.csv,
        body.layout.mapping(),
        set(body.include),
        file_name=body.file_name,
        save_as=body.save_as,
        moves={m.row: m.as_move for m in body.moves if m.as_move is not None},
        paid_with=body.paid_with_wallet_id,
        now=web.clock(),
    )
    return ImportedOut(**import_out(done.record).model_dump(), skipped=done.skipped)


@router.get("/imports")
async def imports(auth: Auth, web: Runtime) -> list[ImportOut]:
    return [import_out(r) for r in await statement_cases.list_imports(web.uow(), auth.user.id)]


@router.post("/imports/{import_id}/undo")
async def undo_statement_import(import_id: UUID, auth: Auth, web: Runtime) -> dict[str, int]:
    removed = await statement_cases.undo_import(web.uow(), auth.user.id, import_id, now=web.clock())
    return {"removed": removed}


class LayoutOut(Model):
    id: UUID
    name: str


@router.get("/imports/layouts")
async def import_layouts(auth: Auth, web: Runtime) -> list[LayoutOut]:
    saved = await statement_cases.list_layouts(web.uow(), auth.user.id)
    return [LayoutOut(id=s.id, name=s.name) for s in saved]


@router.delete("/imports/layouts/{layout_id}", status_code=204)
async def forget_import_layout(layout_id: UUID, auth: Auth, web: Runtime) -> None:
    await statement_cases.forget_layout(web.uow(), auth.user.id, layout_id)
