"""Telling which wallet a line of text is about, by the wallet's match words, and which
wallet someone means by "my Citi card". Card details (issuer, product, network, last four
digits) are cleaned here too.

Pure rules, no I/O. The same matching as category rules (whole words and phrases, any
case): "ibkr" is in "IBKR top-up" but not in "fibkro". The Spending wallet never matches:
it is where everything else is.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import CardNetwork, Wallet, WalletKind, clean_text
from nexus.domain.rules import matches, normalize

MAX_ISSUER = 40
MAX_PRODUCT = 60
LAST4_KEPT = "Only the last 4 digits are kept."

# What an expense can be paid with. Investment and savings wallets hold money; they don't
# pay for things.
PAYING_KINDS = frozenset({WalletKind.SPENDING, WalletKind.CARD, WalletKind.CASH, WalletKind.OTHER})


@dataclass(frozen=True, slots=True)
class WalletMatch:
    wallet: Wallet
    word: str  # the match word that found it, as the user wrote it


def match_wallet(parts: Iterable[str | None], wallets: Iterable[Wallet]) -> WalletMatch | None:
    """The wallet whose match word appears in any of ``parts`` (the counterparty or
    description, the notes). When several wallets match, the one with the longest matching
    phrase wins; if two tie, the text is ambiguous and nothing matches."""
    texts = [p for p in parts if p]
    if not texts:
        return None
    found: list[tuple[int, WalletMatch]] = []
    for wallet in wallets:
        if wallet.kind is WalletKind.SPENDING:
            continue
        best: tuple[int, str] | None = None
        for word in wallet.match_words:
            pattern = normalize(word)
            if not pattern or not any(matches(pattern, text) for text in texts):
                continue
            if best is None or len(pattern) > best[0]:
                best = (len(pattern), word)
        if best is not None:
            found.append((best[0], WalletMatch(wallet, best[1])))
    if not found:
        return None
    longest = max(length for length, _ in found)
    top = [m for length, m in found if length == longest]
    return top[0] if len(top) == 1 else None


def wallet_for(parts: Iterable[str | None], wallets: Iterable[Wallet]) -> Wallet | None:
    """``match_wallet``, without saying which word matched."""
    found = match_wallet(parts, wallets)
    return found.wallet if found else None


# --- card details ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Last4:
    digits: str | None
    longer: bool  # more digits were given than four; only the last four are kept


def clean_last4(value: str | None) -> Last4:
    """The last four digits of a card number. Spaces and dashes between digits are fine
    ("4111 1111 1111 1234"); anything else that isn't a digit is refused. If more than four
    digits are given, only the last four are kept, so the rest is never stored or echoed."""
    if value is None or not value.strip():
        return Last4(None, False)
    if not re.fullmatch(r"[0-9][0-9 -]*", value.strip()):
        raise InvalidInput("a card's last digits must be numbers only")
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        raise InvalidInput("give the last 4 digits of the card")
    return Last4(digits[-4:], len(digits) > 4)


def clean_network(value: str | CardNetwork | None) -> CardNetwork | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return CardNetwork(value.strip().casefold() if isinstance(value, str) else value)
    except ValueError as exc:
        options = ", ".join(n.value for n in CardNetwork)
        raise InvalidInput(f"a card's network must be one of: {options}") from exc


def clean_issuer(value: str | None) -> str | None:
    return clean_text(value, field_name="issuer", limit=MAX_ISSUER)


def clean_product(value: str | None) -> str | None:
    return clean_text(value, field_name="product", limit=MAX_PRODUCT)


# --- which wallet did they pay with? ----------------------------------------------------

# Words around a card's name that say nothing about which one it is.
_FILLER = frozenset(
    "my the a an card cards credit debit on with using by via paid pay ending in number "
    "last digits to".split()
)


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def _fields(wallet: Wallet) -> list[str]:
    fields = [wallet.name, *wallet.match_words]
    for part in (wallet.issuer, wallet.product, wallet.network.value if wallet.network else None):
        if part:
            fields.append(part)
    if wallet.issuer and wallet.product:
        fields.append(f"{wallet.issuer} {wallet.product}")
    return fields


def paying_candidates(wallets: Iterable[Wallet], text: str) -> list[Wallet]:
    """The wallets an expense could have been paid with that ``text`` names: a wallet's
    name, or words from its name, issuer, product or network ("citi", "my premiermiles
    card"), or its last four digits ("ending 4321", "citi 4321"). Any case. One wallet
    means a match; none means no such wallet; several means it is ambiguous. Investment and
    savings wallets never match."""
    pool = [w for w in wallets if w.kind in PAYING_KINDS]
    words = _words(text)
    for start in (0, 1):  # as written, then without a leading "my" or "the"
        if start and not (words and words[0] in ("my", "the")):
            break
        wanted = " ".join(words[start:])
        exact = [w for w in pool if " ".join(_words(w.name)) == wanted]
        if exact:
            return exact
    numbers = [w for w in words if w.isdigit() and len(w) >= 4]
    last4 = numbers[-1][-4:] if numbers else None
    tokens = [w for w in words if w not in _FILLER and w not in numbers]
    if not tokens and last4 is None:
        return []
    found: list[Wallet] = []
    for wallet in pool:
        if last4 is not None and wallet.last4 != last4:
            continue
        have = {w for field in _fields(wallet) for w in _words(field)}
        squashed = {"".join(_words(field)) for field in _fields(wallet)}
        if not tokens or all(t in have for t in tokens) or "".join(tokens) in squashed:
            found.append(wallet)
    return found


def card_with_last4(wallets: Iterable[Wallet], last4: str) -> Wallet | None:
    """The user's one card wallet whose last four digits these are; None when there is no
    such card or more than one."""
    found = [w for w in wallets if w.kind is WalletKind.CARD and w.last4 == last4]
    return found[0] if len(found) == 1 else None


# --- card digits in a line of text -----------------------------------------------------

_FULL_NUMBER = re.compile(r"(?<![\d-])(?:\d{4}[ -]){3}(\d{4})(?![\d-])")
_ENDING = re.compile(
    r"(?i)\b(?:card|visa|mastercard|amex|credit|debit)\b[^\n.]{0,30}?\bending\s+"
    r"(?:in\s+|with\s+)?[:#]?\s*(\d{4})(?!\d)"
)
_MASKED = re.compile(r"(?i)(?<![\w*•])(?:(?:x{2,}|\*{2,}|•{2,})[ -]*)+(\d{4})(?!\d)")
_STAR = re.compile(r"(?<![\w*•])[*x•](\d{4})(?!\d)")


def card_last4_in(text: str) -> str | None:
    """The last four digits of the card an email or message says was used ("card ending
    1234", "xxxx-1234", "**** 1234", "*1234", or a whole number, of which only the last four
    are taken). None when it states none, or states two different ones. Only these four
    digits are returned; nothing else of a card number is kept."""
    found: set[str] = set()
    for pattern in (_FULL_NUMBER, _ENDING, _MASKED, _STAR):
        found.update(m.group(1) for m in pattern.finditer(text))
    return found.pop() if len(found) == 1 else None
