"""Importing a statement: nothing is saved by a preview; duplicates, repeats and
unreadable rows are flagged; only ticked rows are added, once; an import can be
undone as a whole; a saved layout is found again. Every statement is made up."""

from datetime import datetime, time
from decimal import Decimal

import pytest

from nexus.application import category_rules as rule_cases
from nexus.application import salary as salary_cases
from nexus.application import statements as statement_cases
from nexus.application.categories import list_categories
from nexus.application.ports import LedgerQuery
from nexus.application.statements import Verdict
from nexus.application.transactions import NewTransaction, list_ledger, log_transaction
from nexus.application.users import get_user
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, Source, User, UserId
from nexus.domain.money import Money
from nexus.domain.statements import Mapping
from tests.fakes import NOW
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration

STATEMENT = """Account Details For:,Everyday Savings 000-00000-0

Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1,Transaction Ref2
28 Sep 2026,POS,4.20,,KOPITIAM,SINGAPORE
27 Sep 2026,POS,42.10,,GRAB,RIDE
25 Sep 2026,ICT,,"5,000.00",ACME PTE LTD,SALARY
24 Sep 2026,POS,1.80,,KOPI,SINGAPORE
24 Sep 2026,POS,1.80,,KOPI,SINGAPORE
soon,POS,9.99,,MYSTERY,
"""


async def user_of(uow: UowFactory, actor: UserId) -> User:
    return await get_user(uow(), actor)


async def ledger(uow: UowFactory, actor: UserId) -> list[tuple[str, str, Decimal, str]]:
    page = await list_ledger(uow(), actor, LedgerQuery(limit=100))
    return sorted(
        (t.direction.value, t.counterparty or "", t.amount.amount, t.source.value)
        for t in page.items
    )


async def test_a_preview_flags_rows_and_saves_nothing(uow: UowFactory, alice: UserId) -> None:
    user = await user_of(uow, alice)
    await log_transaction(  # already logged by hand, a day off
        uow(),
        alice,
        NewTransaction(
            Direction.OUT, Money.of("42.10", "SGD"),
            datetime.combine(datetime(2026, 9, 26).date(), time(12), tzinfo=NOW.tzinfo),
            counterparty="Grab",
        ),
    )  # fmt: skip
    cats = {c.name: c.id for c in await list_categories(uow(), alice)}
    await rule_cases.set_rule(uow(), user, "kopi", cats["Dining Out"], now=NOW)
    shown = await statement_cases.preview(uow, user, STATEMENT)
    assert shown.mapping is not None and shown.saved_as is None
    verdicts = [(p.row.description, p.verdict, p.category) for p in shown.rows]
    assert verdicts == [
        ("KOPITIAM · SINGAPORE", Verdict.NEW, "Other"),  # rules match whole words
        ("GRAB · RIDE", Verdict.DUPLICATE, "Other"),
        ("ACME PTE LTD · SALARY", Verdict.NEW, "Income"),
        ("KOPI · SINGAPORE", Verdict.NEW, "Dining Out"),
        ("KOPI · SINGAPORE", Verdict.NEW, "Dining Out"),  # a second kopi is its own row
        ("MYSTERY", Verdict.UNCLEAR, None),
    ]
    assert shown.rows[-1].row.problem == "can't read the date"
    assert len(await ledger(uow, alice)) == 1  # only the hand-logged one


async def test_confirm_adds_ticked_rows_once_and_undo_removes_them(
    uow: UowFactory, alice: UserId
) -> None:
    user = await user_of(uow, alice)
    shown = await statement_cases.preview(uow, user, STATEMENT)
    assert shown.mapping is not None
    ticked = {p.row.index for p in shown.rows if p.verdict is Verdict.NEW}
    done = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, ticked | {5}, file_name="sept.csv",
        save_as="Everyday Savings", now=NOW,
    )  # fmt: skip
    assert len(done.record.transaction_ids) == 5 and done.skipped == 1  # the unreadable row
    rows = await ledger(uow, alice)
    assert ("in", "ACME PTE LTD · SALARY", Decimal("5000.0000"), "import") in rows
    assert sum(1 for r in rows if r[1] == "KOPI · SINGAPORE") == 2
    # Money in is income, never salary: no pay schedule or usual salary appears.
    assert await salary_cases.view(uow(), user, now=NOW) is None

    again = await statement_cases.preview(uow, user, STATEMENT)
    assert {p.verdict for p in again.rows if p.row.index in ticked} == {Verdict.IMPORTED}
    assert again.saved_as == "Everyday Savings"  # the layout is found by its headers
    repeat = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, ticked, file_name="sept.csv", now=NOW
    )
    assert repeat.record.transaction_ids == [] and repeat.skipped == len(ticked)

    [record] = await statement_cases.list_imports(uow(), alice)
    assert await statement_cases.undo_import(uow(), alice, record.id, now=NOW) == 5
    assert await ledger(uow, alice) == []
    with pytest.raises(InvalidInput):
        await statement_cases.undo_import(uow(), alice, record.id, now=NOW)
    # Undone rows stay claimed, so the file still can't add them twice.
    later = await statement_cases.preview(uow, user, STATEMENT)
    assert {p.verdict for p in later.rows if p.row.index in ticked} == {Verdict.IMPORTED}


async def test_imports_and_layouts_belong_to_their_user(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    user = await user_of(uow, alice)
    shown = await statement_cases.preview(uow, user, STATEMENT)
    assert shown.mapping is not None
    done = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {0}, file_name="a.csv", save_as="Bank", now=NOW
    )
    [layout] = await statement_cases.list_layouts(uow(), alice)
    assert await statement_cases.list_layouts(uow(), bob) == []
    assert await statement_cases.list_imports(uow(), bob) == []
    with pytest.raises(NotFound):
        await statement_cases.undo_import(uow(), bob, done.record.id, now=NOW)
    with pytest.raises(NotFound):
        await statement_cases.forget_layout(uow(), bob, layout.id)
    bob_view = await statement_cases.preview(uow, await user_of(uow, bob), STATEMENT)
    assert bob_view.saved_as is None
    assert all(p.verdict is not Verdict.IMPORTED for p in bob_view.rows)
    await statement_cases.forget_layout(uow(), alice, layout.id)
    assert await statement_cases.list_layouts(uow(), alice) == []


async def test_a_statement_that_cant_be_mapped(uow: UowFactory, alice: UserId) -> None:
    user = await user_of(uow, alice)
    shown = await statement_cases.preview(uow, user, "when,what,how much\n1/9/2026,x,5\n")
    assert shown.mapping is None and shown.rows == []  # the user picks the columns
    chosen = Mapping(date=0, description=(1,), amount=2)
    picked = await statement_cases.preview(uow, user, "when,what,how much\n1/9/2026,x,-5\n", chosen)
    assert [p.verdict for p in picked.rows] == [Verdict.NEW]
    with pytest.raises(InvalidInput):
        await statement_cases.confirm(
            uow, user, "when,what,how much\n1/9/2026,x,-5\n", chosen, set(), file_name="f", now=NOW
        )
    with pytest.raises(InvalidInput):
        await statement_cases.confirm(
            uow, user, "when,what,how much\n1/9/2026,x,-5\n", chosen, {7}, file_name="f", now=NOW
        )


def test_the_import_source_is_known() -> None:
    assert Source.IMPORT.value == "import"
