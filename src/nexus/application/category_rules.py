"""Category rules: explainable, and changed only when the user says so.

A rule files new expenses whose merchant (or notes) contains its pattern. When
the user corrects a category, nothing changes behind their back: they're
offered a rule (or a change to one) and it's saved only if they accept.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.categories import require_category
from nexus.application.ports import LedgerRepository, UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Category, Direction, Transaction, User, UserId
from nexus.domain.rules import CategoryRule, best_rule, clean_pattern, pattern_for


@dataclass(frozen=True, slots=True)
class RuleView:
    rule: CategoryRule
    category: Category


@dataclass(frozen=True, slots=True)
class RuleChange:
    rule: CategoryRule
    category: Category
    previous: Category | None  # the category it had, when an existing rule changed
    changed: bool  # False when the rule already said this


@dataclass(frozen=True, slots=True)
class RuleSuggestion:
    """Offered after the user files an expense under a different category."""

    transaction_id: UUID
    pattern: str
    category: Category
    replaces: Category | None  # the category of the user's existing rule for this pattern
    broader: str | None  # a shorter rule that also matches and stays as it is

    @property
    def question(self) -> str:
        if self.replaces is not None:
            return (
                f"Change your rule for “{self.pattern}” from {self.replaces.name} "
                f"to {self.category.name}?"
            )
        tail = f" Your rule for “{self.broader}” stays as it is." if self.broader else ""
        return f"Always file “{self.pattern}” under {self.category.name}?{tail}"


@dataclass(frozen=True, slots=True)
class CategoryExplanation:
    transaction: Transaction
    category: Category | None
    rule: CategoryRule | None
    rule_category: Category | None  # the rule's category now; it may have changed since

    @property
    def text(self) -> str:
        if self.category is None:
            return "It isn't in a category."
        if self.rule is None:
            if self.category.name.casefold() in ("other", "income"):
                return (
                    f"It's in {self.category.name}: no rule matched it and no other category "
                    "was picked, or it was filed there directly."
                )
            return f"It's in {self.category.name} because that was chosen for it, not by a rule."
        why = f"It's in {self.category.name} because of your rule “{self.rule.pattern}”."
        if not self.rule.active:
            return f"{why} That rule has since been removed."
        if self.rule_category is not None and self.rule_category.id != self.category.id:
            return f"{why} That rule now files under {self.rule_category.name} instead."
        return f"{why} {self.rule.explanation}"


def _day(user: User, now: datetime) -> str:
    return f"{now.astimezone(ZoneInfo(user.timezone)):%-d %b %Y}"


async def _category(repo: LedgerRepository, actor: UserId, category_id: UUID) -> Category:
    category = await repo.get_category(actor, category_id)
    if category is None:  # pragma: no cover - foreign keys keep this from happening
        raise NotFound("category not found")
    return category


def _exact(rules: list[CategoryRule], pattern: str) -> CategoryRule | None:
    return next((r for r in rules if r.pattern == pattern), None)


async def list_rules(uow: UnitOfWork, actor: UserId) -> list[RuleView]:
    async with uow:
        rules = await uow.ledger.list_category_rules(actor)
        cats = {c.id: c for c in await uow.ledger.list_categories(actor, include_inactive=True)}
    return [RuleView(r, cats[r.category_id]) for r in rules]


async def find_rule(uow: UnitOfWork, actor: UserId, pattern: str) -> RuleView:
    wanted = clean_pattern(pattern)
    for view in await list_rules(uow, actor):
        if view.rule.pattern == wanted:
            return view
    raise NotFound(f"there is no rule for “{wanted}”")


async def set_rule(
    uow: UnitOfWork, user: User, pattern: str, category_id: UUID, *, now: datetime
) -> RuleChange:
    """Add a rule, or change the category of the user's rule for this pattern.
    Only for an explicit request from the user."""
    pattern = clean_pattern(pattern)
    async with uow:
        repo = uow.ledger
        category = await require_category(repo, user.id, category_id)
        existing = _exact(await repo.list_category_rules(user.id), pattern)
        if existing is None:
            rule = CategoryRule(
                uuid4(),
                user.id,
                pattern,
                category.id,
                f"You added this rule on {_day(user, now)}.",
                now,
                now,
            )
            await repo.insert_category_rule(rule)
            await uow.commit()
            return RuleChange(rule, category, None, True)
        if existing.category_id == category.id:
            return RuleChange(existing, category, None, False)
        previous = await _category(repo, user.id, existing.category_id)
        rule = replace(
            existing,
            category_id=category.id,
            explanation=(
                f"Changed from {previous.name} to {category.name} on {_day(user, now)} "
                "at your request."
            ),
            updated_at=now,
        )
        await repo.update_category_rule(rule)
        await uow.commit()
    return RuleChange(rule, category, previous, True)


async def remove_rule(uow: UnitOfWork, actor: UserId, rule_id: UUID, *, now: datetime) -> None:
    """Archive a rule. Expenses it already filed keep their category."""
    async with uow:
        rule = await uow.ledger.get_category_rule(actor, rule_id)
        if rule is None or not rule.active:
            raise NotFound("rule not found")
        await uow.ledger.update_category_rule(replace(rule, archived_at=now, updated_at=now))
        await uow.commit()


async def suggest_rule(uow: UnitOfWork, actor: UserId, tx: Transaction) -> RuleSuggestion | None:
    """What to offer after the user moved ``tx`` into its category: None when the
    rules already agree, or the expense has no merchant to make a rule from."""
    if tx.direction is not Direction.OUT or tx.category_id is None or tx.is_deleted:
        return None
    pattern = pattern_for(tx.counterparty)
    if pattern is None:
        return None
    async with uow:
        repo = uow.ledger
        rules = await repo.list_category_rules(actor)
        exact = _exact(rules, pattern)
        broader = best_rule(rules, tx.counterparty, tx.notes)
        agreeing = exact or broader
        if agreeing is not None and agreeing.category_id == tx.category_id:
            return None
        category = await _category(repo, actor, tx.category_id)
        if exact is not None:
            replaces = await _category(repo, actor, exact.category_id)
            return RuleSuggestion(tx.id, pattern, category, replaces, None)
    return RuleSuggestion(
        tx.id, pattern, category, None, broader.pattern if broader is not None else None
    )


async def accept_suggestion(
    uow: UnitOfWork, user: User, transaction_id: UUID, *, now: datetime
) -> RuleChange:
    """The user said yes to a suggestion: save the rule for this expense's merchant and
    category as they are now. Pressing it twice changes nothing more."""
    async with uow:
        repo = uow.ledger
        tx = await repo.get_transaction(user.id, transaction_id, for_update=True)
        if tx is None or tx.is_deleted:
            raise NotFound("that expense is gone, so there's nothing to make a rule from")
        pattern = pattern_for(tx.counterparty)
        if tx.category_id is None or pattern is None:
            raise InvalidInput("that expense needs a merchant and a category to make a rule")
        category = await require_category(repo, user.id, tx.category_id)
        existing = _exact(await repo.list_category_rules(user.id), pattern)
        when = f"on {_day(user, now)} when you filed “{tx.counterparty}” under {category.name}."
        previous: Category | None = None
        if existing is None:
            rule = CategoryRule(uuid4(), user.id, pattern, category.id, f"Added {when}", now, now)
            await repo.insert_category_rule(rule)
        elif existing.category_id == category.id:
            return RuleChange(existing, category, None, False)
        else:
            previous = await _category(repo, user.id, existing.category_id)
            rule = replace(
                existing,
                category_id=category.id,
                explanation=f"Changed from {previous.name} to {category.name} {when}",
                updated_at=now,
            )
            await repo.update_category_rule(rule)
        # The expense is now explained by the rule it created.
        await repo.update_transaction(replace(tx, category_rule_id=rule.id))
        await uow.commit()
    return RuleChange(rule, category, previous, True)


async def explain(uow: UnitOfWork, actor: UserId, transaction_id: UUID) -> CategoryExplanation:
    async with uow:
        repo = uow.ledger
        tx = await repo.get_transaction(actor, transaction_id)
        if tx is None:
            raise NotFound("transaction not found")
        category = await _category(repo, actor, tx.category_id) if tx.category_id else None
        rule = (
            await repo.get_category_rule(actor, tx.category_rule_id)
            if tx.category_rule_id
            else None
        )
        rule_category = await _category(repo, actor, rule.category_id) if rule else None
    return CategoryExplanation(tx, category, rule, rule_category)
