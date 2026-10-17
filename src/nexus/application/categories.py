from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from nexus.application.ports import LedgerRepository, UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Category, UserId, clean_name

# The fallbacks new expenses and income land in, found by name: they can't go away.
PROTECTED_NAMES = ("other", "income")


async def require_category(repo: LedgerRepository, actor: UserId, category_id: UUID) -> Category:
    category = await repo.get_category(actor, category_id)
    if category is None:
        raise NotFound("category not found")
    return category


async def create_category(uow: UnitOfWork, actor: UserId, name: str) -> Category:
    category = Category(uuid4(), actor, clean_name(name, field_name="category name"))
    async with uow:
        await uow.ledger.insert_category(category)
        await uow.commit()
    return category


async def rename_category(uow: UnitOfWork, actor: UserId, category_id: UUID, name: str) -> Category:
    async with uow:
        category = await require_category(uow.ledger, actor, category_id)
        renamed = replace(category, name=clean_name(name, field_name="category name"))
        await uow.ledger.update_category(renamed)
        await uow.commit()
    return renamed


async def list_categories(uow: UnitOfWork, actor: UserId) -> list[Category]:
    async with uow:
        return await uow.ledger.list_categories(actor)


@dataclass(frozen=True, slots=True)
class Merged:
    source: Category
    into: Category
    moved: int  # transactions refiled


def is_protected(category: Category) -> bool:
    return category.name.casefold() in PROTECTED_NAMES


async def merge_category(
    uow: UnitOfWork, actor: UserId, source_id: UUID, into_id: UUID, *, now: datetime
) -> Merged:
    """Fold one category into another: its expenses, rules and (if the other has none)
    budget move over, and it's deleted. Not undoable."""
    if source_id == into_id:
        raise InvalidInput("pick a different category to merge into")
    async with uow:
        source = await require_category(uow.ledger, actor, source_id)
        if is_protected(source):
            raise InvalidInput("Other and Income can't be merged away")
        into = await require_category(uow.ledger, actor, into_id)
        moved = await uow.ledger.merge_category(actor, source.id, into.id, now, keep_budget=True)
        await uow.commit()
    return Merged(source, into, moved)


async def delete_category(
    uow: UnitOfWork, actor: UserId, category_id: UUID, move_to: UUID | None, *, now: datetime
) -> Merged:
    """Delete a category: its expenses and rules move to ``move_to`` (the user's "Other"
    if not given) and its budget goes with it. Not undoable."""
    if move_to == category_id:
        raise InvalidInput("pick a different category to move its expenses to")
    async with uow:
        category = await require_category(uow.ledger, actor, category_id)
        if is_protected(category):
            raise InvalidInput("Other and Income can't be deleted")
        if move_to is None:
            fallback = next(
                (
                    c
                    for c in await uow.ledger.list_categories(actor)
                    if c.name.casefold() == "other"
                ),
                None,
            )
            if fallback is None:
                raise InvalidInput("there's no Other category to move its expenses to")
            into = fallback
        else:
            into = await require_category(uow.ledger, actor, move_to)
        moved = await uow.ledger.merge_category(actor, category.id, into.id, now, keep_budget=False)
        await uow.commit()
    return Merged(category, into, moved)
