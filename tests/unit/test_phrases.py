"""The fixed messages in each voice: only the wording changes, never the facts; the default is
today's exact text; a joke never lands on a bill, a budget, a debt or a change. Made-up data."""

import re

import pytest

from nexus.domain.phrases import SENSITIVE, Phrase, phrase
from nexus.domain.voice import DEFAULT, Emoji, Preset, VoiceSettings, changed, settings_for

# Values for every key. Each is checked to be in the text, in every voice.
VALUES: dict[Phrase, dict[str, str]] = {
    Phrase.LOGGED_EXPENSE: {"amount": "SGD 2.20", "where": " at Kopi Corner"},
    Phrase.LOGGED_INCOME: {"amount": "SGD 20.00", "source": " from Ann"},
    Phrase.LOGGED_SALARY: {"amount": "SGD 4,200.00"},
    Phrase.RECORDED_INCOME: {"amount": "SGD 150.00", "what": "income", "source": " from Acme"},
    Phrase.RECEIPT_LOGGED: {"entry": "2026-11-05 · -12.40 SGD · Din Tai Fung"},
    Phrase.UNDONE: {"kind": "expense", "what": "SGD 2.20 Kopi Corner"},
    Phrase.SKIPPED: {},
    Phrase.EMAIL_EXPENSE: {"money": "SGD 12.40", "where": " at Din Tai Fung", "day": "5 Nov"},
    Phrase.EMAIL_INCOME: {"money": "SGD 80.00", "sender": " from Ann", "day": "5 Nov"},
    Phrase.EMAIL_BOOKING: {
        "booking": "flight to Tokyo",
        "money": "SGD 640.00",
        "where": " at Sky Air",
        "day": "5 Nov",
        "on": " It's on your Tokyo trip.",
    },
    Phrase.CONFIRM_MANY: {},
    Phrase.CONFIRM_COUNT: {"action": "Delete", "count": "3"},
    Phrase.BUDGET_USED: {
        "threshold": "80",
        "what": "Dining Out budget",
        "month": "November",
        "used": "SGD 160.00 of SGD 200.00",
    },
    Phrase.BUDGET_REACHED: {
        "what": "overall budget",
        "month": "November",
        "used": "SGD 1,000.00 of SGD 1,000.00",
        "percent": "100",
    },
    Phrase.BILL_REMINDER: {"label": "Electricity", "due": "due in 3 days"},
}

# Today's exact text for each key: the default voice must never drift from it.
DEFAULT_TEXT: dict[Phrase, str] = {
    Phrase.LOGGED_EXPENSE: "Logged SGD 2.20 at Kopi Corner.",
    Phrase.LOGGED_INCOME: "Logged SGD 20.00 received from Ann.",
    Phrase.LOGGED_SALARY: "Logged SGD 4,200.00 salary. Enjoy payday! 🎉",
    Phrase.RECORDED_INCOME: "Recorded SGD 150.00 income from Acme.",
    Phrase.RECEIPT_LOGGED: "Logged from receipt: 2026-11-05 · -12.40 SGD · Din Tai Fung",
    Phrase.UNDONE: "Undone: the expense of SGD 2.20 Kopi Corner.",
    Phrase.SKIPPED: "Skipped. Nothing was logged.",
    Phrase.EMAIL_EXPENSE: "📧 From your email: SGD 12.40 at Din Tai Fung on 5 Nov. Log it?",
    Phrase.EMAIL_INCOME: (
        "📧 From your email: SGD 80.00 came in from Ann on 5 Nov. Log it as money in?"
    ),
    Phrase.EMAIL_BOOKING: (
        "📧 From your email: a flight to Tokyo, SGD 640.00 at Sky Air on 5 Nov. "
        "It's on your Tokyo trip. Log the cost?"
    ),
    Phrase.CONFIRM_MANY: "Confirm these changes?",
    Phrase.CONFIRM_COUNT: "Delete 3 entries?",
    Phrase.BUDGET_USED: "You've used 80% of your Dining Out budget for November: "
    "SGD 160.00 of SGD 200.00.",
    Phrase.BUDGET_REACHED: "You've reached your overall budget for November: "
    "SGD 1,000.00 of SGD 1,000.00 (100%).",
    Phrase.BILL_REMINDER: "Reminder: Electricity is due in 3 days.",
}

PRESETS = [settings_for(p) for p in Preset]
# Emoji dials alone don't change the wording; a voice with its emoji left on shows them.
EMOJI_ON = [settings_for(p) for p in Preset if settings_for(p).emoji is not Emoji.NONE]


def test_every_key_has_values_and_default_text_here() -> None:
    assert set(VALUES) == set(Phrase) == set(DEFAULT_TEXT)


@pytest.mark.parametrize("key", list(Phrase))
def test_the_default_voice_is_todays_exact_text(key: Phrase) -> None:
    assert phrase(key, DEFAULT, **VALUES[key]) == DEFAULT_TEXT[key]


@pytest.mark.parametrize("key", list(Phrase))
@pytest.mark.parametrize("voice", PRESETS, ids=[v.preset.value for v in PRESETS])
def test_every_voice_keeps_every_fact(key: Phrase, voice: VoiceSettings) -> None:
    text = phrase(key, voice, **VALUES[key])
    for name, value in VALUES[key].items():
        assert value.strip() in text, (name, value, text)
    assert text.strip() == text and "  " not in text
    assert "{" not in text and "}" not in text
    assert text.endswith(("?", ".")) or key is Phrase.RECEIPT_LOGGED or "!" in text


