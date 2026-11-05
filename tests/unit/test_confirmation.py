"""What the user is asked to confirm: one readable line per entry, and several entries asked
about together in one message. Every name and figure is made up."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from nexus.agent.confirmation import Ask, combine, entry_text, short_day, short_money
from nexus.domain.ledger import Direction, Source, Transaction, TransactionStatus, UserId
from nexus.domain.money import Money
from nexus.domain.voice import Preset, settings_for

TODAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 4, 0, tzinfo=UTC)


def entry(direction: Direction, amount: str, currency: str, merchant: str | None) -> Transaction:
    return Transaction(
        id=uuid4(),
        user_id=UserId(uuid4()),
        direction=direction,
        amount=Money(Decimal(amount), currency),
        occurred_at=NOW,
        counterparty=merchant,
        category_id=None,
        notes="Payment confirmation",
        status=TransactionStatus.CONFIRMED,
        source=Source.EMAIL,
        created_at=NOW,
        updated_at=NOW,
    )


def test_money_and_dates_are_short() -> None:
    assert short_money(Money(Decimal("14"), "EUR")) == "EUR 14.00"
    assert short_money(Money(Decimal("1240.5"), "SGD")) == "SGD 1,240.50"
    assert short_money(Money(Decimal("1500"), "JPY")) == "JPY 1,500"
    assert short_day(date(2026, 11, 5), TODAY) == "5 Nov"
    assert short_day(date(2025, 12, 31), TODAY) == "31 Dec 2025"


def test_money_in_says_from_and_income_and_money_out_says_at_and_the_category() -> None:
    income = entry(Direction.IN, "14", "EUR", "Acme Hire")
    assert entry_text(income, TODAY, TODAY, None) == "5 Nov · EUR 14.00 from Acme Hire (income)"
    spent = entry(Direction.OUT, "12.40", "SGD", "Kopi Corner")
    assert entry_text(spent, TODAY, TODAY, "Dining Out") == (
        "5 Nov · SGD 12.40 at Kopi Corner (Dining Out)"
    )
    assert entry_text(entry(Direction.OUT, "3", "SGD", None), TODAY, TODAY, None) == (
        "5 Nov · SGD 3.00"
    )
    assert "note" not in entry_text(spent, TODAY, TODAY, "Dining Out")


def test_one_entry_is_a_sentence_and_still_a_string() -> None:
    ask = Ask("Delete", "5 Nov · EUR 14.00 from Acme Hire (income)")
    assert ask == "Delete 5 Nov · EUR 14.00 from Acme Hire (income)?"
    assert combine([ask]) == ask
    edit = Ask("Change", "5 Nov · SGD 3.00", ": notes → lunch")
    assert combine([edit]) == "Change 5 Nov · SGD 3.00: notes → lunch?"


def test_the_same_action_on_several_entries_is_one_question() -> None:
    a = Ask("Delete", "5 Nov · EUR 14.00 from Acme Hire (income)")
    b = Ask("Delete", "6 Nov · SGD 12.40 at Kopi Corner (Dining Out)")
    assert combine([a, b]) == (
        "Delete 2 entries?\n"
        "• 5 Nov · EUR 14.00 from Acme Hire (income)\n"
        "• 6 Nov · SGD 12.40 at Kopi Corner (Dining Out)"
    )
    c, d = Ask("Change", "5 Nov · SGD 3.00", ": notes → lunch"), Ask("Change", "6 Nov · SGD 4.00")
    assert combine([c, d]).splitlines() == [
        "Change 2 entries?",
        "• 5 Nov · SGD 3.00: notes → lunch",
        "• 6 Nov · SGD 4.00",
    ]


def test_mixed_actions_get_a_bullet_each_and_other_questions_are_joined_as_before() -> None:
    delete, change = Ask("Delete", "5 Nov · SGD 3.00"), Ask("Change", "6 Nov · SGD 4.00", ": a")
    assert combine([delete, change]) == (
        "Confirm these changes?\n• Delete 5 Nov · SGD 3.00\n• Change 6 Nov · SGD 4.00: a"
    )
    assert combine([delete, "Delete the wallet Cash?"]) == (
        "Confirm these changes?\n• Delete 5 Nov · SGD 3.00\n• Delete the wallet Cash"
    )
    assert combine(["Delete Travel?", "Delete Food?"]) == "Delete Travel?\nDelete Food?"


def test_the_heading_over_several_entries_follows_the_voice_but_the_entries_never_do() -> None:
    a = Ask("Delete", "5 Nov · EUR 14.00 from Acme Hire (income)")
    b = Ask("Delete", "6 Nov · SGD 12.40 at Kopi Corner (Dining Out)")
    mixed = [Ask("Delete", "5 Nov · SGD 3.00"), Ask("Change", "6 Nov · SGD 4.00", ": a")]
    for preset in Preset:
        voice = settings_for(preset)
        many = combine([a, b], voice)
        assert many.splitlines()[1:] == combine([a, b]).splitlines()[1:]
        assert "2" in many.splitlines()[0] and "Delete" in many.splitlines()[0]
        both = combine(mixed, voice)
        assert both.splitlines()[1:] == combine(mixed).splitlines()[1:]
    assert combine(mixed, settings_for(Preset.DIRECT)).splitlines()[0] == "Confirm?"
    assert combine(mixed, settings_for(Preset.CHILL)).splitlines()[0] == (
        "Okay to go ahead with these?"
    )
    # A joke never lands on a change to the ledger.
    assert combine(mixed, settings_for(Preset.CHEEKY)) == combine(mixed)
    assert combine([a, b], settings_for(Preset.CHEEKY)) == combine([a, b])
    # One entry alone is the question itself, in every voice.
    assert combine([a], settings_for(Preset.DIRECT)) == a
