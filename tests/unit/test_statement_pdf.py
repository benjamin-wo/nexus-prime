"""Reading PDF statements. Every statement here is made up; the card layout follows
a common Singapore credit-card statement, the account one a savings statement."""

from datetime import date
from decimal import Decimal

import pytest

from nexus.application.statements import PDF_LAYOUT, read_pdf
from nexus.domain.errors import InvalidInput
from nexus.domain.statement_pdf import Kind, read_statement_lines, statement_date
from nexus.domain.statements import read_rows, read_table
from nexus.infra.pdf.text import PasswordNeeded, pdf_lines
from tests.pdfs import make_pdf

CARD = [
    "Statement Summary",
    "Customer Name Credit Limit SGD 10,000 Statement Date 13 SEP 2026",
    "EXAMPLE CARD 0000-0000-0000-0000 A N OTHER",
    "Post Trans Description of Transaction Transaction Amount",
    "Date Date SGD",
    "PREVIOUS BALANCE 120.00",
    "17 AUG 16 AUG PAYMENT - THANK YOU 120.00 CR",
    "Ref No. : 00000000000000000000000",
    "18 AUG 16 AUG KOPI CORNER SINGAPORE 4.20",
    "Ref No. : 00000000000000000000001",
    "20 AUG 19 AUG 1234567 BUS/MRT SINGAPORE 2.10",
    "Ref No. : 00000000000000000000002",
    "07 SEP 05 SEP SUNSET CAFE BALI 28.50",
    "Ref No. : 00000000000000000000003",
    "IDR 350,000.00",
    "09 SEP 08 SEP ONLINE STORE REFUND 10.00CR",
    "SUB TOTAL 24.80",
    "TOTAL BALANCE FOR EXAMPLE CARD 24.80",
    "Please check the entries above. 14 days to raise errors.",
]

ACCOUNT = [
    "Savings Account Statement",
    "Statement Date 30/09/2026",
    "Date Description Withdrawal Deposit Balance",
    "01/09/2026 Balance Brought Forward 1,000.00",
    "02/09/2026 NETS PURCHASE 12.30 987.70",
    "KOPI CORNER",
    "05/09/2026 FAST TRANSFER 40.00 1,027.70",
    "FROM ANN",
    "25/09/2026 SALARY GIRO 5,000.00 6,027.70",
    "Balance Carried Forward 6,027.70",
]


def test_a_card_statement_reads_and_reconciles() -> None:
    found = read_statement_lines(CARD)
    assert found.kind is Kind.CARD and found.statement_date == date(2026, 9, 13)
    assert [(r.day, r.amount) for r in found.rows] == [
        (date(2026, 8, 16), Decimal("120.00")),  # the payment is money in
        (date(2026, 8, 16), Decimal("-4.20")),
        (date(2026, 8, 19), Decimal("-2.10")),  # the number after the date isn't a year
        (date(2026, 9, 5), Decimal("-28.50")),
        (date(2026, 9, 8), Decimal("10.00")),
    ]
    assert found.rows[3].description == "SUNSET CAFE BALI (IDR 350,000.00)"
    assert found.rows[1].description == "KOPI CORNER SINGAPORE"  # no Ref No. appended
    assert (found.opening, found.closing, found.reconciles) == (
        Decimal("120.00"), Decimal("24.80"), True,
    )  # fmt: skip


def test_rows_that_dont_add_up_are_reported() -> None:
    missing = [line for line in CARD if "KOPI" not in line]
    assert read_statement_lines(missing).reconciles is False


def test_an_account_statement_reads_direction_from_the_balance() -> None:
    found = read_statement_lines(ACCOUNT)
    assert found.kind is Kind.ACCOUNT
    assert [(r.day, r.description, r.amount) for r in found.rows] == [
        (date(2026, 9, 2), "NETS PURCHASE KOPI CORNER", Decimal("-12.30")),
        (date(2026, 9, 5), "FAST TRANSFER FROM ANN", Decimal("40.00")),
        (date(2026, 9, 25), "SALARY GIRO", Decimal("5000.00")),
    ]
    assert found.reconciles is True


def test_a_january_statement_puts_december_in_the_year_before() -> None:
    lines = [
        "Statement Date 13 JAN 2027",
        "20 DEC 19 DEC GIFT SHOP 50.00",
        "05 JAN 04 JAN CAFE 3.00",
    ]
    found = read_statement_lines(lines)
    assert [r.day for r in found.rows] == [date(2026, 12, 19), date(2027, 1, 4)]
    assert statement_date(["nothing here"]) is None


def test_the_csv_from_a_pdf_goes_through_the_usual_preview() -> None:
    read = read_pdf(CARD)
    assert read.rows == 5 and read.reconciles is True
    rows = read_rows(read_table(read.csv), PDF_LAYOUT)
    assert [(r.day, r.amount, r.direction.value if r.direction else None) for r in rows][:2] == [
        (date(2026, 8, 16), Decimal("120.00"), "in"),
        (date(2026, 8, 16), Decimal("4.20"), "out"),
    ]
    with pytest.raises(InvalidInput):
        read_pdf(["A letter with no transactions in it."])


def test_text_comes_out_of_a_real_pdf_and_a_locked_one() -> None:
    lines = pdf_lines(make_pdf(CARD))
    assert "17 AUG 16 AUG PAYMENT - THANK YOU 120.00 CR" in lines
    assert read_statement_lines(lines).reconciles is True
    locked = make_pdf(CARD, password="S1234567A")
    with pytest.raises(PasswordNeeded) as needed:
        pdf_lines(locked)
    assert not needed.value.wrong
    with pytest.raises(PasswordNeeded) as wrong:
        pdf_lines(locked, "nope")
    assert wrong.value.wrong
    assert len(read_statement_lines(pdf_lines(locked, "S1234567A")).rows) == 5
    with pytest.raises(InvalidInput):
        pdf_lines(b"not a pdf at all")
    with pytest.raises(InvalidInput):
        pdf_lines(b"%PDF-1.4 but broken")
