"""Speech to text through OpenRouter: ``POST /api/v1/audio/transcriptions`` with the audio
as base64 in JSON, answered with ``{"text": ..., "usage": {"seconds", "cost", ...}}``.

The first model gets a short neutral prompt that makes it write money as "$12.50" instead
of "12:50" (96% of amounts exact in the bake-off, against 76% without). The fallback runs
without a prompt: prompting Whisper through some providers returns nothing at all.

When the caller knows names the user uses (people they split with), the first model's
prompt also lists up to 20, so it writes "Ann" rather than "Anne". The fallback never
gets them.

Audio and transcripts are never logged. A log line holds the model, the audio's seconds
and the cost.
"""

import base64
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from nexus.application.ports import SpeechError, Transcript

log = logging.getLogger(__name__)

URL = "https://openrouter.ai/api/v1/audio/transcriptions"
TIMEOUT = 15.0  # seconds, for each model tried
# Says nothing about what will be said: the bake-off prompt shared no words with its clips.
PROMPT = (
    "Voice note to a personal expense tracker. Write money amounts as digits with a dollar "
    "sign and a decimal point, for example $4.20, $35.75, $6.05, $2.3k."
)


MAX_NAMES = 20
MAX_NAME_LENGTH = 40


def vocabulary(names: Sequence[str]) -> str:
    """The sentence that lists names for the prompt ("" when there are none). Only letters,
    spaces, hyphens and apostrophes get through, so a name can't carry instructions; a
    name over 40 characters is dropped, and at most 20 are listed."""
    clean: dict[str, None] = {}
    for name in names:
        letters = "".join(c if c.isalpha() or c in "-'" else " " for c in name)
        word = " ".join(letters.split()).strip("-' ")
        if word and len(word) <= MAX_NAME_LENGTH:
            clean.setdefault(word)
    return f" Names that may come up: {', '.join(list(clean)[:MAX_NAMES])}." if clean else ""


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class OpenRouterSpeech:
    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        model: str,
        fallback_model: str | None = None,
        *,
        url: str = URL,
    ) -> None:
        self._http = http
        self._key = api_key
        self._model = model
        self._fallback = fallback_model
        self._url = url

    async def transcribe(
        self, audio: bytes, audio_format: str, names: Sequence[str] = ()
    ) -> Transcript:
        encoded = base64.b64encode(audio).decode()
        try:
            return await self._ask(
                self._model, encoded, audio_format, prompt=PROMPT + vocabulary(names)
            )
        except SpeechError as first:
            if not self._fallback or self._fallback == self._model:
                raise
            log.warning("%s failed (%s); trying %s", self._model, first, self._fallback)
        return await self._ask(self._fallback, encoded, audio_format, prompt=None)

    async def _ask(
        self, model: str, encoded: str, audio_format: str, *, prompt: str | None
    ) -> Transcript:
        body: dict[str, Any] = {
            "model": model,
            "input_audio": {"data": encoded, "format": audio_format},
            "language": "en",
            "temperature": 0,
        }
        if prompt:
            body["provider"] = {"options": {"openai": {"prompt": prompt}}}
        try:
            response = await self._http.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise SpeechError(f"{model}: request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise SpeechError(f"{model}: HTTP {response.status_code}")
        try:
            data = response.json()
            text = data["text"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SpeechError(f"{model}: unexpected response") from exc
        if not isinstance(text, str):
            raise SpeechError(f"{model}: unexpected response")
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        seconds, cost = _number(usage.get("seconds")), _number(usage.get("cost"))
        log.info(
            "transcribed with %s: %s s of audio, cost $%s",
            model,
            "?" if seconds is None else f"{seconds:.1f}",
            "?" if cost is None else f"{cost:.6f}",
        )
        return Transcript(text.strip(), model, seconds, cost)
