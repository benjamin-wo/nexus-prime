"""Tests for ``capabilities/email/validation.py`` — Jev transaction detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from capabilities.email.validation import (
    _FALLBACK,
    is_transaction_email,
    load_agent,
    validate_transaction_email,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures: reusable mock Jev API responses
# ═══════════════════════════════════════════════════════════════════════════════

_HIGH_CONFIDENCE_TRANSACTION = {
    "model": "typesafe/jev-1.13",
    "answers": {
        "is_transaction": {
            "type": "noul",
            "noul": 0.92,
        },
        "email_type": {
            "type": "choice",
            "choice": "transaction",
            "probabilities": {
                "transaction": 0.85,
                "promotional": 0.05,
                "security_alert": 0.03,
                "other": 0.07,
            },
            "confidence": 0.85,
        },
    },
    "usage": {"input_tokens": 512, "output_tokens": 8, "cost": 0.0001},
}

_LOW_PROBABILITY_SPAM = {
    "model": "typesafe/jev-1.13",
    "answers": {
        "is_transaction": {
            "type": "noul",
            "noul": 0.08,
        },
        "email_type": {
            "type": "choice",
            "choice": "promotional",
            "probabilities": {
                "transaction": 0.05,
                "promotional": 0.88,
                "security_alert": 0.02,
                "other": 0.05,
            },
            "confidence": 0.88,
        },
    },
    "usage": {"input_tokens": 300, "output_tokens": 6, "cost": 0.00005},
}

_EDGE_PRECISE_MID = {
    "model": "typesafe/jev-1.13",
    "answers": {
        "is_transaction": {
            "type": "noul",
            "noul": 0.5,
        },
        "email_type": {
            "type": "choice",
            "choice": "other",
            "probabilities": {
                "transaction": 0.25,
                "promotional": 0.25,
                "security_alert": 0.25,
                "other": 0.25,
            },
            "confidence": 0.5,
        },
    },
    "usage": {"input_tokens": 200, "output_tokens": 4, "cost": 0.00003},
}


def _mock_jev(result: dict) -> AsyncMock:
    """Build an ``AsyncMock`` for ``_call_jev`` that returns *result*."""
    mock = AsyncMock(return_value=result)
    return mock


# ═══════════════════════════════════════════════════════════════════════════════
# validate_transaction_email — happy path
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_validate_output_shape_high_confidence_transaction():
    """High noul probability → is_transaction=True, email_type='transaction'."""
    with patch(
        "capabilities.email.validation._call_jev",
        new_callable=AsyncMock,
        return_value=_HIGH_CONFIDENCE_TRANSACTION,
    ):
        result = await validate_transaction_email(
            sender="receipts@starbucks.com",
            subject="Your receipt from Starbucks",
            body="Thank you for your order. Total: $15.00.",
        )

    assert result["is_transaction"] is True
    assert result["is_transaction_probability"] == 0.92
    assert result["email_type"] == "transaction"
    assert result["email_type_probabilities"]["transaction"] == 0.85
    assert result["confidence"] == 0.92  # max(noul=0.92, confidence=0.85)
    assert result["usage"]["input_tokens"] == 512
    assert result["model"] == "typesafe/jev-1.13"


@pytest.mark.asyncio
async def test_validate_low_probability_non_transaction():
    """Low noul → is_transaction=False, email_type='promotional'."""
    with patch(
        "capabilities.email.validation._call_jev",
        new_callable=AsyncMock,
        return_value=_LOW_PROBABILITY_SPAM,
    ):
        result = await validate_transaction_email(
            sender="ads@spam.com",
            subject="Great deals!",
            body="Cheap flights today only!",
        )

    assert result["is_transaction"] is False
    assert result["is_transaction_probability"] == 0.08
    assert result["email_type"] == "promotional"


@pytest.mark.asyncio
async def test_validate_exactly_05_is_not_transaction():
    """noul == 0.5 → is_transaction=False (not > 0.5)."""
    with patch(
        "capabilities.email.validation._call_jev",
        new_callable=AsyncMock,
        return_value=_EDGE_PRECISE_MID,
    ):
        result = await validate_transaction_email(
            sender="mid@example.com",
            subject="Ambiguous email",
            body="Some message",
        )

    assert result["is_transaction"] is False  # 0.5 is not > 0.5
    assert result["is_transaction_probability"] == 0.5
    assert result["email_type"] == "other"


# ═══════════════════════════════════════════════════════════════════════════════
# Graceful degradation — Jev API unreachable
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_validate_fallback_when_jev_fails():
    """_call_jev returns None → fallback dict with null fields."""
    with patch(
        "capabilities.email.validation._call_jev",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await validate_transaction_email(
            sender="test@example.com",
            subject="Test",
            body="Test body",
        )

    assert result["is_transaction"] is None
    assert result["is_transaction_probability"] is None
    assert result["email_type"] == "unknown"
    assert result["email_type_probabilities"] == {}
    assert result["confidence"] == 0.0
    assert result["usage"] == {}
    assert result["model"] is None


@pytest.mark.asyncio
async def test_is_transaction_email_returns_05_on_fallback():
    """_call_jev returns None → is_transaction_email returns 0.5."""
    with patch(
        "capabilities.email.validation._call_jev",
        new_callable=AsyncMock,
        return_value=None,
    ):
        prob = await is_transaction_email(
            sender="test@example.com",
            subject="Test",
            body="Test body",
        )

    assert prob == 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# is_transaction_email — convenience wrapper
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_is_transaction_email_returns_probability_directly():
    """When available, is_transaction_email returns the noul probability."""
    with patch(
        "capabilities.email.validation._call_jev",
        new_callable=AsyncMock,
        return_value=_HIGH_CONFIDENCE_TRANSACTION,
    ):
        prob = await is_transaction_email(
            sender="receipts@starbucks.com",
            subject="Your receipt",
            body="Total: $15.00",
        )

    assert prob == 0.92


@pytest.mark.asyncio
async def test_is_transaction_email_low_value():
    """Low noul value is forwarded correctly by the wrapper."""
    with patch(
        "capabilities.email.validation._call_jev",
        new_callable=AsyncMock,
        return_value=_LOW_PROBABILITY_SPAM,
    ):
        prob = await is_transaction_email(
            sender="spam@spam.com",
            subject="Buy now",
            body="Cheap stuff",
        )

    assert prob == 0.08


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compatible stubs
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_load_agent_returns_none():
    """load_agent always returns None (legacy stub kept for back-compat)."""
    agent = await load_agent()
    assert agent is None


def test_fallback_dict_is_correct_shape():
    """_FALLBACK has the expected keys and default values."""
    assert _FALLBACK["is_transaction"] is None
    assert _FALLBACK["is_transaction_probability"] is None
    assert _FALLBACK["email_type"] == "unknown"
    assert _FALLBACK["email_type_probabilities"] == {}
    assert _FALLBACK["confidence"] == 0.0
    assert _FALLBACK["usage"] == {}
    assert _FALLBACK["model"] is None