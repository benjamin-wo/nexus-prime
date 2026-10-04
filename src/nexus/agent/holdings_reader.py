"""Reading a broker's portfolio screenshot (IBKR's Portfolio screen first) into
positions. The image is not stored, and nothing is saved until the user says so."""

import base64
import logging
import re
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _number(value: Any) -> Any:
    """'1,250.5', '$118.40' or 12 become '1250.5', '118.40' and '12'."""
    if value is None or isinstance(value, bool):
        return None
    found = _NUMBER.search(str(value).replace(",", ""))
    return found.group(0) if found else None


class ScreenshotPosition(BaseModel):
    symbol: str = Field(description="The ticker as shown, e.g. NVDA")
    quantity: str | None = Field(None, description="Number of shares held, digits only")
    average_cost: str | None = Field(
        None, description="Average cost (or average price) per share, digits only"
    )
    currency: str | None = Field(None, description="ISO 4217 code if shown, else null")

    @field_validator("quantity", "average_cost", mode="before")
    @classmethod
    def _digits(cls, value: Any) -> Any:
        return _number(value)


class ScreenshotHoldings(BaseModel):
    is_portfolio: bool = Field(
        description="Whether the image is a brokerage portfolio or positions screen"
    )
    positions: list[ScreenshotPosition] = Field(default_factory=list)


class HoldingsReader(Protocol):
    async def read(self, image: bytes, mime_type: str) -> ScreenshotHoldings: ...


_PROMPT = (
    "Read this image. If it is a brokerage app's portfolio or positions screen (such as "
    "Interactive Brokers), list every stock position: the ticker, the number of shares, "
    "the average cost per share (IBKR may call it 'Avg Price' or 'Average Cost'; use the "
    "per-share figure, not the total cost basis) and the currency if shown. Leave out cash, "
    "totals, options and anything you can't read clearly; use null rather than guess."
)


class LlmHoldingsReader:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model.with_structured_output(ScreenshotHoldings)

    async def read(self, image: bytes, mime_type: str) -> ScreenshotHoldings:
        encoded = base64.b64encode(image).decode()
        message = HumanMessage(
            content=[
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ]
        )
        for attempt in (1, 2):  # models now and then return a reply that doesn't parse
            try:
                result = await self._model.ainvoke([message])
                if isinstance(result, ScreenshotHoldings):
                    return result
                return ScreenshotHoldings.model_validate(result)
            except Exception:
                if attempt == 2:
                    raise
                log.warning("portfolio reply didn't parse; trying once more", exc_info=True)
        raise AssertionError("unreachable")  # pragma: no cover
