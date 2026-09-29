"""Category rules: they file new expenses, explain themselves, and only change when the
user accepts. A correction never rewrites a rule on its own."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import category_rules as rule_cases
from nexus.application.categories import list_categories, set_category_active
from nexus.application.transactions import (
    NewTransaction,
    TransactionChanges,
    edit_transaction,
    log_transaction,
    undo_last,
)
from nexus.application.users import get_user
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, Transaction, UserId
from nexus.domain.money import Money
from nexus.infra.db.tables import transactions
from tests.fakes import NOW
from tests.integration.conftest import UowFactory

pytestmark = pytest.mark.integration


async def category(uow: UowFactory, user: UserId, name: str) -> UUID:
    return next(c.id for c in await list_categories(uow(), user) if c.name == name)


async def spend(
    uow: UowFactory,
    user: UserId,
    merchant: str | None,
    *,
    notes: str | None = None,
    category_id: UUID | None = None,
    direction: Direction = Direction.OUT,
) -> Transaction:
    return await log_transaction(
        uow(),
        user,
        NewTransaction(
            direction,
            Money.of("12", "SGD"),
            NOW,
            counterparty=merchant,
            category_id=category_id,
            notes=notes,
        ),
    )


async def add_rule(uow: UowFactory, user: UserId, pattern: str, name: str) -> rule_cases.RuleChange:
    owner = await get_user(uow(), user)
    return await rule_cases.set_rule(
        uow(), owner, pattern, await category(uow, user, name), now=NOW
    )


async def recategorise(uow: UowFactory, user: UserId, tx: Transaction, name: str) -> Transaction:
    changes = TransactionChanges(category_id=await category(uow, user, name))
    return await edit_transaction(uow(), user, tx.id, changes)


async def test_rules_file_new_expenses_by_merchant_and_notes(
    uow: UowFactory, alice: UserId
) -> None:
    transport = await category(uow, alice, "Transport")
    food = await category(uow, alice, "Food & Drink")
    grab = (await add_rule(uow, alice, "  GRAB ", "Transport")).rule
    assert grab.pattern == "grab"
    assert grab.explanation == "You added this rule on 28 Sep 2026."

    ride = await spend(uow, alice, "Grab ride")
    assert (ride.category_id, ride.category_rule_id) == (transport, grab.id)
    # Whole words only.
    assert (await spend(uow, alice, "Grabbed a snack")).category_id is None
    # Notes count too.
    by_notes = await spend(uow, alice, "Card payment", notes="grab to airport")
    assert by_notes.category_id == transport
    # A category the user gives wins over a rule, and income is never filed by rules.
    assert (await spend(uow, alice, "Grab", category_id=food)).category_rule_id is None
    assert (await spend(uow, alice, "Grab", direction=Direction.IN)).category_id is None


async def test_the_most_specific_rule_wins(uow: UowFactory, alice: UserId) -> None:
    await add_rule(uow, alice, "grab", "Transport")
    specific = (await add_rule(uow, alice, "grab food", "Food & Drink")).rule
    await add_rule(uow, alice, "lunch", "Groceries")

    assert (await spend(uow, alice, "GrabFood")).category_id is None
    delivery = await spend(uow, alice, "Grab Food")
    assert delivery.category_rule_id == specific.id
    # A merchant match beats a notes match, even a longer one.
    ride = await spend(uow, alice, "Grab", notes="lunch")
    assert ride.category_id == await category(uow, alice, "Transport")


async def test_rules_for_archived_categories_are_skipped(uow: UowFactory, alice: UserId) -> None:
    change = await add_rule(uow, alice, "netflix", "Entertainment")
    await set_category_active(uow(), alice, change.category.id, False)
    assert (await spend(uow, alice, "Netflix")).category_id is None


async def test_a_correction_offers_a_rule_change_but_never_makes_one(
    uow: UowFactory, alice: UserId
) -> None:
    grab = (await add_rule(uow, alice, "grab", "Transport")).rule
    ride = await spend(uow, alice, "Grab")

    moved = await recategorise(uow, alice, ride, "Food & Drink")
    assert moved.category_rule_id is None  # the user chose it; the rule no longer explains it
    [view] = await rule_cases.list_rules(uow(), alice)
    assert view.rule == grab  # untouched
    offer = await rule_cases.suggest_rule(uow(), alice, moved)
    assert offer is not None
    assert offer.question == "Change your rule for “grab” from Transport to Food & Drink?"

    # The next Grab still follows the rule until the user accepts.
    assert (await spend(uow, alice, "Grab")).category_id == grab.category_id

    owner = await get_user(uow(), alice)
    later = NOW + timedelta(hours=1)
    change = await rule_cases.accept_suggestion(uow(), owner, moved.id, now=later)
    assert change.changed and change.previous is not None
    assert change.rule.category_id == await category(uow, alice, "Food & Drink")
    assert change.rule.explanation == (
        "Changed from Transport to Food & Drink on 28 Sep 2026 "
        "when you filed “Grab” under Food & Drink."
    )
    # Pressing the button again changes nothing.
    again = await rule_cases.accept_suggestion(uow(), owner, moved.id, now=later)
    assert not again.changed and again.rule == change.rule
    explained = await rule_cases.explain(uow(), alice, moved.id)
    assert explained.text.startswith("It's in Food & Drink because of your rule “grab”.")
    # Expenses the old rule filed keep their category; the rule only files new ones.
    assert (await rule_cases.explain(uow(), alice, ride.id)).category is not None


async def test_a_new_merchant_is_offered_a_rule(uow: UowFactory, alice: UserId) -> None:
    tx = await spend(uow, alice, "Tiong Bahru Bakery")
    moved = await recategorise(uow, alice, tx, "Food & Drink")
    offer = await rule_cases.suggest_rule(uow(), alice, moved)
    assert offer is not None
    assert offer.question == "Always file “tiong bahru bakery” under Food & Drink?"

    owner = await get_user(uow(), alice)
    change = await rule_cases.accept_suggestion(uow(), owner, moved.id, now=NOW)
    assert change.changed and change.previous is None
    assert change.rule.explanation == (
        "Added on 28 Sep 2026 when you filed “Tiong Bahru Bakery” under Food & Drink."
    )
    assert (await spend(uow, alice, "Tiong Bahru Bakery")).category_rule_id == change.rule.id
    # Once the rule agrees, corrections to it aren't offered again.
    assert await rule_cases.suggest_rule(uow(), alice, moved) is None


async def test_a_narrower_rule_leaves_the_broader_one_alone(uow: UowFactory, alice: UserId) -> None:
    grab = (await add_rule(uow, alice, "grab", "Transport")).rule
    delivery = await spend(uow, alice, "Grab Food")
    moved = await recategorise(uow, alice, delivery, "Food & Drink")
    offer = await rule_cases.suggest_rule(uow(), alice, moved)
    assert offer is not None
    assert offer.question == (
        "Always file “grab food” under Food & Drink? Your rule for “grab” stays as it is."
    )
    owner = await get_user(uow(), alice)
    await rule_cases.accept_suggestion(uow(), owner, moved.id, now=NOW)
    rules = {v.rule.pattern: v.category.name for v in await rule_cases.list_rules(uow(), alice)}
    assert rules == {"grab": "Transport", "grab food": "Food & Drink"}
    assert (await spend(uow, alice, "Grab")).category_rule_id == grab.id


async def test_no_offer_when_nothing_would_change(uow: UowFactory, alice: UserId) -> None:
    await add_rule(uow, alice, "grab", "Transport")
    tx = await spend(uow, alice, "Grab", category_id=await category(uow, alice, "Shopping"))
    back = await recategorise(uow, alice, tx, "Transport")
    assert await rule_cases.suggest_rule(uow(), alice, back) is None  # the rule already agrees
    anonymous = await recategorise(uow, alice, await spend(uow, alice, None), "Health")
    assert await rule_cases.suggest_rule(uow(), alice, anonymous) is None  # no merchant
    owner = await get_user(uow(), alice)
    with pytest.raises(InvalidInput):
        await rule_cases.accept_suggestion(uow(), owner, anonymous.id, now=NOW)


async def test_removed_rules_stop_filing_but_still_explain(uow: UowFactory, alice: UserId) -> None:
    grab = (await add_rule(uow, alice, "grab", "Transport")).rule
    ride = await spend(uow, alice, "Grab")
    await rule_cases.remove_rule(uow(), alice, grab.id, now=NOW)
    assert await rule_cases.list_rules(uow(), alice) == []
    assert (await spend(uow, alice, "Grab")).category_id is None
    explained = await rule_cases.explain(uow(), alice, ride.id)
    assert explained.text == (
        "It's in Transport because of your rule “grab”. That rule has since been removed."
    )
    with pytest.raises(NotFound):
        await rule_cases.remove_rule(uow(), alice, grab.id, now=NOW)
    # The pattern is free for a new rule.
    assert (await add_rule(uow, alice, "grab", "Travel")).rule.id != grab.id


async def test_explanations(uow: UowFactory, alice: UserId) -> None:
    assert (await rule_cases.explain(uow(), alice, (await spend(uow, alice, "x")).id)).text == (
        "It isn't in a category."
    )
    chosen = await spend(uow, alice, "Grab", category_id=await category(uow, alice, "Transport"))
    assert (await rule_cases.explain(uow(), alice, chosen.id)).text == (
        "It's in Transport because that was chosen for it, not by a rule."
    )
    await add_rule(uow, alice, "grab", "Transport")
    ride = await spend(uow, alice, "Grab")
    assert (await rule_cases.explain(uow(), alice, ride.id)).text == (
        "It's in Transport because of your rule “grab”. You added this rule on 28 Sep 2026."
    )
    await add_rule(uow, alice, "grab", "Travel")  # an explicit change by the user
    assert (await rule_cases.explain(uow(), alice, ride.id)).text == (
        "It's in Transport because of your rule “grab”. That rule now files under Travel instead."
    )


async def test_undoing_a_correction_brings_the_rule_back(uow: UowFactory, alice: UserId) -> None:
    grab = (await add_rule(uow, alice, "grab", "Transport")).rule
    ride = await spend(uow, alice, "Grab")
    await recategorise(uow, alice, ride, "Food & Drink")
    restored = (await undo_last(uow(), alice)).transaction
    assert (restored.category_id, restored.category_rule_id) == (grab.category_id, grab.id)


async def test_rules_are_private(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    grab = (await add_rule(uow, alice, "grab", "Transport")).rule
    assert (await spend(uow, bob, "Grab")).category_id is None
    assert await rule_cases.list_rules(uow(), bob) == []
    with pytest.raises(NotFound):
        await rule_cases.remove_rule(uow(), bob, grab.id, now=NOW)
    bob_user = await get_user(uow(), bob)
    with pytest.raises(NotFound):  # alice's category
        await rule_cases.set_rule(uow(), bob_user, "taxi", grab.category_id, now=NOW)
    ride = await spend(uow, alice, "Grab")
    with pytest.raises(NotFound):
        await rule_cases.accept_suggestion(uow(), bob_user, ride.id, now=NOW)
    with pytest.raises(NotFound):
        await rule_cases.explain(uow(), bob, ride.id)

    # The database itself refuses to point bob's expense at alice's rule.
    theirs = await spend(uow, bob, "Grab", category_id=await category(uow, bob, "Transport"))
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                update(transactions)
                .where(transactions.c.id == theirs.id)
                .values(category_rule_id=grab.id)
            )


async def test_bad_patterns_are_refused(uow: UowFactory, alice: UserId) -> None:
    for pattern in ("", " x ", "y" * 61):
        with pytest.raises(InvalidInput):
            await add_rule(uow, alice, pattern, "Transport")
    with pytest.raises(NotFound):
        await rule_cases.find_rule(uow(), alice, "nothing here")
