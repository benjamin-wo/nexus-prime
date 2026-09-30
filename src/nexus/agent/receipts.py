"""Reading a receipt photo into a draft expense. The image is not stored."""

import base64
import logging
import re
from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ReceiptDraft(BaseModel):
    is_receipt: bool = Field(description="Whether the image is a receipt, bill or invoice")
    amount: str | None = Field(None, description="The final total paid, digits only, e.g. 12.40")
    currency: str | None = Field(None, description="ISO 4217 code if printed, else null")
    merchant: str | None = Field(None, description="Shop or company name")
    date: str | None = Field(None, description="Purchase date as YYYY-MM-DD if printed")
    category: str | None = Field(
        None, description="The closest category from the list given, exactly as written"
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _just_the_number(cls, value: Any) -> Any:
        """'RM 45.00', 'S$1,980' or 12.4 become '45.00', '1980' and '12.4'."""
        if value is None or isinstance(value, bool):
            return None
        found = _NUMBER.search(str(value).replace(",", ""))
        return found.group(0) if found else None

    @field_validator("date", mode="before")
    @classmethod
    def _iso_date(cls, value: Any) -> Any:
        return None if value is None else iso_date(str(value))


_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_YMD = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DMY = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})")


_DAYS_AGO = (
    (re.compile(r"\bday before yesterday\b", re.I), 2),
    (re.compile(r"\byesterday\b", re.I), 1),
    (re.compile(r"\btoday\b", re.I), 0),
)


def caption_date(caption: str | None, today: date) -> str | None:
    """The day a caption like "from yesterday" means, for a receipt with no date."""
    for pattern, days in _DAYS_AGO:
        if caption and pattern.search(caption):
            return date.fromordinal(today.toordinal() - days).isoformat()
    return None


def iso_date(text: str) -> str | None:
    """A printed date as YYYY-MM-DD, or None. Slashed dates are read day first, as
    Singapore receipts print them (16/2/2013 is 16 February)."""
    ymd = _YMD.search(text)
    if ymd:
        year, month, day = (int(g) for g in ymd.groups())
    else:
        dmy = _DMY.search(text)
        if not dmy:
            return None
        day, month, year = (int(g) for g in dmy.groups())
        year += 2000 if year < 100 else 0
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


class ReceiptReader(Protocol):
    async def read(
        self,
        image: bytes,
        mime_type: str,
        caption: str | None,
        *,
        categories: Sequence[str] = (),
        today: date | None = None,
    ) -> ReceiptDraft: ...


_PROMPT = (
    "Read this image. If it is a receipt, bill or invoice, extract the final total "
    "actually paid (after tax, service charge and discounts), its currency if printed, "
    "the merchant and the purchase date. Use null for anything you can't read clearly; "
    "never guess.{today}{categories}{caption}"
)


class LlmReceiptReader:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model.with_structured_output(ReceiptDraft)

    async def read(
        self,
        image: bytes,
        mime_type: str,
        caption: str | None,
        *,
        categories: Sequence[str] = (),
        today: date | None = None,
    ) -> ReceiptDraft:
        encoded = base64.b64encode(image).decode()
        hint = f" The user wrote: {caption!r}." if caption else ""
        # So "from yesterday" in a caption can be turned into a date.
        when = f" Today is {today:%A %Y-%m-%d}." if today else ""
        choose = (
            " Also pick the closest category for this purchase from: " + ", ".join(categories) + "."
            if categories
            else ""
        )
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": _PROMPT.format(caption=hint, categories=choose, today=when),
                },
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ]
        )
        for attempt in (1, 2):  # models now and then return a reply that doesn't parse
            try:
                result = await self._model.ainvoke([message])
                if isinstance(result, ReceiptDraft):
                    return result
                return ReceiptDraft.model_validate(result)
            except Exception:
                if attempt == 2:
                    raise
                log.warning("receipt reply didn't parse; trying once more", exc_info=True)
        raise AssertionError("unreachable")  # pragma: no cover
