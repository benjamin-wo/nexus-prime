"""Voice clips for the evaluation set: short made-up money commands read by synthetic
voices and encoded as Telegram sends them (Opus in Ogg). They live in ``voice/``, with a
``manifest.json`` saying what each one says. A case plays one through the real speech
model (``Turn.audio``) and the same path a voice note takes in production.
"""

import asyncio
import json
from pathlib import Path

CLIPS = Path(__file__).parent / "voice"
MIME = "audio/ogg"


def known(key: str) -> bool:
    return (CLIPS / f"{key}.ogg").exists()


def manifest() -> dict[str, dict[str, object]]:
    """Per clip: the words spoken, the accent, whether it is clean or noisy, its seconds."""
    data: dict[str, dict[str, object]] = json.loads((CLIPS / "manifest.json").read_text())
    return data


async def load(key: str) -> tuple[bytes, str]:
    """The clip's bytes and media type."""
    return await asyncio.to_thread((CLIPS / f"{key}.ogg").read_bytes), MIME
