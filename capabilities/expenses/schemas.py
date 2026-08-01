from datetime import datetime
from pydantic import BaseModel, Field

class ExtractedExpense(BaseModel):
    amount: float
    currency: str = Field(default="USD")
    merchant: str
    category: str
    date: datetime
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    needs_clarification: bool = Field(default=False, description="True if merchant or amount is ambiguous")
