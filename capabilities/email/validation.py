"""
Jev (OpenRouter Decisions) wrapper — transaction email validation.

Calls the OpenRouter Decisions API (System One decision model) to classify
emails as financial transactions, promotions, security alerts, or other.
Graceful degradation when the API is unreachable.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from core.config import settings

log = logging.getLogger(__name__)


# ── Backward-compatible stub ────────────────────────────────────────────────
# load_agent kept so existing imports (tests, callers) don't break when they
# import it — always returns None since Laya has been replaced by Jev.

_LAYA_AVAILABLE = False  # kept so ``patch.object(val_mod, "_LAYA_AVAILABLE")`` patterns still resolve
_model: Optional[Any] = None  # kept for import compat; unused


async def load_agent(
    model_id_or_path: str = "convaiinnovations/laya",
    device: Optional[str] = None,
    token: Optional[str] = None,
    subfolder: Optional[str] = None,
) -> Any:
    """No-op stub.  Laya has been replaced by Jev (OpenRouter Decisions).

    Always returns ``None``.  Kept so existing importers of ``load_agent``
    do not break.
    """
    del model_id_or_path, device, token, subfolder  # unused
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Transaction detection questions (Jev format)
# ═══════════════════════════════════════════════════════════════════════════════

_TRANSACTION_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "is_transaction": {
        "type": "noul",
        "instructions": (
            "Is this email a genuine record of money the user actually "
            "paid/spent (receipt, payment confirmation, card/bank transaction "
            "alert, paid invoice)? False for promotions, newsletters, "
            "statements, refunds, incoming money, payment reminders, "
            "OTP/security mail."
        ),
        "criteria": {
            "true": "Genuine payment or charge",
            "false": (
                "Promotion, newsletter, statement, refund, incoming money, "
                "reminder, or security mail"
            ),
        },
    },
    "email_type": {
        "type": "choice",
        "instructions": "What type of email is this?",
        "criteria": {
            "transaction": (
                "Financial transaction: receipt, payment confirmation, "
                "invoice, order summary, billing statement"
            ),
            "promotional": (
                "Marketing or promotional content: newsletter, offer, "
                "discount, advertisement"
            ),
            "security_alert": (
                "Security notification: password reset, login alert, "
                "verification code, suspicious activity warning"
            ),
            "other": "None of the above categories",
        },
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Jev API call
# ═══════════════════════════════════════════════════════════════════════════════

_FALLBACK: Dict[str, Any] = {
    "is_transaction": None,
    "is_transaction_probability": None,
    "email_type": "unknown",
    "email_type_probabilities": {},
    "confidence": 0.0,
    "usage": {},
    "model": None,
}


async def _call_jev(
    state: Dict[str, str],
    questions: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """POST *state* + *questions* to the OpenRouter Decisions API.

    Returns the parsed JSON response dict, or ``None`` on any failure
    (HTTP error, timeout, malformed JSON, missing config).
    """
    api_key = settings.openrouter_api_key
    url = settings.openrouter_decisions_url
    model = settings.jev_model

    if not api_key or not url:
        log.warning("Jev: missing openrouter_api_key or openrouter_decisions_url")
        return None

    payload: Dict[str, Any] = {
        "model": model,
        "state": state,
        "questions": questions,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        log.error("Jev HTTP %s: %s", exc.response.status_code, exc.response.text[:500])
    except httpx.RequestError as exc:
        log.error("Jev request failed: %s", exc)
    except ValueError as exc:
        log.error("Jev malformed JSON: %s", exc)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. High-level public API
# ═══════════════════════════════════════════════════════════════════════════════


async def validate_transaction_email(
    sender: str,
    subject: str,
    body: str,
) -> Dict[str, Any]:
    """Classify an email as a transaction receipt using the Jev decision model.

    Builds a structured state from the email fields, asks two typed questions
    via the OpenRouter Decisions API, and returns the model's answers with
    confidence scores.

    Args:
        sender: Sender email address.
        subject: Email subject line.
        body: Raw email body text.

    Returns:
        A dict with the following keys::

            {
                "is_transaction": bool | None,        # True if noul > 0.5
                "is_transaction_probability": float,   # raw noul score 0-1
                "email_type": str,                     # chosen category
                "email_type_probabilities": dict,      # per-category probs
                "confidence": float,                   # calibrated 0-1
                "usage": {"input_tokens": int},        # token usage
                "model": str | None,                   # model identifier
            }

        On any error (HTTP error, timeout, malformed response) returns a
        fallback dict with ``is_transaction=None``,
        ``is_transaction_probability=None``, ``email_type="unknown"``,
        and ``confidence=0.0``.  No exception escapes.
    """
    state = {
        "sender": sender,
        "subject": subject,
        "body": body,
    }

    result = await _call_jev(state, _TRANSACTION_QUESTIONS)
    if result is None:
        return dict(_FALLBACK)

    answers = result.get("answers", {})
    is_tx_answer = answers.get("is_transaction", {})
    type_answer = answers.get("email_type", {})

    is_tx_noul = is_tx_answer.get("noul")
    is_tx: bool | None = (
        is_tx_noul > 0.5
        if isinstance(is_tx_noul, (int, float))
        else None
    )

    return {
        "is_transaction": is_tx,
        "is_transaction_probability": (
            float(is_tx_noul) if isinstance(is_tx_noul, (int, float)) else None
        ),
        "email_type": type_answer.get("choice", "unknown"),
        "email_type_probabilities": type_answer.get("probabilities", {}),
        "confidence": max(
            (
                float(is_tx_answer.get("noul", 0.0))
                if isinstance(is_tx_answer.get("noul"), (int, float))
                else 0.0
            ),
            (
                float(type_answer.get("confidence", 0.0))
                if isinstance(type_answer.get("confidence"), (int, float))
                else 0.0
            ),
        ),
        "usage": result.get("usage", {}),
        "model": result.get("model"),
    }


async def is_transaction_email(
    sender: str,
    subject: str,
    body: str,
) -> float:
    """Return the probability (0.0–1.0) that an email is a transaction.

    A thin convenience wrapper around ``validate_transaction_email()``
    that extracts the ``is_transaction_probability`` field.

    Args:
        sender: Sender email address.
        subject: Email subject line.
        body: Raw email body text.

    Returns:
        A float between 0.0 (definitely not a transaction) and 1.0
        (definitely a transaction).  Returns **0.5** when the API is
        unreachable, representing maximal uncertainty.
    """
    result = await validate_transaction_email(
        sender=sender, subject=subject, body=body
    )
    prob = result.get("is_transaction_probability")
    if prob is None:
        return 0.5
    return prob