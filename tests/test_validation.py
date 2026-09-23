"""Tests for ``capabilities/email/validation.py`` — Laya transaction detection."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capabilities.email.validation import (
    is_transaction_email,
    load_agent,
    validate_transaction_email,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures: reusable mock predict responses
# ═══════════════════════════════════════════════════════════════════════════════

_HIGH_CONFIDENCE_TRANSACTION = {
    "model": "laya-rl-agent",
    "answers": {
        "is_transaction": {
            "type": "noul",
            "noul": 0.92,
            "confidence": 0.94,
            "action": {"act_probability": 0.94},
        },
        "email_type": {
            "type": "choice",
            "choice": "transaction",
            "probabilities": {
                "transaction": 0.85,
                "promotional": 0.05,
                "security_alert": 0.03,
                "spam_phishing": 0.02,
                "other": 0.05,
            },
            "confidence": 0.85,
            "action": {"act_probability": 0.85},
        },
    },
    "usage": {"input_tokens": 512, "output_tokens": 0},
}

_LOW_PROBABILITY_SPAM = {
    "model": "laya-rl-agent",
    "answers": {
        "is_transaction": {
            "type": "noul",
            "noul": 0.08,
            "confidence": 0.92,
            "action": {"act_probability": 0.92},
        },
        "email_type": {
            "type": "choice",
            "choice": "promotional",
            "probabilities": {
                "transaction": 0.05,
                "promotional": 0.88,
                "security_alert": 0.02,
                "spam_phishing": 0.03,
                "other": 0.02,
            },
            "confidence": 0.88,
            "action": {"act_probability": 0.88},
        },
    },
    "usage": {"input_tokens": 300, "output_tokens": 0},
}

_EDGE_PRECISE_MID = {
    "model": "laya-rl-agent",
    "answers": {
        "is_transaction": {
            "type": "noul",
            "noul": 0.5,
            "confidence": 0.5,
            "action": {"act_probability": 0.5},
        },
        "email_type": {
            "type": "choice",
            "choice": "other",
            "probabilities": {
                "transaction": 0.25,
                "promotional": 0.25,
                "security_alert": 0.25,
                "spam_phishing": 0.0,
                "other": 0.25,
            },
            "confidence": 0.5,
            "action": {"act_probability": 0.5},
        },
    },
    "usage": {"input_tokens": 200, "output_tokens": 0},
}


def _mock_agent(predict_result: dict) -> MagicMock:
    """Build a fake Agent whose ``predict()`` returns *predict_result*."""
    agent = MagicMock()
    agent.predict.return_value = predict_result
    return agent


def _patch_email_utils() -> list:
    """Return context managers that mock ``_clean_email_body`` and
    ``_email_state`` so tests don't depend on a real ``laya`` install."""
    return [
        patch(
            "capabilities.email.validation._clean_email_body",
            return_value="cleaned mock body",
        ),
        patch(
            "capabilities.email.validation._email_state",
            return_value={"subject": "mock", "body": "cleaned mock body"},
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# validate_transaction_email — happy path
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_validate_output_shape_high_confidence_transaction():
    """High noul probability → is_transaction=True, email_type='transaction'."""
    agent = _mock_agent(_HIGH_CONFIDENCE_TRANSACTION)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "capabilities.email.validation.load_agent",
                new_callable=AsyncMock,
                return_value=agent,
            )
        )
        for cm in _patch_email_utils():
            stack.enter_context(cm)

        result = await validate_transaction_email(
            sender="receipts@starbucks.com",
            subject="Your receipt from Starbucks",
            body="Thank you for your order. Total: $15.00.",
        )

    assert result["is_transaction"] is True
    assert result["is_transaction_probability"] == 0.92
    assert result["email_type"] == "transaction"
    assert result["email_type_probabilities"]["transaction"] == 0.85
    assert result["confidence"] == 0.94  # max of 0.94 and 0.85
    assert result["usage"]["input_tokens"] == 512
    assert result["model"] == "laya-rl-agent"


