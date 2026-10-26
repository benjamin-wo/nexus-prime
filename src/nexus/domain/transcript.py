"""Cleaning up what speech-to-text wrote, before the chat agent reads it as if it were typed.

Speech models hear the digits right but format money badly: "eight forty" comes back as
"8:40" or "840", "seventeen ninety nine" as "1799", and "12.50" as "12. 50". They also
invent a sentence out of silence ("Thanks for watching."). This module is pure: it fixes
only what is clearly a mistake and leaves the rest alone, because a wrong guess logs the
wrong amount while a missed fix just makes the agent ask. A real time ("at 7:30 pm",
"meet at 8:40", "at 14:00") is never touched.
"""

import re

HEARD_MAX = 120  # characters of the transcript shown in a "heard:" line
HEARD_MARK = "🎙"

_SPACE = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Sentences speech models make up from silence or music, when they are the last one said.
_TAILS = frozenset(
    {
        "we'll be right back",
        "thanks for watching",
        "thank you for watching",
        "thanks for watching and see you next time",
        "please subscribe",
        "please like and subscribe",
        "see you in the next video",
        "see you next time",
    }
)

# A word that says money is being spent, or something people spend on every day.
_SPEND = re.compile(
    r"\b(?:spent|spend|paid|pay|paying|bought|buy|cost|costs|charged|expense|log|logged|tipped|"
    r"ordered|lunch|dinner|breakfast|brunch|supper|coffee|tea|kopi|snacks?|drinks?|beer|taxi|"
    r"cab|grab|uber|gojek|bus|mrt|fare|parking|toll|groceries|netflix|spotify|subscription|"
    r"hawker|kopitiam|maxwell|food court|tip)\b",
    re.I,
)
# Cheap things: only with one of these is a run-together "840" read as 8.40.
_SMALL = re.compile(
    r"\b(?:lunch|dinner|breakfast|brunch|supper|coffee|tea|kopi|snacks?|drinks?|beer|taxi|cab|"
    r"grab|uber|gojek|bus|mrt|fare|parking|toll|hawker|kopitiam|maxwell|food court)\b",
    re.I,
)
# Things that cost thousands: "1850 for rent" is 1850, not 18.50.
_BIG = re.compile(
    r"\b(?:rent|salary|mortgage|loan|tuition|deposit|laptop|phone|flight|insurance|bonus|car|"
    r"invoice|wage|payslip|tax|holiday|trip)\b",
    re.I,
)
# Words that make a clock-like figure a time.
_CLOCK = re.compile(
    r"\b(?:meet|meeting|appointment|alarm|wake|remind|reminder|schedule|scheduled|leaves?|"
    r"departs?|arrives?|starts?|begins?|ends?|opens?|closes?|tonight|tomorrow|later|next|"
    r"o'clock|this (?:morning|afternoon|evening))\b",
    re.I,
)
_TIME_PREPOSITIONS = frozenset(
    {"at", "by", "from", "until", "till", "before", "after", "around", "since", "past", "between"}
)
_NUMBER = re.compile(r"\d+(?:[:.,]\d+)*")
_ORDINAL = re.compile(r"(?:st|nd|rd|th)\b", re.I)
_DAYTIME = re.compile(r"\s*(?:[ap]\.?m\b|o'clock|hrs\b|hours?\b|%)", re.I)
_PREVIOUS_WORD = re.compile(r"(\w+)\W*$")
_SPLIT_PAIR = re.compile(
    r"(?<![\d.])(\d{1,3})\.\s(\d{2})"
    r"(?=\s*(?:[.!?,]|$)|\s+(?:yesterday|today|last|on|at|for|with|split)\b)"
)
_BARE_DOLLAR = re.compile(r"(?<![A-Za-z])\$\s?(?=\d)")
_CODES = re.compile(
    r"\b(?:USD|SGD|AUD|CAD|NZD|HKD|EUR|GBP|JPY|MYR|IDR|THB|INR|CNY|KRW|CHF|PHP|VND|TWD)\b"
)
_NAMED_DOLLARS = re.compile(
    r"\b(?:US|American|Singapore|Australian|Canadian|Hong Kong|New Zealand) dollars?\b", re.I
)


