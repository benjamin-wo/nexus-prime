"""Holdings from a broker screenshot (checked by the user before saving) and from
trades the user tells Nexus about. Every ticker and figure here is made up."""

from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from nexus.agent.holdings_reader import ScreenshotHoldings, ScreenshotPosition
from nexus.agent.receipts import ReceiptDraft
from nexus.application import investments as investment_cases
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.investments import Position
from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from tests.fakes import NOW, FakeHoldings, FakeReceipts, call, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_email import person

pytestmark = pytest.mark.integration


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


def pos(symbol: str, quantity: str, cost: str) -> Position:
    return Position(symbol, Decimal(quantity), usd(cost))


async def trade(
    uow: UowFactory, user_id: UserId, side: str, symbol: str, quantity: str, price: str | None
) -> Position | None:
    return await investment_cases.record_trade(
        uow(),
        user_id,
        investment_cases.Side(side),
        symbol,
        Decimal(quantity),
        usd(price) if price else None,
        now=NOW,
    )


async def held(uow: UowFactory, user_id: UserId) -> list[tuple[str, Decimal, Money]]:
    found = await investment_cases.portfolio(uow(), user_id)
    return [(h.position.symbol, h.position.quantity, h.position.average_cost) for h in found]


async def test_a_screenshot_is_checked_then_saved(uow: UowFactory) -> None:
    user = await person(uow)
    reader = FakeHoldings()
    agent = build(uow, scripted(), holdings=reader)
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", "my portfolio", "p1"))
    assert reply.text == (
        "📈 I read 2 positions from your screenshot:\n"
        "• AAPL: 5 at 190.00 USD avg\n"
        "• NVDA: 10 at 118.40 USD avg\n"
        "Save these as your holdings?"
    )
    assert await held(uow, user.id) == []  # nothing until the user says so
    save, cancel = reply.buttons[0]
    assert (save.label, cancel.label) == ("Save", "Cancel")
    done = only(await agent.press(user.id, save.data))
    assert done.text == "Saved 2 positions. They're on the Investment page in the web app."
    assert await held(uow, user.id) == [
        ("AAPL", Decimal("5"), usd("190")),
        ("NVDA", Decimal("10"), usd("118.40")),
    ]
    again = only(await agent.press(user.id, save.data))
    assert again.text == "That screenshot was already saved."


async def test_a_later_screenshot_shows_what_changed(uow: UowFactory) -> None:
    user = await person(uow)
    await investment_cases.set_position(
        uow(), user.id, Position("NVDA", Decimal("4"), usd("100")), now=NOW
    )
    await investment_cases.set_position(
        uow(), user.id, Position("TSLA", Decimal("2"), usd("250")), now=NOW
    )
    agent = build(uow, scripted(), holdings=FakeHoldings())
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", "holdings", "p1"))
    assert reply.text.splitlines() == [
        "📈 Compared with what I have, your screenshot shows:",
        "• + AAPL: 5 at 190.00 USD avg (new)",
        "• + NVDA: 4 → 10 shares",
        "• - TSLA: gone (was 2)",
        "Update your holdings to match?",
    ]
    cancelled = only(await agent.press(user.id, reply.buttons[0][1].data))
    assert cancelled.text == "OK, I've left your holdings as they were."
    assert [s for s, _, _ in await held(uow, user.id)] == ["NVDA", "TSLA"]


async def test_a_photo_that_isnt_a_receipt_is_tried_as_a_portfolio(uow: UowFactory) -> None:
    user = await person(uow)
    reader = FakeHoldings()
    agent = build(uow, scripted(), FakeReceipts(ReceiptDraft(is_receipt=False)), holdings=reader)
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", None, "p1"))
    assert reply.text.startswith("📈 I read 2 positions")

    # A real receipt never reaches the portfolio reader.
    receipt = FakeReceipts(ReceiptDraft(is_receipt=True, amount="4.20", merchant="Kopi"))
    agent = build(uow, scripted(), receipt, holdings=reader)
    reply = only(await agent.handle_photo(user.id, b"jpg", "image/jpeg", None, "p2"))
    assert reply.text.startswith("Log 4.20 SGD at Kopi")
    assert reader.reads == 1

    # Neither: the usual "couldn't read a total".
    nothing = FakeHoldings(ScreenshotHoldings(is_portfolio=False))
    agent = build(uow, scripted(), FakeReceipts(ReceiptDraft(is_receipt=False)), holdings=nothing)
    reply = only(await agent.handle_photo(user.id, b"jpg", "image/jpeg", None, "p3"))
    assert reply.text.startswith("I couldn't read a total")


async def test_a_screenshot_with_nothing_readable(uow: UowFactory) -> None:
    user = await person(uow)
    blank = FakeHoldings(
        ScreenshotHoldings(is_portfolio=True, positions=[ScreenshotPosition(symbol="Cash")])
    )
    agent = build(uow, scripted(), holdings=blank)
    reply = only(await agent.handle_photo(user.id, b"png", "image/png", "portfolio", "p1"))
    assert reply.text.startswith("I couldn't find any positions in that screenshot.")
    assert reply.buttons == []


async def test_the_newest_screenshot_wins(uow: UowFactory) -> None:
    user = await person(uow)
    first = await investment_cases.propose(
        uow(), user.id, [Position("NVDA", Decimal("1"), usd("1"))], now=NOW
    )
    second = await investment_cases.propose(
        uow(), user.id, [Position("AMD", Decimal("2"), usd("3"))], now=NOW
    )
    with pytest.raises(Conflict, match="discarded"):
        await investment_cases.save_draft(uow(), user.id, first.draft.id, now=NOW)
    waiting = await investment_cases.waiting_draft(uow(), user.id)
    assert waiting is not None and waiting.id == second.draft.id
    with pytest.raises(InvalidInput):
        await investment_cases.propose(uow(), user.id, [], now=NOW)


async def test_trades_the_user_tells_nexus_about(uow: UowFactory) -> None:
    user = await person(uow)
    model = scripted(
        call("record_trade", side="buy", symbol="nvda", quantity="10", price="100"),
        AIMessage(content="Recorded."),
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(user.id, "I bought 10 NVDA at 100", "m1"))
    assert ask.text == "Record that you bought 10 NVDA at 100.00 USD?"
    done = only(await agent.resolve(user.id, ask.buttons[0][0].data.split(":")[1], True))
    assert "Recorded." in done.text
    side = investment_cases.Side
    await investment_cases.record_trade(
        uow(), user.id, side.BUY, "NVDA", Decimal("10"), usd("110"), now=NOW
    )
    assert await held(uow, user.id) == [("NVDA", Decimal("20"), usd("105"))]
    await investment_cases.record_trade(
        uow(), user.id, side.SELL, "NVDA", Decimal("20"), None, now=NOW
    )
    assert await held(uow, user.id) == []
    with pytest.raises(InvalidInput, match="what price"):
        await investment_cases.record_trade(
            uow(), user.id, side.BUY, "AMD", Decimal("1"), None, now=NOW
        )
    with pytest.raises(NotFound):
        await investment_cases.remove(uow(), user.id, "AMD")
