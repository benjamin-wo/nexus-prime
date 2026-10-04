"""The Investment department's API: holdings, and positions read from a broker
screenshot waiting to be saved. Research only: nothing here trades."""

import base64
import binascii
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import investments as investment_cases
from nexus.channels.web.api import MoneyOut, money
from nexus.channels.web.security import Auth, Runtime, limit
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.investments import (
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
    # At the last close; all None until the stock has a price.
    price: MoneyOut | None = None
    price_day: date | None = None
    value: MoneyOut | None = None
    gain: MoneyOut | None = None
    gain_percent: Decimal | None = None
    day_change: MoneyOut | None = None
    day_percent: Decimal | None = None
    value_home: MoneyOut | None = None  # None also when there's no exchange rate yet


class DraftOut(Model):
    id: str
    positions: list[PositionOut]
    changes: list[str]  # what saving it would change
    first: bool  # no holdings yet: it would be the whole portfolio


class TotalsOut(Model):
    """The portfolio in the home currency, at the last close."""

    value: MoneyOut | None
    cost: MoneyOut | None
    gain: MoneyOut | None
    gain_percent: Decimal | None
    day_change: MoneyOut | None
    day_percent: Decimal | None
    as_of: date | None
    missing: list[str]  # stocks left out (no price or exchange rate yet)


class PortfolioOut(Model):
    holdings: list[HoldingOut]
    totals: TotalsOut
    draft: DraftOut | None  # a screenshot waiting to be saved
    screenshots: bool  # reading screenshots is set up
    prices: bool  # daily prices are set up


def _position(p: Position) -> PositionOut:
    return PositionOut(
        symbol=p.symbol,
        quantity=p.quantity,
        average_cost=money(p.average_cost),
        cost=money(p.cost),
    )


def _optional(value: Money | None) -> MoneyOut | None:
    return money(value) if value is not None else None


def _holding(row: investment_cases.Row) -> HoldingOut:
    h, v = row.holding, row.valued
    out = HoldingOut(**_position(h.position).model_dump(), updated_at=h.updated_at)
    if v is None:
        return out
    return out.model_copy(
        update={
            "price": money(v.price),
            "price_day": v.price_day,
            "value": money(v.value),
            "gain": money(v.gain),
            "gain_percent": v.gain_percent,
            "day_change": _optional(v.day_change),
            "day_percent": v.day_percent,
            "value_home": _optional(row.value_home),
        }
    )


def _totals(v: investment_cases.Valuation) -> TotalsOut:
    return TotalsOut(
        value=_optional(v.value),
        cost=_optional(v.cost),
        gain=_optional(v.gain),
        gain_percent=v.gain_percent,
        day_change=_optional(v.day_change),
        day_percent=v.day_percent,
        as_of=v.as_of,
        missing=v.missing,
    )


def _draft(draft: HoldingsDraft, held: list[Position]) -> DraftOut:
    return DraftOut(
        id=str(draft.id),
        positions=[_position(p) for p in draft.positions],
        changes=changes(held, draft.positions),
        first=not held,
    )


@router.get("")
async def portfolio(auth: Auth, web: Runtime) -> PortfolioOut:
    valued = await investment_cases.valuation(web.uow(), web.rates, auth.user)
    draft = await investment_cases.waiting_draft(web.uow(), auth.user.id)
    held = [row.holding.position for row in valued.rows]
    return PortfolioOut(
        holdings=[_holding(row) for row in valued.rows],
        totals=_totals(valued),
        draft=_draft(draft, held) if draft else None,
        screenshots=web.service.reads_portfolios,
        prices=web.prices,
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
