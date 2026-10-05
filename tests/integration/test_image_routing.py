"""Images the user sends: looked at first, then routed in code. Receipts are logged,
anything else (or a question) is answered by the chat agent from what was read, and
nothing read from an image acts on its own. Every shop, name and figure is made up."""

import pytest

from nexus.agent.image_look import ImageKind, ImageLook
from nexus.agent.receipts import ReceiptDraft
from nexus.agent.service import Picture
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import list_ledger
from nexus.domain.ledger import UserId
from tests.fakes import (
    FakeImageLooker,
    FakeReceipts,
    FakeTripReader,
    ScriptedModel,
    say,
    scripted,
)
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.pdfs import make_pdf

pytestmark = pytest.mark.integration

IMG = b"\xff\xd8jpeg"
RAMEN = ImageLook(ImageKind.RECEIPT, "JPY", "A ramen shop receipt.", "ICHIRAN / TOTAL ¥1,980")
TRANSFER = ImageLook(
    ImageKind.TRANSFER,
    "SGD",
    "A bank transfer confirmation.",
    "Transfer successful / SGD 1,250.00 / To: Jamie Example / Ref: Rent October",
)
PAYSLIP = ImageLook(
    ImageKind.PAYSLIP, "SGD", "A payslip.", "Example Pte Ltd / salary 4200 / CPF 840"
)
MENU = ImageLook(ImageKind.OTHER, "SGD", "A noodle menu.", "Wonton Mee 8.50 / Lemon Tea 3.20")


def last_human(model: ScriptedModel) -> str:
    return str(model.seen[-1][-1].content) if model.seen else ""


def told(model: ScriptedModel) -> str:
    """What the chat agent was given for the newest message."""
    for messages in reversed(model.seen):
        for m in reversed(messages):
            if m.type == "human":
                return str(m.content)
    return ""


async def expenses(uow: UowFactory, user: UserId) -> int:
    return (await list_ledger(uow(), user, LedgerQuery())).total


async def test_a_receipt_is_logged_with_the_currency_the_look_saw(
    uow: UowFactory, alice: UserId
) -> None:
    # The receipt reader read the total but not the currency; the first look saw yen.
    reader = FakeReceipts(ReceiptDraft(is_receipt=True, amount="1980", merchant="Ichiran"))
    agent = build(uow, scripted(), reader, looker=FakeImageLooker([RAMEN]))
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "telegram-photo:r1"))
    assert reply.text.startswith("Log 1980 JPY at Ichiran on ")
    assert "⚠️" not in reply.text


async def test_a_currency_disagreement_is_flagged(uow: UowFactory, alice: UserId) -> None:
    reader = FakeReceipts(
        ReceiptDraft(is_receipt=True, amount="1980", currency="SGD", merchant="Ichiran")
    )
    agent = build(uow, scripted(), reader, looker=FakeImageLooker([RAMEN]))
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "telegram-photo:r2"))
    assert reply.text.startswith("Log 1980.00 SGD at Ichiran")
    assert reply.text.endswith(
        "⚠️ The receipt may be in JPY, not SGD: if so, tap Cancel and tell me the amount "
        "and currency."
    )


async def test_a_question_about_a_receipt_goes_to_the_chat_agent(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(say("That's a fair price for ramen in Tokyo."))
    reader = FakeReceipts(ReceiptDraft(is_receipt=True, amount="1980", currency="JPY"))
    agent = build(uow, model, reader, looker=FakeImageLooker([RAMEN]))
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", "is this expensive?", "tg:1"))
    assert reply.text == "That's a fair price for ramen in Tokyo."
    assert reader.reads == 0  # not read as an expense
    given = told(model)
    assert given.startswith("[photo] is this expensive?\n<image>\nkind: receipt\ncurrency: JPY")
    assert "text:\nICHIRAN / TOTAL ¥1,980\n</image>" in given
    assert await expenses(uow, alice) == 0


async def test_other_images_are_described_not_logged(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("That's your October rent transfer to Jamie. Want me to log it?"))
    reader = FakeReceipts(ReceiptDraft(is_receipt=True, amount="1250"))
    agent = build(uow, model, reader, looker=FakeImageLooker([TRANSFER]))
    reply = only(await agent.handle_photo(alice, IMG, "image/png", None, "tg:2"))
    assert reply.text.startswith("That's your October rent transfer")
    assert reader.reads == 0 and await expenses(uow, alice) == 0
    assert "<image>\nkind: transfer" in told(model)


async def test_a_payslips_text_never_records_income_by_itself(
    uow: UowFactory, alice: UserId
) -> None:
    # "salary 4200" typed would be recorded straight away; read from an image it's data.
    model = scripted(say("It's your payslip: 4,200 before CPF. Want me to record it?"))
    agent = build(uow, model, FakeReceipts(ReceiptDraft(is_receipt=False)),
                  looker=FakeImageLooker([PAYSLIP]))  # fmt: skip
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "tg:3"))
    assert reply.text.startswith("It's your payslip")
    assert await expenses(uow, alice) == 0
    assert model.seen  # the chat agent answered, not a shortcut


