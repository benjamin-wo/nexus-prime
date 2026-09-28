"""Reading a receipt photo into a draft expense. The image is not stored."""

import base64
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ReceiptDraft(BaseModel):
    is_receipt: bool = Field(description="Whether the image is a receipt, bill or invoice")
    amount: str | None = Field(None, description="The final total paid, digits only, e.g. 12.40")
    currency: str | None = Field(None, description="ISO 4217 code if printed, else null")
    merchant: str | None = Field(None, description="Shop or company name")
    date: str | None = Field(None, description="Purchase date as YYYY-MM-DD if printed")


class ReceiptReader(Protocol):
    async def read(self, image: bytes, mime_type: str, caption: str | None) -> ReceiptDraft: ...


_PROMPT = (
    "Read this image. If it is a receipt, bill or invoice, extract the final total "
    "actually paid (after tax, service charge and discounts), its currency if printed, "
    "the merchant and the purchase date. Use null for anything you can't read clearly; "
    "never guess.{caption}"
)


class LlmReceiptReader:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model.with_structured_output(ReceiptDraft)

    async def read(self, image: bytes, mime_type: str, caption: str | None) -> ReceiptDraft:
        encoded = base64.b64encode(image).decode()
        hint = f" The user wrote: {caption!r}." if caption else ""
        message = HumanMessage(
            content=[
                {"type": "text", "text": _PROMPT.format(caption=hint)},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ]
        )
        result = await self._model.ainvoke([message])
        if isinstance(result, ReceiptDraft):
            return result
        return ReceiptDraft.model_validate(result)
