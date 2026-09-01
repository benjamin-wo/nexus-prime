"""Safety kernel: the deterministic checks that must never be delegated to the LLM."""

from __future__ import annotations

import re


TERMINATION_INTENTS = {
    "stop", "stop it", "cancel", "cancel that", "never mind", "nevermind",
    "forget it", "forget about it", "that's enough", "that's all", "thats all",
    "i'm done", "im done", "i'm good", "im good", "all good", "ok", "okay",
    "ok stop", "okay stop", "that's it", "thats it", "drop it", "quit",
    "enough", "no more", "stop talking", "shut up", "leave it",
    "that's all for now", "thats all for now", "nothing else", "done for now",
    "bye", "goodbye", "see you", "see ya", "good night", "goodnight",
    "no thanks", "not now", "maybe later", "later", "i'll get back to you",
}

# Greetings / thanks / acknowledgments that never need a tool call (or even
# the LLM). Exact-match phrases after normalization (lowercased, punctuation
# stripped); the value is the canned reply. Kept deliberately narrow so a
# real request ("hi can you log 15 bucks") never matches.
_TRIVIAL_GREETINGS = {
    "hi", "hello", "hey", "heya", "hiya", "yo", "sup", "howdy", "hi there",
    "hello there", "hey there", "good morning", "good afternoon", "good evening",
    "morning", "afternoon", "evening", "greetings",
}
_TRIVIAL_THANKS = {
    "thanks", "thank you", "thx", "ty", "thanks a lot", "thank you so much",
    "thanks so much", "appreciated", "appreciate it", "cheers", "tysm",
    "thanks mate", "thanks a bunch",
}
_TRIVIAL_BYE = {
    "bye", "goodbye", "bye bye", "good night", "goodnight", "see you",
    "see ya", "cya", "later", "catch you later",
}
_TRIVIAL_ACK = {
    "ok", "okay", "k", "cool", "nice", "great", "awesome", "perfect",
    "got it", "understood", "noted", "alright", "sure", "sounds good",
    "nice one", "no problem", "np", "haha", "lol", "ok thanks", "okay thanks",
    "thanks ok", "yes", "yep", "yeah", "sure thing", "done", "that works",
}
_TRIVIAL_HOWAREYOU = {
    "how are you", "how's it going", "how are you doing", "how r u",
    "whats up", "what's up", "how is it going", "you good",
}

_TRIVIAL_REPLIES: dict = {
    phrase: None
    for phrase in set().union(
        _TRIVIAL_GREETINGS,
        _TRIVIAL_THANKS,
        _TRIVIAL_BYE,
        _TRIVIAL_ACK,
        _TRIVIAL_HOWAREYOU,
    )
}


def _normalize_trivial(text: str) -> str:
    lowered = (text or "").strip().lower()
    lowered = re.sub(r"^[^a-z0-9]+", "", lowered)  # strip leading punctuation/"ok "
    lowered = re.sub(r"[^a-z0-9' ]+", "", lowered)  # strip punctuation
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def is_trivial_message(text: str) -> str:
    """Return a canned reply when `text` is pure small talk that needs no
    tools and no LLM; return "" otherwise. Never matches anything with a
    number, currency symbol, or a real request-shaped phrase."""
    if not text or len(text) > 60:
        return ""
    if re.search(r"\d", text):
        return ""
    normalized = _normalize_trivial(text)
    if not normalized or len(normalized) > 30:
        return ""
    if normalized not in _TRIVIAL_REPLIES:
        return ""
    if normalized in _TRIVIAL_BYE:
        return "Bye! 👋 Take care — ping me anytime."
    if normalized in _TRIVIAL_THANKS:
        return "Anytime! 😊 Let me know if you need anything else."
    if normalized in _TRIVIAL_HOWAREYOU:
        return "Doing great, thanks for asking! ⚡ What can I help you with?"
    if normalized in _TRIVIAL_ACK:
        return "👍 Got it."
    return "Hey! 👋 What can I help you with?"


def is_termination_intent(text: str) -> bool:
    """True for explicit stop/closing commands so the kernel terminates the
    thread instead of routing it anywhere."""
    lowered = (text or "").strip().lower()
    if not lowered or len(lowered) > 60:
        return False
    if lowered in TERMINATION_INTENTS:
        return True
    return re.fullmatch(r"stop(?:!|\.)*", lowered) is not None
