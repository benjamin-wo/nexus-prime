"""What the user is asked to confirm. One line per ledger entry, in words a person reads
("Delete 5 Nov · EUR 14.00 from Acme Rentals (income)?"), and several entries asked about
in one turn put together in one message. Pure text, no I/O; the same text goes to Telegram
and the web chat."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from nexus.domain.ledger import Direction, Transaction
from nexus.domain.money import Money, minor_units


class Ask(str):
    """One ledger entry to act on, and the sentence that asks about it alone ("Delete 5 Nov
    · EUR 14.00 from Acme Rentals (income)?"). It is a plain ``str`` to anything that only
    shows it; ``combine`` takes its parts to put several into one message.

    ``action`` is the verb ("Delete", "Change"), ``entry`` the entry in words, ``detail``
    what is asked of it (": category → Travel")."""

    action: str
    entry: str
    detail: str

    def __new__(cls, action: str, entry: str, detail: str = "") -> "Ask":
        self = super().__new__(cls, f"{action} {entry}{detail}?")
        self.action, self.entry, self.detail = action, entry, detail
        return self

    def bullet(self) -> str:
        return f"• {self.entry}{self.detail}"


def short_day(day: date, today: date) -> str:
    """ "5 Nov", with the year when it isn't this year."""
    return f"{day:%-d %b}" if day.year == today.year else f"{day:%-d %b %Y}"


def short_money(money: Money) -> str:
    """ "EUR 14.00", "SGD 1,240.00"."""
    shown = money.amount.quantize(Decimal(1).scaleb(-minor_units(money.currency)))
    return f"{money.currency} {shown:,}"


def entry_text(tx: Transaction, day: date, today: date, category: str | None) -> str:
    """An entry for a person: "5 Nov · EUR 14.00 from Acme Rentals (income)" or
    "5 Nov · SGD 12.40 at Kopi Corner (Dining Out)". No ids, notes or signs."""
    text = f"{short_day(day, today)} · {short_money(tx.amount)}"
    if tx.counterparty:
        text += f" {'from' if tx.direction is Direction.IN else 'at'} {tx.counterparty}"
    label = "income" if tx.direction is Direction.IN else category
    return f"{text} ({label})" if label else text


def combine(parts: Sequence[str]) -> str:
    """One message for everything waiting for the user's yes.

    - Other questions (plain text) are joined line by line, as they always were.
    - Entries all asked about in the same way: one entry is a sentence; several are
      "Delete 2 entries?" with a bullet each.
    - A mix: "Confirm these changes?" with a bullet each, naming its action."""
    asks = [p for p in parts if isinstance(p, Ask)]
    if not asks:
        return "\n".join(parts)
    if len(asks) == len(parts) and len({a.action for a in asks}) == 1:
        if len(asks) == 1:
            return str(asks[0])
        return "\n".join([f"{asks[0].action} {len(asks)} entries?", *(a.bullet() for a in asks)])
    lines = [
        f"• {p.action} {p.entry}{p.detail}" if isinstance(p, Ask) else f"• {p.rstrip('?')}"
        for p in parts
    ]
    return "\n".join(["Confirm these changes?", *lines])
