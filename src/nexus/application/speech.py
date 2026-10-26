"""Voice notes: what is accepted, and how long and large it may be.

The same limits hold on Telegram and the web, so a note either channel takes is one the
other would take too. Audio is passed straight to the speech model; nothing converts it.
"""

# Two minutes of speech is far more than a money command needs, and bounds the cost.
MAX_SECONDS = 120
MAX_BYTES = 5 * 1024 * 1024

TOO_LONG = "That's too long — keep voice notes under 2 minutes."
NOT_SET_UP = "Voice notes aren't set up — mind typing it?"
UNCLEAR = "Couldn't make that out — mind typing it?"
UNSUPPORTED = "I can't read that kind of audio. Try a regular voice note."

# Content type (no parameters) -> the format name the speech model is told.
_FORMATS = {
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/webm": "webm",
    "video/webm": "webm",  # some browsers label an audio-only recording this way
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "aac",
    "audio/x-aac": "aac",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
}
# What the web endpoint accepts (the recorders browsers have, plus MP3 files).
WEB_TYPES = frozenset(
    {"audio/webm", "audio/ogg", "audio/mp4", "audio/m4a", "audio/aac", "audio/mpeg"}
)


def base_type(content_type: str) -> str:
    """The media type without parameters, lower case: "audio/webm;codecs=opus" -> "audio/webm"."""
    return content_type.split(";", 1)[0].strip().lower()


def audio_format(content_type: str) -> str | None:
    """The speech model's format name for a content type; None if it isn't audio we take."""
    return _FORMATS.get(base_type(content_type))