async def test_not_a_receipt_after_all(uow: UowFactory, alice: UserId) -> None:
    # The look thought "receipt" but the receipt reader found no total: the chat agent
    # answers from what was read instead of saying it couldn't read a total.
    model = scripted(say("It's a menu: wonton mee is 8.50."))
    reader = FakeReceipts(ReceiptDraft(is_receipt=False))
    look = ImageLook(ImageKind.RECEIPT, "SGD", "A noodle menu.", "Wonton Mee 8.50")
    agent = build(uow, model, reader, looker=FakeImageLooker([look]))
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "tg:4"))
    assert reply.text == "It's a menu: wonton mee is 8.50." and reader.reads == 1


async def test_when_the_look_fails_photos_are_read_as_receipts(
    uow: UowFactory, alice: UserId
) -> None:
    reader = FakeReceipts(ReceiptDraft(is_receipt=True, amount="6.40", merchant="Toast Box"))
    agent = build(uow, scripted(), reader, looker=FakeImageLooker([None]))
    reply = only(await agent.handle_photo(alice, IMG, "image/jpeg", None, "telegram-photo:r3"))
    assert reply.text.startswith("Log 6.40 SGD at Toast Box")
    asked = build(uow, scripted(), reader, looker=FakeImageLooker([None]))
    failed = only(await asked.handle_photo(alice, IMG, "image/jpeg", "what's this?", "tg:5"))
    assert failed.text == "I couldn't read that right now. Try again in a bit."


async def test_photos_sent_together_are_answered_together(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("The transfer is 1,250; the menu's cheapest dish is lemon tea."))
    agent = build(uow, model, FakeReceipts(ReceiptDraft(is_receipt=False)),
                  looker=FakeImageLooker([TRANSFER, MENU]))  # fmt: skip
    pictures = [Picture(IMG, "image/jpeg", "p1"), Picture(IMG, "image/jpeg", "p2")]
    reply = only(await agent.handle_images(alice, pictures, "compare these", "tg:6"))
    assert reply.text.startswith("The transfer is 1,250")
    given = told(model)
    assert given.startswith("[2 photos] compare these\n<image 1>\nkind: transfer")
    assert "<image 2>\nkind: other" in given and given.count("</image") == 2


async def test_follow_ups_can_use_what_was_read(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("It's a menu."), say("Lemon tea, at 3.20."))
    agent = build(uow, model, FakeReceipts(ReceiptDraft(is_receipt=False)),
                  looker=FakeImageLooker([MENU]))  # fmt: skip
    await agent.handle_photo(alice, IMG, "image/jpeg", None, "tg:7")
    reply = only(await agent.handle_text(alice, "what's the cheapest thing?", "tg:8"))
    assert reply.text == "Lemon tea, at 3.20."
    history = " ".join(str(m.content) for m in model.seen[-1])
    assert "Lemon Tea 3.20" in history  # the transcription is still in the conversation


async def test_a_pdfs_text_goes_to_the_chat_agent(uow: UowFactory, alice: UserId) -> None:
    model = scripted(say("It's an invoice for 88.00, due 15 Oct."))
    agent = build(uow, model, FakeReceipts(ReceiptDraft(is_receipt=False)))
    pdf = make_pdf(["Example Town Council", "Amount due: 88.00", "Due date: 15 Oct 2026"])
    reply = only(await agent.handle_pdf(alice, pdf, "bill.pdf", None, "tg:9"))
    assert reply.text.startswith("It's an invoice")
    given = told(model)
    assert given.startswith("[PDF]\n<image>\nkind: other\nsummary: A PDF file named bill.pdf")
    assert "Amount due: 88.00" in given
    locked = only(await agent.handle_pdf(alice, make_pdf(["x"], "pw"), "s.pdf", None, "tg:10"))
    assert locked.text.startswith("That PDF is locked.")
    junk = only(await agent.handle_pdf(alice, b"not a pdf", "x.pdf", None, "tg:11"))
    assert junk.text == "That isn't a pdf. Send a screenshot of it instead."


async def test_a_ticket_with_a_price_goes_on_the_trip(uow: UowFactory, alice: UserId) -> None:
    # The look saw a receipt (an e-ticket shows its fare); the receipt reader knows it's
    # travel, so its entries go on the itinerary rather than into the chat.
    ticket = ImageLook(ImageKind.RECEIPT, "SGD", "An e-ticket receipt.", "ZZ12 SIN-NRT SGD 820")
    reader = FakeReceipts(ReceiptDraft(is_receipt=True, is_travel=True, amount="820"))
    trips = FakeTripReader()
    agent = build(uow, scripted(), reader, trips=trips, looker=FakeImageLooker([ticket]))
    replies = await agent.handle_photo(alice, IMG, "image/png", None, "telegram-photo:t1")
    assert trips.reads == 1
    assert "ZZ12" in replies[0].text and await expenses(uow, alice) == 0
