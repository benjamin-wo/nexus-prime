"""What voice notes are accepted, and the speech settings."""

import pytest

from nexus.application import speech
from nexus.settings import Settings

DB = "postgresql://nexus:nexus@localhost:5432/nexus"


@pytest.mark.parametrize(
    ("content_type", "audio_format"),
    [
        ("audio/ogg", "ogg"),
        ("audio/ogg; codecs=opus", "ogg"),
        ("AUDIO/WEBM;codecs=opus", "webm"),
        ("audio/mp4", "m4a"),
        ("audio/m4a", "m4a"),
        ("audio/x-m4a", "m4a"),
        ("audio/aac", "aac"),
        ("audio/mpeg", "mp3"),
        ("audio/wav", None),
        ("video/mp4", None),
        ("application/pdf", None),
        ("", None),
    ],
)
def test_content_types_map_to_the_model_s_formats(
    content_type: str, audio_format: str | None
) -> None:
    assert speech.audio_format(content_type) == audio_format


def test_the_web_accepts_what_browsers_record() -> None:
    assert speech.WEB_TYPES == {
        "audio/webm", "audio/ogg", "audio/mp4", "audio/m4a", "audio/aac", "audio/mpeg"
    }  # fmt: skip
    assert speech.base_type("Audio/WebM; codecs=opus") == "audio/webm"


def test_voice_notes_need_an_openrouter_key() -> None:
    off = Settings(_env_file=None, database_url=DB, openrouter_api_key=None)
    assert not off.speech_enabled
    assert off.stt_model == "openai/gpt-4o-mini-transcribe"
    assert off.stt_fallback_model == "openai/whisper-large-v3-turbo"
    on = Settings(_env_file=None, database_url=DB, openrouter_api_key="sk-or-test")
    assert on.speech_enabled


def test_the_models_can_be_changed_and_the_fallback_dropped() -> None:
    settings = Settings(
        _env_file=None, database_url=DB, stt_model="vendor/stt-1", stt_fallback_model=" "
    )
    assert settings.stt_model == "vendor/stt-1"
    assert settings.stt_fallback_model is None
