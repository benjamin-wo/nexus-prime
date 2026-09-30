from decimal import Decimal

import pytest

from nexus.agent.kernel import (
    IncomeKind,
    is_self_diagnosis,
    is_termination,
    parse_income,
    unsupported_intent,
)


@pytest.mark.parametrize(
    ("text", "kind", "amount", "currency", "who"),
    [
        ("Ann paid me back 20", IncomeKind.REPAYMENT, "20", "SGD", "Ann"),
        ("ann paid me 12.50 for lunch", IncomeKind.REPAYMENT, "12.5", "SGD", "ann"),
        ("Mary Tan repaid 30 USD", IncomeKind.REPAYMENT, "30", "USD", "Mary Tan"),
        ("Ben sent me $15", IncomeKind.REPAYMENT, "15", "SGD", "Ben"),
        ("salary 4,200", IncomeKind.SALARY, "4200", "SGD", None),
        ("got paid 3.5k", IncomeKind.SALARY, "3500", "SGD", None),
        ("payday: S$5000", IncomeKind.SALARY, "5000", "SGD", None),
        ("received 50 from Ann", IncomeKind.INCOME, "50", "SGD", "Ann"),
        ("I got 100 EUR from Grandma", IncomeKind.INCOME, "100", "EUR", "Grandma"),
        ("got refunded 23.90", IncomeKind.INCOME, "23.9", "SGD", None),
        ("refund 40 from Shopee", IncomeKind.INCOME, "40", "SGD", "Shopee"),
        ("9397 as salary today", IncomeKind.SALARY, "9397", "SGD", None),
        ("9397 salary", IncomeKind.SALARY, "9397", "SGD", None),
        ("3k for my paycheck", IncomeKind.SALARY, "3000", "SGD", None),
        ("I got 5000 as salary", IncomeKind.SALARY, "5000", "SGD", None),
        ("my salary is 9,397", IncomeKind.SALARY, "9397", "SGD", None),
        ("got my salary 9397", IncomeKind.SALARY, "9397", "SGD", None),
        ("salary today 9397", IncomeKind.SALARY, "9397", "SGD", None),
        ("salary 9397 yesterday", IncomeKind.SALARY, "9397", "SGD", None),
        ("received 50 from Ann yesterday", IncomeKind.INCOME, "50", "SGD", "Ann"),
    ],
)
def test_recognises_income(
    text: str, kind: IncomeKind, amount: str, currency: str, who: str | None
) -> None:
    intent = parse_income(text, "SGD")
    assert intent is not None
    assert intent.kind is kind
    assert intent.amount.amount == Decimal(amount)
    assert intent.amount.currency == currency
    assert intent.counterparty == who


@pytest.mark.parametrize(
    "text",
    [
        "coffee 5.50",
        "I paid 5 for coffee",
        "paid 20 for dinner with Ann",
        "got coffee 5",
        "we paid me 20",
        "received",
        "salary",
        "how much salary did I get last month?",
        "Ann paid 20",
        "received 50 US$ EUR",
        "9397 as salary next month",
        "is 9397 a good salary?",
        "how much salary today",
    ],
)
def test_leaves_everything_else_to_the_model(text: str) -> None:
    assert parse_income(text, "SGD") is None


def test_symbol_and_code_must_agree() -> None:
    assert parse_income("received S$50 USD from Ann", "SGD") is None


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("transfer 50 to Ann", "transfer"),
        ("please send $20 to my mum", "transfer"),
        ("can you pay my phone bill", "payment"),
        ("please pay ann 20", "payment"),
        ("pay my credit card bill now", "payment"),
        ("pay DBS 500 from my account", "payment"),
        ("can you make a payment to DBS", "payment"),
        ("make a payment to DBS", "payment"),
        ("cancel my Netflix subscription", "cancel_subscription"),
    ],
)
def test_refuses_money_movement(text: str, intent: str) -> None:
    assert unsupported_intent(text) == intent


@pytest.mark.parametrize(
    "text",
    [
        "paid 5 for coffee",
        "payday 3000",
        "pay check 3000",
        "send me my summary",
        "coffee 4",
        # Bills to note, for the model; it has no tool that pays.
        "pay the town council 88 on 15 october",
        "pay rent 1800 on the 1st",
        "pay my phone bill",
    ],
)
def test_does_not_refuse_ordinary_requests(text: str) -> None:
    assert unsupported_intent(text) is None


@pytest.mark.parametrize("text", ["stop", "Cancel", "never mind!", "that's enough", "forget it."])
def test_termination(text: str) -> None:
    assert is_termination(text)


@pytest.mark.parametrize("text", ["stop logging coffee", "cancel the dinner expense", "coffee 5"])
def test_not_termination(text: str) -> None:
    assert not is_termination(text)


@pytest.mark.parametrize(
    "text", ["are you working?", "is this broken", "why didn't you reply", "Is the bot down?"]
)
def test_self_diagnosis(text: str) -> None:
    assert is_self_diagnosis(text)


def test_replies_are_plain_text() -> None:
    from nexus.agent.graph import strip_ids

    reply = "Tap **Advanced**, then **Allow**. Logged [id 123e4567-e89b-12d3-a456-426614174000]"
    assert strip_ids(reply) == "Tap Advanced, then Allow. Logged"


@pytest.mark.parametrize(
    ("text", "days_ago", "note"),
    [
        ("salary 9397", 0, None),
        ("9397 as salary today", 0, None),
        ("salary 9397 yesterday", 1, None),
        ("salary yesterday 9397", 1, None),
        ("received 50 from Ann yesterday", 1, None),
        ("got refunded 23.90 for the shoes yesterday", 1, "the shoes"),
    ],
)
def test_today_or_yesterday(text: str, days_ago: int, note: str | None) -> None:
    intent = parse_income(text, "SGD")
    assert intent is not None
    assert (intent.days_ago, intent.note) == (days_ago, note)
