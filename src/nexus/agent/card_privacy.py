"""Card numbers in what a user sends, cut down to their last four before any model or the
chat log sees them (moved out of ``service``)."""

from dataclasses import replace

from nexus.agent.image_look import ImageLook
from nexus.domain.private import hide_card_numbers


def _hidden(text: str) -> tuple[str, bool]:
    """What the user sent with any card number cut down to its last four, and whether one
    was. Every way words reach the agent (typed, spoken, a caption, text read from an image
    or PDF) passes through here before they are shown to a model or kept anywhere."""
    hidden = hide_card_numbers(text)
    return hidden, hidden != text


def _hidden_caption(caption: str | None) -> tuple[str | None, bool]:
    if not caption:
        return caption, False
    return _hidden(caption)


def _hidden_look(look: ImageLook | None) -> ImageLook | None:
    """The look at an image with any card number in what it read cut down to its last
    four; the very same look when there is none."""
    if look is None:
        return None
    text, hid_text = _hidden(look.text)
    summary, hid_summary = _hidden(look.summary)
    return replace(look, summary=summary, text=text) if hid_text or hid_summary else look
