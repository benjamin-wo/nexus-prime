from dataclasses import replace
from uuid import UUID, uuid4

from nexus.application.ports import LedgerRepository, UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Category, UserId, clean_name


async def require_category(
    repo: LedgerRepository, actor: UserId, category_id: UUID, *, active: bool = True
) -> Category:
    category = await repo.get_category(actor, category_id)
    if category is None:
        raise NotFound("category not found")
    if active and not category.active:
        raise InvalidInput(f"category {category.name!r} is archived")
    return category


async def create_category(uow: UnitOfWork, actor: UserId, name: str) -> Category:
    category = Category(uuid4(), actor, clean_name(name, field_name="category name"), True)
    async with uow:
        await uow.ledger.insert_category(category)
        await uow.commit()
    return category


async def rename_category(uow: UnitOfWork, actor: UserId, category_id: UUID, name: str) -> Category:
    async with uow:
        category = await require_category(uow.ledger, actor, category_id, active=False)
        renamed = replace(category, name=clean_name(name, field_name="category name"))
        await uow.ledger.update_category(renamed)
        await uow.commit()
    return renamed


async def set_category_active(
    uow: UnitOfWork, actor: UserId, category_id: UUID, active: bool
) -> Category:
    """Archive or unarchive. Archived categories stay on past transactions."""
    async with uow:
        category = await require_category(uow.ledger, actor, category_id, active=False)
        updated = replace(category, active=active)
        await uow.ledger.update_category(updated)
        await uow.commit()
    return updated


async def list_categories(
    uow: UnitOfWork, actor: UserId, *, include_inactive: bool = False
) -> list[Category]:
    async with uow:
        return await uow.ledger.list_categories(actor, include_inactive=include_inactive)
