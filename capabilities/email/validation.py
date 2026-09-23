"""
Laya model wrapper — transaction email validation.

Provides lazy-loaded Laya model with ``asyncio.Lock`` guard, email
transaction detection via typed questions (noul + choice), and graceful
degradation when Laya is not installed.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

# ── Module-level lock and cache ──────────────────────────────────────────────

_model_lock = asyncio.Lock()
_model: Optional[Any] = None

# ── Graceful degradation if Laya is not installed ────────────────────────────

try:
    import laya as _laya_module  # type: ignore[no-redef]
    from laya.email import clean_email_body as _clean_email_body
    from laya.email import email_state as _email_state

    LAYA_AVAILABLE = True
except ImportError:
    _laya_module = None
    _clean_email_body = None  # type: ignore[assignment]
    _email_state = None  # type: ignore[assignment]
    LAYA_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Laya agent loading (async, lock-guarded)
# ═══════════════════════════════════════════════════════════════════════════════


async def load_agent(
    model_id_or_path: str = "convaiinnovations/laya",
    device: Optional[str] = None,
    token: Optional[str] = None,
    subfolder: Optional[str] = None,
) -> Any:
    """Load a Laya System-1 decision model.

    This wraps ``laya.load()``.  Loading is guarded by an ``asyncio.Lock``
    so that concurrent callers share a single model instance.  The loaded
    model is cached in the module-level ``_model`` variable.

    Args:
        model_id_or_path: HuggingFace repo ID or local path.
            Default: ``"convaiinnovations/laya"``.
        device: Torch device string (``"cpu"``, ``"cuda"``, ``"mps"``)
            or ``None`` for auto-detect (CUDA → MPS → CPU fallback).
        token: HuggingFace auth token for gated models.
        subfolder: Repo subfolder for alternative checkpoints, e.g.
            ``"multilingual"`` or ``"typed-decisions"``.

    Returns:
        A ``laya.agent.Agent`` instance with a ``predict()`` method, or
        ``None`` if Laya is not installed (graceful degradation).

    Model cache:
        The ``huggingface_hub`` default cache at
        ``~/.cache/huggingface/hub`` is used.  Override with the
        ``HF_HOME`` environment variable.
    """
    if not LAYA_AVAILABLE:
        return None

    global _model
    async with _model_lock:
        if _model is None:
            _model = _laya_module.load(
                model_id_or_path=model_id_or_path,
                device=device,
                token=token,
                subfolder=subfolder,
            )
    return _model


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Transaction detection questions
# ═══════════════════════════════════════════════════════════════════════════════

_TRANSACTION_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "is_transaction": {
        "type": "noul",
        "instructions": (
            "Is this email a financial transaction receipt, payment "
            "confirmation, invoice, order summary, billing statement, "
            "or any other record of a financial transaction?"
        ),
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
            "spam_phishing": (
                "Spam or phishing attempt: unsolicited, suspicious links, "
                "urgent requests for personal information"
            ),
            "other": "None of the above categories",
        },
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# 3. High-level public API
# ═══════════════════════════════════════════════════════════════════════════════


async def validate_transaction_email(
    sender: str,
    subject: str,
    body: str,
) -> Dict[str, Any]:
    """Classify an email as a transaction receipt using the Laya model.

    Builds a structured state from the email fields (cleaning the body
    first), asks two typed questions, and returns the model's answers
    with confidence scores.

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

        When Laya is not installed or the model cannot be loaded, returns
        a fallback dict with ``is_transaction=None``,
        ``is_transaction_probability=None``, ``email_type="unknown"``,
        and ``confidence=0.0``.
    """
    agent = await load_agent()
    if agent is None:
        return {
            "is_transaction": None,
            "is_transaction_probability": None,
            "email_type": "unknown",
            "email_type_probabilities": {},
            "confidence": 0.0,
            "usage": {},
            "model": None,
        }

    # Clean quoted history & disclaimers; build structured state
    cleaned_body = _clean_email_body(body, max_chars=3000)
    state = _email_state(
        subject=subject,
        body=cleaned_body,
        sender=sender,
        clean=False,  # already cleaned above
    )

    # Evaluate — agent.predict is synchronous
    result: Dict[str, Any] = agent.predict(state, _TRANSACTION_QUESTIONS)

    answers = result.get("answers", {})
    is_tx_answer = answers.get("is_transaction", {})
    type_answer = answers.get("email_type", {})

    is_tx_noul = is_tx_answer.get("noul", 0.0)
    is_tx: bool | None = is_tx_noul > 0.5 if is_tx_noul is not None else None

    return {
        "is_transaction": is_tx,
        "is_transaction_probability": is_tx_noul,
        "email_type": type_answer.get("choice", "unknown"),
        "email_type_probabilities": type_answer.get("probabilities", {}),
        "confidence": max(
            is_tx_answer.get("confidence", 0.0),
            type_answer.get("confidence", 0.0),
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
        (definitely a transaction).  Returns **0.5** when Laya is not
        installed, representing maximal uncertainty.
    """
    result = await validate_transaction_email(
        sender=sender, subject=subject, body=body
    )
    prob = result.get("is_transaction_probability")
    if prob is None:
        return 0.5
    return prob