@pytest.mark.parametrize("key", list(Phrase))
def test_a_question_stays_a_question(key: Phrase) -> None:
    asked = DEFAULT_TEXT[key].endswith("?")
    for voice in PRESETS:
        assert phrase(key, voice, **VALUES[key]).endswith("?") is asked, voice.preset


@pytest.mark.parametrize("key", list(Phrase))
def test_direct_and_chill_say_it_their_own_way(key: Phrase) -> None:
    direct = phrase(key, settings_for(Preset.DIRECT), **VALUES[key])
    chill = phrase(key, settings_for(Preset.CHILL), **VALUES[key])
    default = phrase(key, DEFAULT, **VALUES[key])
    assert chill != default
    assert direct != default or key is Phrase.CONFIRM_COUNT  # "Delete 3 entries?" is as short
    assert direct != chill or key is Phrase.CONFIRM_COUNT


def test_one_message_in_all_five_voices() -> None:
    said = {
        voice.preset: phrase(Phrase.LOGGED_EXPENSE, voice, **VALUES[Phrase.LOGGED_EXPENSE])
        for voice in PRESETS
    }
    assert said == {
        Preset.DEFAULT: "Logged SGD 2.20 at Kopi Corner.",
        Preset.DIRECT: "Logged: SGD 2.20 at Kopi Corner.",
        Preset.CHILL: "SGD 2.20 at Kopi Corner, done.",
        Preset.HYPE: "Logged SGD 2.20 at Kopi Corner. Nice and tidy! ✅",
        Preset.CHEEKY: "Logged SGD 2.20 at Kopi Corner. Your wallet felt that one.",
    }


def test_direct_has_no_emoji_in_any_wording() -> None:
    direct = settings_for(Preset.DIRECT)
    assert direct.emoji is Emoji.NONE
    for key in Phrase:
        text = phrase(key, direct, **VALUES[key])
        assert text.isascii() or not re.search("[\U0001f000-\U0001faff☀-➿]", text), text


@pytest.mark.parametrize("key", [k for k in Phrase if k in SENSITIVE], ids=lambda k: k.value)
def test_cheeky_uses_the_default_wording_on_sensitive_messages(key: Phrase) -> None:
    cheeky = settings_for(Preset.CHEEKY)
    assert phrase(key, cheeky, **VALUES[key]) == phrase(key, DEFAULT, **VALUES[key])


def test_the_sensitive_messages_are_bills_budgets_confirmations_and_undo() -> None:
    assert SENSITIVE == {
        Phrase.BILL_REMINDER,
        Phrase.BUDGET_USED,
        Phrase.BUDGET_REACHED,
        Phrase.CONFIRM_MANY,
        Phrase.CONFIRM_COUNT,
        Phrase.UNDONE,
    }


def test_cheeky_only_teases_about_everyday_spending() -> None:
    cheeky = settings_for(Preset.CHEEKY)
    teased = [
        key
        for key in Phrase
        if phrase(key, cheeky, **VALUES[key]) != phrase(key, DEFAULT, **VALUES[key])
    ]
    assert teased
    assert not set(teased) & SENSITIVE
    assert Phrase.EMAIL_INCOME not in teased and Phrase.EMAIL_BOOKING not in teased


@pytest.mark.parametrize("key", [Phrase.BILL_REMINDER, Phrase.BUDGET_REACHED])
def test_hype_does_not_cheer_for_bad_news(key: Phrase) -> None:
    text = phrase(key, settings_for(Preset.HYPE), **VALUES[key])
    assert "!" not in text and text == phrase(key, DEFAULT, **VALUES[key])


def test_no_emoji_removes_them_from_the_default_wording_too() -> None:
    quiet = changed(DEFAULT, emoji="none")
    assert quiet.preset is Preset.DEFAULT
    assert phrase(Phrase.LOGGED_SALARY, quiet, **VALUES[Phrase.LOGGED_SALARY]) == (
        "Logged SGD 4,200.00 salary. Enjoy payday!"
    )
    assert phrase(Phrase.EMAIL_EXPENSE, quiet, **VALUES[Phrase.EMAIL_EXPENSE]) == (
        "From your email: SGD 12.40 at Din Tai Fung on 5 Nov. Log it?"
    )


def test_hype_with_no_emoji_keeps_its_words_without_the_pictures() -> None:
    quiet = changed(settings_for(Preset.HYPE), emoji="none")
    assert phrase(Phrase.LOGGED_EXPENSE, quiet, **VALUES[Phrase.LOGGED_EXPENSE]) == (
        "Logged SGD 2.20 at Kopi Corner. Nice and tidy!"
    )


def test_a_value_with_braces_is_kept_as_it_is() -> None:
    text = phrase(Phrase.LOGGED_EXPENSE, DEFAULT, amount="SGD 2.20", where=" at {Kopi} {0}")
    assert text == "Logged SGD 2.20 at {Kopi} {0}."


def test_a_missing_value_is_an_error_not_a_silent_blank() -> None:
    with pytest.raises(KeyError):
        phrase(Phrase.LOGGED_EXPENSE, DEFAULT, amount="SGD 2.20")