@pytest.mark.asyncio
async def test_validate_low_probability_non_transaction():
    """Low noul → is_transaction=False, email_type='promotional'."""
    agent = _mock_agent(_LOW_PROBABILITY_SPAM)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "capabilities.email.validation.load_agent",
                new_callable=AsyncMock,
                return_value=agent,
            )
        )
        for cm in _patch_email_utils():
            stack.enter_context(cm)

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
    agent = _mock_agent(_EDGE_PRECISE_MID)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "capabilities.email.validation.load_agent",
                new_callable=AsyncMock,
                return_value=agent,
            )
        )
        for cm in _patch_email_utils():
            stack.enter_context(cm)

        result = await validate_transaction_email(
            sender="mid@example.com",
            subject="Ambiguous email",
            body="Some message",
        )

    assert result["is_transaction"] is False  # 0.5 is not > 0.5
    assert result["is_transaction_probability"] == 0.5
    assert result["email_type"] == "other"


# ═══════════════════════════════════════════════════════════════════════════════
# Graceful degradation — Laya not installed
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_validate_fallback_when_laya_not_available():
    """LAYA_AVAILABLE=False → fallback dict with null fields."""
    import capabilities.email.validation as val_mod

    with patch.object(val_mod, "LAYA_AVAILABLE", False):
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
    """LAYA_AVAILABLE=False → is_transaction_email returns 0.5."""
    import capabilities.email.validation as val_mod

    with patch.object(val_mod, "LAYA_AVAILABLE", False):
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
    agent = _mock_agent(_HIGH_CONFIDENCE_TRANSACTION)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "capabilities.email.validation.load_agent",
                new_callable=AsyncMock,
                return_value=agent,
            )
        )
        for cm in _patch_email_utils():
            stack.enter_context(cm)

        prob = await is_transaction_email(
            sender="receipts@starbucks.com",
            subject="Your receipt",
            body="Total: $15.00",
        )

    assert prob == 0.92


@pytest.mark.asyncio
async def test_is_transaction_email_low_value():
    """Low noul value is forwarded correctly by the wrapper."""
    agent = _mock_agent(_LOW_PROBABILITY_SPAM)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "capabilities.email.validation.load_agent",
                new_callable=AsyncMock,
                return_value=agent,
            )
        )
        for cm in _patch_email_utils():
            stack.enter_context(cm)

        prob = await is_transaction_email(
            sender="spam@spam.com",
            subject="Buy now",
            body="Cheap stuff",
        )

    assert prob == 0.08


# ═══════════════════════════════════════════════════════════════════════════════
# Concurrency guard — asyncio.Lock
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_load_agent_concurrency_guard():
    """Three concurrent ``load_agent()`` calls only invoke ``laya.load()`` once."""
    import capabilities.email.validation as val_mod

    # Reset module state so we exercise the load path
    val_mod._model = None  # type: ignore[union-attr]

    call_count = 0
    mock_agent = MagicMock()

    def slow_load(**kwargs: object) -> MagicMock:
        """Simulate a slow model load that blocks inside the lock."""
        nonlocal call_count
        call_count += 1
        import time

        time.sleep(0.05)  # Block long enough for racing coroutines to queue
        return mock_agent

    with (
        patch.object(val_mod, "LAYA_AVAILABLE", True),
        patch.object(val_mod, "_laya_module") as mock_laya_mod,
    ):
        mock_laya_mod.load = slow_load

        results = await asyncio.gather(
            val_mod.load_agent(),
            val_mod.load_agent(),
            val_mod.load_agent(),
        )

    assert call_count == 1, f"Expected 1 laya.load() call, got {call_count}"
    for agent in results:
        assert agent is mock_agent


@pytest.mark.asyncio
async def test_load_agent_returns_none_when_not_available():
    """load_agent returns None when LAYA_AVAILABLE is False."""
    import capabilities.email.validation as val_mod

    with patch.object(val_mod, "LAYA_AVAILABLE", False):
        agent = await val_mod.load_agent()

    assert agent is None