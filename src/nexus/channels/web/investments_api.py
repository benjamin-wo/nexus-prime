"""The Investment department's API: holdings, and positions read from a broker
screenshot waiting to be saved. Research only: nothing here trades."""

import base64
import binascii
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import investments as investment_cases
from nexus.channels.web.api import MoneyOut, money
from nexus.channels.web.security import Auth, Runtime, limit
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.investments import (
    Holding,
    HoldingsDraft,
    Position,
    changes,
    clean_quantity,
    clean_symbol,
)
from nexus.domain.money import Money

router = APIRouter(prefix="/api/investments")

# A phone screenshot, base64-encoded: well under this.
MAX_IMAGE_CHARS = 14_000_000
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PositionOut(Model):
    symbol: str
    quantity: Decimal
    average_cost: MoneyOut
    cost: MoneyOut


class HoldingOut(PositionOut):
    updated_at: datetime


class DraftOut(Model):
    id: str
    positions: list[PositionOut]
    changes: list[str]  # what saving it would change
    first: bool  # no holdings yet: it would be the whole portfolio


class PortfolioOut(Model):
    holdings: list[HoldingOut]
    draft: DraftOut | None  # a screenshot waiting to be saved
    screenshots: bool  # reading screenshots is set up


def _position(p: Position) -> PositionOut:
    return PositionOut(
        symbol=p.symbol,
        quantity=p.quantity,
        average_cost=money(p.average_cost),
        cost=money(p.cost),
    )


def _holding(h: Holding) -> HoldingOut:
    return HoldingOut(**_position(h.position).model_dump(), updated_at=h.updated_at)


def _draft(draft: HoldingsDraft, held: list[Position]) -> DraftOut:
    return DraftOut(
        id=str(draft.id),
        positions=[_position(p) for p in draft.positions],
        changes=changes(held, draft.positions),
        first=not held,
    )


@router.get("")
async def portfolio(auth: Auth, web: Runtime) -> PortfolioOut:
    held = await investment_cases.portfolio(web.uow(), auth.user.id)
    draft = await investment_cases.waiting_draft(web.uow(), auth.user.id)
    return PortfolioOut(
        holdings=[_holding(h) for h in held],
        draft=_draft(draft, [h.position for h in held]) if draft else None,
        screenshots=web.service.reads_portfolios,
    )


class ScreenshotIn(Model):
    image: str = Field(min_length=1, max_length=MAX_IMAGE_CHARS)  # base64
    mime_type: str = Field(pattern="^image/(png|jpeg|webp)$")


@router.post("/screenshot")
async def read_screenshot(body: ScreenshotIn, auth: Auth, web: Runtime) -> DraftOut:
    """A broker screenshot read into positions, waiting for the user to save them.
    The image is only held for this request."""
    limit(web, auth, "import")
    try:
        image = base64.b64decode(body.image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidInput("that image didn't arrive whole; try again") from exc
    held = [h.position for h in await investment_cases.portfolio(web.uow(), auth.user.id)]
    proposal = await web.service.read_portfolio(auth.user.id, image, body.mime_type)
    if proposal is None:  # pragma: no cover - asked, so never None
        raise InvalidInput("I couldn't find any positions in that screenshot")
    return _draft(proposal.draft, held)


@router.post("/drafts/{draft_id}/save")
async def save_draft(draft_id: str, auth: Auth, web: Runtime) -> list[PositionOut]:
    saved = await investment_cases.save_draft(
        web.uow(), auth.user.id, _uuid(draft_id), now=web.clock()
    )
    return [_position(p) for p in saved]


@router.post("/drafts/{draft_id}/discard", status_code=204)
async def discard_draft(draft_id: str, auth: Auth, web: Runtime) -> None:
    await investment_cases.discard_draft(web.uow(), auth.user.id, _uuid(draft_id))


class PositionIn(Model):
    quantity: str = Field(min_length=1, max_length=32)
    average_cost: str = Field(min_length=1, max_length=32)
    currency: str = Field("USD", pattern="^[A-Za-z]{3}$")


@router.put("/holdings/{symbol}", status_code=204)
async def set_holding(symbol: str, body: PositionIn, auth: Auth, web: Runtime) -> None:
    position = Position(
        clean_symbol(symbol),
        clean_quantity(body.quantity),
        Money.of(body.average_cost.replace(",", ""), body.currency.upper()),
    )
    await investment_cases.set_position(web.uow(), auth.user.id, position, now=web.clock())


@router.delete("/holdings/{symbol}", status_code=204)
async def remove_holding(symbol: str, auth: Auth, web: Runtime) -> None:
    await investment_cases.remove(web.uow(), auth.user.id, clean_symbol(symbol))


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise NotFound("that screenshot isn't waiting any more") from exc
