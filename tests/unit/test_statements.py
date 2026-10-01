"""Reading bank statements exported as CSV. Every statement here is made up."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction
from nexus.domain.statements import (
    AmountSign,
    DateOrder,
    Mapping,
    RowStatus,
    fingerprints,
    guess_date_order,
    parse_amount,
    parse_date,
    read_rows,
    read_table,
    suggest_mapping,
)

# Account details above the header, separate withdrawal and deposit columns.
SPLIT = """Account Details For:,Everyday Savings 000-00000-0
Statement as at:,30 Sep 2026

Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1,Transaction Ref2
28 Sep 2026,POS,4.20,,KOPITIAM,SINGAPORE
27 Sep 2026,ICT,,"5,000.00",ACME PTE LTD,SALARY
26 Sep 2026,POS,6.90,,STARBUCKS,SINGAPORE
"""

# One signed amount column, semicolons, month-first dates.
SIGNED = """Date;Description;Amount;Currency;Balance
09/28/2026;GRAB *RIDE;-42.10;SGD;1000.00
09/25/2026;Refund SHOPEE;34.90;SGD;1042.10
09/13/2026;NETFLIX.COM;-17.98;SGD;1007.20
"""

# A credit card: spending listed as positive, "CR" on payments.
CARD = """Posting Date,Merchant,Amount (SGD)
2026-09-20,JUMBO SEAFOOD,120.00
2026-09-21,PAYMENT - THANK YOU,500.00 CR
2026-09-22,GUARDIAN,(23.50)
"""


def test_the_header_is_found_below_account_details() -> None:
    table = read_table(SPLIT)
    assert table.headers[0] == "Transaction Date"
    assert len(table.rows) == 3


def test_split_columns_are_suggested_and_read() -> None:
    table = read_table(SPLIT)
    mapping = suggest_mapping(table)
    assert mapping is not None
    assert (mapping.date, mapping.debit, mapping.credit, mapping.amount) == (0, 2, 3, None)
    assert mapping.description == (4, 5)
    rows = read_rows(table, mapping)
    assert [(r.day, r.amount, r.direction) for r in rows] == [
        (date(2026, 9, 28), Decimal("4.20"), Direction.OUT),
        (date(2026, 9, 27), Decimal("5000.00"), Direction.IN),
        (date(2026, 9, 26), Decimal("6.90"), Direction.OUT),
    ]
    assert rows[0].description == "KOPITIAM · SINGAPORE"


def test_a_signed_column_with_month_first_dates() -> None:
    table = read_table(SIGNED)
    mapping = suggest_mapping(table)
    assert mapping is not None
    assert mapping.amount == 2 and mapping.currency == 3
    assert mapping.date_order is DateOrder.MDY  # 09/28: 28 can't be a month
    rows = read_rows(table, mapping)
    assert rows[0].direction is Direction.OUT and rows[0].amount == Decimal("42.10")
    assert rows[1].direction is Direction.IN
    assert rows[0].currency == "SGD"


def test_a_card_that_lists_spending_as_positive() -> None:
    table = read_table(CARD)
    mapping = suggest_mapping(table)
    assert mapping is not None and mapping.date_order is DateOrder.YMD
    card = replace(mapping, sign=AmountSign.POSITIVE_IS_OUT)
    rows = read_rows(table, card)
    assert [(r.amount, r.direction) for r in rows] == [
        (Decimal("120.00"), Direction.OUT),
        (Decimal("500.00"), Direction.IN),  # the CR payment
        (Decimal("23.50"), Direction.IN),  # a bracketed refund
    ]


def test_unreadable_rows_are_flagged_not_guessed() -> None:
    table = read_table(
        "Date,Description,Amount\n31/02/2026,Bad day,-5\nsoon,Nope,-3\n01/09/2026,No amount,\n"
    )
    rows = read_rows(table, Mapping(date=0, description=(1,), amount=2))
    assert [(r.status, r.problem) for r in rows] == [
        (RowStatus.UNCLEAR, "can't read the date"),
        (RowStatus.UNCLEAR, "can't read the date"),
        (RowStatus.UNCLEAR, "can't read the amount"),
    ]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("12.30", "12.30"),
        ("-12.30", "-12.30"),
        ("1,234.50", "1234.50"),
        ("(12.30)", "-12.30"),
        ("12.30 DR", "-12.30"),
        ("12.30 CR", "12.30"),
        ("S$ 8.00", "8.00"),
        ("SGD -8", "-8"),
        ("12.30-", "-12.30"),
    ],
)
def test_amounts(text: str, value: str) -> None:
    assert parse_amount(text) == Decimal(value)


@pytest.mark.parametrize("text", ["", "-", "abc", "NaN", "inf"])
def test_not_amounts(text: str) -> None:
    assert parse_amount(text) is None


def test_dates() -> None:
    assert parse_date("28/09/2026", DateOrder.DMY) == date(2026, 9, 28)
    assert parse_date("09/28/2026", DateOrder.MDY) == date(2026, 9, 28)
    assert parse_date("28-09-26", DateOrder.DMY) == date(2026, 9, 28)
    assert parse_date("2026-09-28 13:05", DateOrder.DMY) == date(2026, 9, 28)
    assert parse_date("28 Sep 2026", DateOrder.MDY) == date(2026, 9, 28)
    assert parse_date("Sep 28, 2026", DateOrder.DMY) == date(2026, 9, 28)
    assert parse_date("28-SEP-2026", DateOrder.DMY) == date(2026, 9, 28)
    assert parse_date("31/02/2026", DateOrder.DMY) is None
    assert guess_date_order(["03/04/2026", "05/06/2026"]) is DateOrder.DMY  # no tell: day first


def test_repeated_rows_get_their_own_fingerprints() -> None:
    table = read_table("Date,Description,Amount\n28/09/2026,KOPI,-1.80\n28/09/2026,KOPI,-1.80\n")
    rows = read_rows(table, Mapping(date=0, description=(1,), amount=2))
    prints = fingerprints(rows)
    assert len(set(prints.values())) == 2
    again = fingerprints(
        read_rows(
            read_table("Date,Description,Amount\n28/09/2026,kopi,-1.80\n"),
            Mapping(date=0, description=(1,), amount=2),
        )
    )
    assert again[0] == prints[0]  # the same row in a re-export matches


def test_bad_files_and_mappings_are_refused() -> None:
    with pytest.raises(InvalidInput):
        read_table("")
    with pytest.raises(InvalidInput):
        read_table("Date,Amount\n")
    with pytest.raises(InvalidInput):
        read_table("x" * 2_000_001)
    table = read_table(SIGNED)
    for bad in (
        Mapping(date=9, description=(1,), amount=2),
        Mapping(date=0, description=(), amount=2),
        Mapping(date=0, description=(1,)),
        Mapping(date=0, description=(1,), amount=2, debit=3),
    ):
        with pytest.raises(InvalidInput):
            read_rows(table, bad)


def test_the_same_layout_has_the_same_key() -> None:
    other = SIGNED.replace("GRAB *RIDE", "SOMETHING ELSE")
    assert read_table(SIGNED).header_key == read_table(other).header_key
    assert read_table(SIGNED).header_key != read_table(CARD).header_key
