"""CSV export of the ledger. Cells that a spreadsheet would run as a formula are
neutralised, and no links are included."""

import csv
import io
from collections.abc import Iterable
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application.fx import Conversion
from nexus.domain.ledger import Category, Transaction, Wallet

COLUMNS = ["date", "direction", "amount", "currency", "home_amount", "home_currency", "fx_rate",
           "fx_rate_date", "counterparty", "category", "notes", "status", "source", "from_wallet",
           "to_wallet"]  # fmt: skip
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n")


def neutralise(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_START) else value


def to_csv(
    transactions: Iterable[Transaction],
    categories: dict[UUID, Category],
    tz: ZoneInfo,
    home_currency: str,
    conversions: dict[UUID, Conversion],
    wallets: dict[UUID, Wallet] | None = None,
) -> str:
    """Home-currency columns are blank when a foreign row has no available rate. The wallet
    columns are filled for moves only."""
    named = wallets or {}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for tx in transactions:
        category = categories.get(tx.category_id) if tx.category_id else None
        home = conversions.get(tx.id)
        home_amount = tx.amount if tx.amount.currency == home_currency else (home and home.home)
        rate = home.rate if home else None
        row = [
            tx.occurred_at.astimezone(tz).date().isoformat(),
            tx.direction.value,
            str(tx.amount.amount),
            tx.amount.currency,
            str(home_amount.amount) if home_amount else "",
            home_currency if home_amount else "",
            str(rate.value) if rate else "",
            rate.effective.isoformat() if rate else "",
            tx.counterparty or "",
            category.name if category else "",
            tx.notes or "",
            tx.status.value,
            tx.source.value,
            named[tx.from_wallet_id].name if tx.from_wallet_id in named else "",
            named[tx.to_wallet_id].name if tx.to_wallet_id in named else "",
        ]
        writer.writerow([neutralise(cell) for cell in row])
    return out.getvalue()
