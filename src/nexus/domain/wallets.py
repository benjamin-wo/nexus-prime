"""Telling which wallet a line of text is about, by the wallet's match words.

Pure rules, no I/O. The same matching as category rules (whole words and phrases, any
case): "ibkr" is in "IBKR top-up" but not in "fibkro". The Spending wallet never matches:
it is where everything else is.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from nexus.domain.ledger import Wallet, WalletKind
from nexus.domain.rules import matches, normalize


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
