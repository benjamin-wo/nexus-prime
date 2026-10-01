"""Money that comes in: a bank alert of a transfer is offered as the sender's
repayment when they owe the user, IOUs settle under the bank's spelling of a name,
an IOU can be marked paid back by hand, and the chat can answer waiting emails.
Every name and figure here is made up."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import AnswerEmailArgs, ToolContext, build_tools
from nexus.application import email as email_cases
from nexus.application import splits as split_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import NewTransaction, list_ledger, log_transaction
from nexus.domain.email import InboundEmail
from nexus.domain.errors import Conflict, InvalidInput
from nexus.domain.ledger import Direction, ShareRequest, Source, User, same_person
from nexus.domain.money import Money
from tests.fakes import NOW, FakeMailbox, fake_email
from tests.integration.conftest import UowFactory
from tests.integration.test_email import connect, messages, person, sweep

pytestmark = pytest.mark.integration

TRANSFER = "From: TAN WEI MING\nTotal: 20.00\nCurrency: SGD"


def sgd(amount: str) -> Money:
    return Money(Decimal(amount), "SGD")


async def owes(uow: UowFactory, user: User, name: str = "Wei Ming", share: str = "20") -> None:
    """A dinner of 40 the user paid, with ``name`` owing ``share`` of it."""
    dinner = await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            direction=Direction.OUT,
            amount=sgd("40"),
            occurred_at=NOW - timedelta(days=2),
            counterparty="Hotpot place",
        ),
    )
    await split_cases.split_bill(uow(), user.id, dinner.id, [ShareRequest(name, sgd(share))])


async def owed(uow: UowFactory, user: User) -> list[tuple[str, Money]]:
    ious = await split_cases.list_open_ious(uow(), user.id)
    return [(i.split.participant_name, i.outstanding) for i in ious]


async def a_transfer_arrives(uow: UowFactory, user: User) -> InboundEmail:
    mailbox = FakeMailbox(
        {
            "t1": fake_email(
                "t1", "You've received a transfer", TRANSFER, at=NOW - timedelta(hours=1)
            )
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    [email] = await email_cases.waiting(uow(), user.id, now=NOW)
    return email


def test_names_match_however_the_bank_writes_them() -> None:
    assert same_person("Wei Ming", "TAN WEI MING")
    assert same_person("tan wei ming", "Wei Ming")
    assert same_person("Ann", "ann")
    assert not same_person("Wei Ming", "TAN WEI LING")
    assert not same_person("Ann", "")


async def test_a_transfer_from_someone_who_owes_is_offered_as_their_repayment(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await owes(uow, user)
    email = await a_transfer_arrives(uow, user)
    assert email.status.value == "pending" and (email.draft or {})["direction"] == "in"

    [question] = await messages(engine)
    assert question["text"] == (
        "📧 From your email: 20.00 SGD came in from TAN WEI MING on 28 Sep. Wei Ming owes "
        "you 20.00 SGD. Count it as paying that back?"
    )
    labels = [b["label"] for row in question["buttons"] for b in row]
    assert labels == ["Yes, paid back", "Just income", "Skip"]

    tx = await email_cases.log_email(uow, user, email.id, now=NOW, repayment=True)
    assert (tx.direction, tx.amount, tx.counterparty, tx.source) == (
        Direction.IN, sgd("20"), "Wei Ming", Source.EMAIL,
    )  # fmt: skip
    assert await owed(uow, user) == []
    with pytest.raises(Conflict):  # answered already
        await email_cases.log_email(uow, user, email.id, now=NOW)


async def test_just_income_leaves_the_iou_open(uow: UowFactory) -> None:
    user = await person(uow)
    await owes(uow, user)
    email = await a_transfer_arrives(uow, user)
    tx = await email_cases.log_email(uow, user, email.id, now=NOW, repayment=False)
    assert (tx.direction, tx.counterparty) == (Direction.IN, "TAN WEI MING")
    assert await owed(uow, user) == [("Wei Ming", sgd("20"))]


async def test_money_from_someone_who_owes_nothing_is_offered_as_income(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    email = await a_transfer_arrives(uow, user)
    [question] = await messages(engine)
    assert question["text"] == (
        "📧 From your email: 20.00 SGD came in from TAN WEI MING on 28 Sep. Log it as money in?"
    )
    assert [b["label"] for b in question["buttons"][0]] == ["Log it", "Skip"]
    with pytest.raises(InvalidInput):
        await email_cases.log_email(uow, user, email.id, now=NOW, repayment=True)
    tx = await email_cases.log_email(uow, user, email.id, now=NOW)
    assert (tx.direction, tx.amount) == (Direction.IN, sgd("20"))
    page = await list_ledger(uow(), user.id, LedgerQuery())
    assert [t.direction for t in page.items] == [Direction.IN]


async def test_a_repayment_settles_under_the_banks_spelling(uow: UowFactory) -> None:
    user = await person(uow)
    await owes(uow, user, share="25")
    settled = await split_cases.settle_iou(uow(), user.id, "tan wei ming", sgd("10"), NOW)
    assert settled.transaction.counterparty == "Wei Ming"
    assert await owed(uow, user) == [("Wei Ming", sgd("15"))]
    mine = await split_cases.list_open_ious(uow(), user.id, participant_name="TAN WEI MING")
    assert [i.outstanding for i in mine] == [sgd("15")]


async def test_an_iou_can_be_marked_paid_back(uow: UowFactory) -> None:
    user = await person(uow)
    await owes(uow, user, share="25")
    [iou] = await split_cases.list_open_ious(uow(), user.id)
    done = await split_cases.mark_repaid(uow, user.id, iou.split.id, now=NOW)
    assert (done.transaction.amount, done.transaction.direction) == (sgd("25"), Direction.IN)
    assert await owed(uow, user) == []


async def test_the_chat_sees_and_answers_a_waiting_email(uow: UowFactory) -> None:
    user = await person(uow)
    await owes(uow, user)
    email = await a_transfer_arrives(uow, user)
    ctx = ToolContext(user=user, uow=uow, now=NOW)
    line = email_cases.describe(email, ctx.tz)
    assert "20.00 SGD came in from TAN WEI MING" in line

    tool = build_tools(lambda _: "")["answer_email"]
    assert tool.confirm is not None
    asked = await tool.confirm(ctx, AnswerEmailArgs(number=1, action="repayment"))
    assert asked.startswith("Log it as paying back what they owe?")
    result = await tool.run(ctx, AnswerEmailArgs(number=1, action="repayment"))
    assert result.wrote and "Logged 20.00 SGD received from Wei Ming" in result.text
    assert await owed(uow, user) == []
    assert await email_cases.waiting(uow(), user.id, now=NOW) == []
    with pytest.raises(InvalidInput):
        await tool.run(ctx, AnswerEmailArgs(number=1, action="skip"))
