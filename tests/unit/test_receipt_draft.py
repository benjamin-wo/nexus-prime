"""What a receipt reader's reply is turned into, whatever format the model used."""

from datetime import date

import pytest

from nexus.agent.receipts import ReceiptDraft, caption_date, iso_date


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("2026-09-26", "2026-09-26"),
        ("2026/09/20 21:05", "2026-09-20"),
        ("26/09/2026", "2026-09-26"),  # day first, as Singapore receipts print it
        ("16-2-2013", "2013-02-16"),
        ("24.09.26", "2026-09-24"),
        ("Saturday 16-2-2013 18:00:01", "2013-02-16"),
        ("31/02/2026", None),  # no such day
        ("yesterday", None),
    ],
)
def test_dates_become_iso(printed: str, expected: str | None) -> None:
    assert iso_date(printed) == expected


def test_amounts_keep_just_the_number() -> None:
    def amount(value: object) -> str | None:
        return ReceiptDraft.model_validate({"is_receipt": True, "amount": value}).amount

    assert amount("RM 45.00") == "45.00"
    assert amount("¥1,980") == "1980"
    assert amount(12.4) == "12.4"
    assert amount("n/a") is None
    assert amount(None) is None


def test_an_unreadable_date_is_left_out_not_an_error() -> None:
    draft = ReceiptDraft.model_validate({"is_receipt": True, "amount": "5", "date": "soon"})
    assert draft.date is None


def test_a_caption_can_date_an_undated_receipt() -> None:
    today = date(2026, 9, 28)
    assert caption_date("from yesterday", today) == "2026-09-27"
    assert caption_date("the day before yesterday's lunch", today) == "2026-09-26"
    assert caption_date("today", today) == "2026-09-28"
    assert caption_date("lunch with ann", today) is None
    assert caption_date(None, today) is None
