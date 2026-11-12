"""When a "Needs you" item carries buttons, and what they call. Every name and figure here
is made up."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from nexus.application import duplicates as duplicate_cases
from nexus.application.bills import BillView
from nexus.application.home import (
    FeedAction,
    FeedItem,
    _bill_actions,
    _duplicates_item,
    _email_item,
)
from nexus.domain.email import EmailStatus, InboundEmail
from nexus.domain.ledger import (
    Direction,
    Role,
    Source,
    Transaction,
    TransactionStatus,
    User,
    UserId,
)
from nexus.domain.money import Money
from nexus.domain.planning import Bill, Cadence

ME = UserId(uuid4())
USER = User(ME, 1, 1, "Asia/Singapore", "SGD", Role.MEMBER, datetime(2026, 1, 1, tzinfo=UTC))
NOW = datetime(2026, 10, 21, 1, tzinfo=UTC)


def shape(item: FeedItem) -> list[tuple[str, str, str, str, dict[str, object] | None]]:
    return [(a.key, a.label, a.method, a.path, a.body) for a in item.actions]


# --- bills --------------------------------------------------------------------------------


def bill_view(amount: str | None, *, spending: bool = True, wallet: UUID | None = None) -> BillView:
    bill = Bill(
        uuid4(),
        ME,
        "Rent",
        Money.of(amount, "SGD") if amount else None,
        Cadence.MONTHLY,
        date(2026, 10, 23),
        NOW,
        spending=spending,
        wallet_id=wallet,
    )
    return BillView(bill, date(2026, 10, 23), None, date(2026, 10, 21))


def test_a_bill_with_an_amount_can_be_marked_paid_for_its_due_date_or_snoozed() -> None:
    view = bill_view("1800")
    assert _bill_actions(view) == (
        FeedAction("paid", "Mark paid", "POST", f"/bills/{view.bill.id}/paid?due=2026-10-23"),
        FeedAction("snooze", "Remind me later", "POST", f"/bills/{view.bill.id}/snooze"),
    )


def test_a_bill_that_would_ask_how_much_it_was_can_only_be_snoozed() -> None:
    plain = bill_view(None)
    move = bill_view(None, spending=False, wallet=uuid4())
    for view in (plain, move):
        assert [a.key for a in _bill_actions(view)] == ["snooze"]


def test_a_bill_that_only_gets_marked_done_needs_no_amount() -> None:
    view = bill_view(None, spending=False)  # money set aside that moves nowhere
    assert [(a.key, a.label) for a in _bill_actions(view)] == [
        ("paid", "Mark done"),
        ("snooze", "Remind me later"),
    ]


# --- receipts from email ------------------------------------------------------------------


def email(**draft: Any) -> InboundEmail:
    found: dict[str, Any] = {"amount": "18.90", "currency": "SGD", "merchant": "Grab"}
    return InboundEmail(
        uuid4(),
        ME,
        uuid4(),
        "m1",
        NOW,
        "no-reply@grab.com",
        "Your receipt",
        EmailStatus.PENDING,
        None,
        {**found, **draft},
        None,
        NOW,
    )


def test_one_clear_receipt_is_described_and_can_be_logged_or_skipped() -> None:
    mail = email()
    item = _email_item([mail], USER)
    assert item.text == "Grab receipt, 18.90 SGD, from your email"
    assert item.link == "/settings/email" and not item.urgent
    assert shape(item) == [
        ("log", "Log it", "POST", f"/email/{mail.id}/log", {}),
        ("skip", "Skip", "POST", f"/email/{mail.id}/skip", None),
    ]


def test_a_receipt_with_no_merchant_still_reads_plainly() -> None:
    assert _email_item([email(merchant=None)], USER).text == "Receipt, 18.90 SGD, from your email"


def test_several_receipts_stay_one_link() -> None:
    item = _email_item([email(), email()], USER)
    assert item.text == "2 receipts from email waiting for you"
    assert item.actions == ()


def test_a_receipt_that_needs_a_look_is_not_logged_from_home() -> None:
    twin = {"label": "Grab 18.90 SGD on 20 Oct", "id": str(uuid4())}
    unclear = [
        email(amount=None),  # nothing was read
        email(amount="refund -5.00"),  # not a clear amount
        email(duplicate_of=twin),  # looks like a payment already logged
        email(wallet={"id": str(uuid4()), "name": "IBKR"}),  # may be a move
        email(direction="in"),  # money received, not spent
    ]
    for mail in unclear:
        item = _email_item([mail], USER)
        assert item.text == "1 receipt from email waiting for you", mail.draft
        assert item.actions == ()


# --- possible duplicates -------------------------------------------------------------------


def entry(
    name: str | None, amount: str, day: int, source: Source, *, currency: str = "SGD"
) -> Transaction:
    at = datetime(2026, 10, day, 4, tzinfo=UTC)
    return Transaction(
        id=uuid4(),
        user_id=ME,
        direction=Direction.OUT,
        amount=Money.of(amount, currency),
        occurred_at=at,
        counterparty=name,
        category_id=None,
        notes=None,
        status=TransactionStatus.CONFIRMED,
        source=source,
        created_at=at,
        updated_at=at,
    )


def test_one_pair_of_the_same_amount_is_described_and_can_be_merged_or_kept() -> None:
    newer = entry("Grab Singapore", "23.40", 20, Source.MANUAL)
    older = entry("Grab* A-7KXP", "23.40", 19, Source.EMAIL)
    item = _duplicates_item([duplicate_cases.Pair(newer, older)], USER)
    assert item.text == (
        "Grab Singapore, 23.40 SGD, may be logged twice: 20 Oct added by hand and 19 Oct from email"
    )
    other: dict[str, object] = {"other_id": str(older.id)}
    assert shape(item) == [
        ("merge", "Same one", "POST", f"/transactions/{newer.id}/merge", other),
        ("keep_both", "Keep both", "POST", f"/transactions/{newer.id}/not-duplicate", other),
    ]


def test_a_pair_with_no_names_still_reads_plainly() -> None:
    pair = duplicate_cases.Pair(
        entry(None, "5", 20, Source.TEXT), entry(None, "5", 20, Source.PHOTO)
    )
    assert _duplicates_item([pair], USER).text == (
        "A payment, 5.00 SGD, may be logged twice: 20 Oct typed in chat and 20 Oct from a photo"
    )


def test_several_pairs_stay_one_link() -> None:
    pairs = [
        duplicate_cases.Pair(entry("A", "5", 20, Source.MANUAL), entry("A", "5", 19, Source.EMAIL)),
        duplicate_cases.Pair(entry("B", "9", 18, Source.MANUAL), entry("B", "9", 17, Source.EMAIL)),
    ]
    item = _duplicates_item(pairs, USER)
    assert item.text == "2 possible duplicates to check"
    assert item.actions == () and item.link == "/accounting/ledger"


def test_a_pair_in_two_currencies_cannot_be_merged_from_home() -> None:
    pair = duplicate_cases.Pair(
        entry("Hotel", "100", 20, Source.MANUAL),
        entry("Hotel", "130", 20, Source.EMAIL, currency="USD"),
    )
    item = _duplicates_item([pair], USER)
    assert item.text == "1 possible duplicate to check" and item.actions == ()