def _plain(sentence: str) -> str:
    """A sentence for comparing: lower case, no punctuation but apostrophes."""
    text = sentence.lower().replace("\u2019", "'")
    return _SPACE.sub(" ", re.sub(r"[^a-z0-9' ]", " ", text)).strip()


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s]


def _drop_tails(sentences: list[str]) -> list[str]:
    while sentences and _plain(sentences[-1]) in _TAILS:
        sentences = sentences[:-1]
    return sentences


def _amount(sentence: str) -> str:
    """The sentence with its one clock-like or run-together figure read as a price, when
    it is clearly a spend phrase."""
    if not _SPEND.search(sentence) or _CLOCK.search(sentence):
        return sentence
    numbers = [m for m in _NUMBER.finditer(sentence) if not _ORDINAL.match(sentence, m.end())]
    if len(numbers) != 1:  # no figure, or another amount: leave it
        return sentence
    found = numbers[0]
    token, start, end = found.group(0), found.start(), found.end()
    if sentence[:start].rstrip().endswith("$") or _DAYTIME.match(sentence, end):
        return sentence
    before = _PREVIOUS_WORD.search(sentence[:start])
    if before and before.group(1).lower() in _TIME_PREPOSITIONS:
        return sentence
    fixed: str | None = None
    if re.fullmatch(r"\d{1,2}:[0-5]\d", token):
        hour, minutes = token.split(":")
        if minutes != "00":  # "6:00" could as well be 60: don't guess
            fixed = f"{hour}.{minutes}"
    elif re.fullmatch(r"\d{4}", token):
        # Not a year, not round ("1800" is 1800), and not something that costs thousands.
        if not 1900 <= int(token) <= 2100 and token[2:] != "00" and not _BIG.search(sentence):
            fixed = f"{token[:2]}.{token[2:]}"
    elif re.fullmatch(r"\d{3}", token):
        # Only a cheap everyday thing, at 3.00 or more ("dinner 120" is 120).
        if int(token[0]) >= 3 and token[1:] != "00" and _SMALL.search(sentence):
            fixed = f"{token[0]}.{token[1:]}"
    return sentence[:start] + fixed + sentence[end:] if fixed else sentence


def _home_dollars(text: str, home_currency: str) -> str:
    """A "$" with no other currency named means the user's own: the sign is dropped, so
    the agent reads the amount in the home currency as it does for typed "12.50"."""
    named = {code for code in _CODES.findall(text) if code != home_currency.upper()}
    if named or _NAMED_DOLLARS.search(text):
        return text
    return _BARE_DOLLAR.sub("", text)


def tidy_transcript(text: str, home_currency: str) -> str:
    """The transcript as the user would have typed it: one line, a made-up closing
    sentence dropped, "8:40" or "840" in a spending sentence read as 8.40, "12. 50" as
    12.50, and a bare "$" as ``home_currency``."""
    text = _SPACE.sub(" ", text).strip()
    text = " ".join(_drop_tails(_sentences(text)))
    if _SPEND.search(text):
        text = _SPLIT_PAIR.sub(r"\1.\2", text)
    text = " ".join(_amount(s) for s in _sentences(text))
    return _home_dollars(text, home_currency)


def heard_line(transcript: str) -> str:
    """The line that tells the user what Nexus understood from their voice note."""
    said = transcript.rstrip(" .")  # 'heard: "Grab 12.50"', not 'heard: "Grab 12.50."'
    shown = said if len(said) <= HEARD_MAX else said[: HEARD_MAX - 1] + "…"
    return f'{HEARD_MARK} heard: "{shown}"'
