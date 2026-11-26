"""Tools for the user's spending categories."""

from pydantic import Field

from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.application import categories as category_cases
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import (
    Category,
)


async def _categories(ctx: ToolContext, _: NoArgs) -> ToolResult:
    cats = await category_cases.list_categories(ctx.uow(), ctx.user.id)
    return ToolResult(", ".join(c.name for c in cats) or "No categories.")


class CategoryNameArgs(Args):
    category: str = Field(description="The category's name")


class RenameCategoryArgs(Args):
    category: str = Field(description="The category's current name")
    new_name: str = Field(description="What to call it")


async def _find_category(ctx: ToolContext, name: str) -> Category | None:
    found = await category_cases.list_categories(ctx.uow(), ctx.user.id)
    return next((c for c in found if c.name.casefold() == name.strip().casefold()), None)


async def _add_category(ctx: ToolContext, a: CategoryNameArgs) -> ToolResult:
    existing = await _find_category(ctx, a.category)
    if existing is not None:
        return ToolResult(f"There's already a category called {existing.name}.")
    made = await category_cases.create_category(ctx.uow(), ctx.user.id, a.category)
    return ToolResult(f"Added the category {made.name}.", wrote=True)


async def _rename_category(ctx: ToolContext, a: RenameCategoryArgs) -> ToolResult:
    current = await _find_category(ctx, a.category)
    if current is None:
        raise NotFound(f"there's no category called {a.category!r}")
    clash = await _find_category(ctx, a.new_name)
    if clash is not None and clash.id != current.id:
        raise InvalidInput(f"there's already a category called {clash.name}")
    renamed = await category_cases.rename_category(ctx.uow(), ctx.user.id, current.id, a.new_name)
    return ToolResult(
        f"Renamed {current.name} to {renamed.name}. Everything filed under it moves with it.",
        wrote=True,
    )


class DeleteCategoryArgs(Args):
    category: str = Field(description="The category to delete")
    move_to: str = Field(default="Other", description="The category its expenses and rules move to")


async def _delete_pair(ctx: ToolContext, a: DeleteCategoryArgs) -> tuple[Category, Category]:
    current = await _find_category(ctx, a.category)
    if current is None:
        raise NotFound(f"there's no category called {a.category!r}")
    if category_cases.is_protected(current):
        raise InvalidInput("Other and Income can't be deleted")
    into = await _find_category(ctx, a.move_to)
    if into is None:
        raise NotFound(f"there's no category called {a.move_to!r}")
    if into.id == current.id:
        raise InvalidInput("pick a different category to move its expenses to")
    return current, into


async def _describe_delete_category(ctx: ToolContext, a: DeleteCategoryArgs) -> str:
    current, into = await _delete_pair(ctx, a)
    return f"Delete {current.name}? Its expenses and rules move to {into.name}."


async def _delete_category(ctx: ToolContext, a: DeleteCategoryArgs) -> ToolResult:
    current, into = await _delete_pair(ctx, a)
    deleted = await category_cases.delete_category(
        ctx.uow(), ctx.user.id, current.id, into.id, now=ctx.now
    )
    count = f"{deleted.moved} expense{'' if deleted.moved == 1 else 's'}"
    return ToolResult(f"Deleted {current.name}. Its {count} moved to {into.name}.", wrote=True)


class MergeCategoryArgs(Args):
    category: str = Field(description="The category to fold away")
    into: str = Field(description="The category its expenses move into")


async def _merge_pair(ctx: ToolContext, a: MergeCategoryArgs) -> tuple[Category, Category]:
    source = await _find_category(ctx, a.category)
    if source is None:
        raise NotFound(f"there's no category called {a.category!r}")
    if category_cases.is_protected(source):
        raise InvalidInput("Other and Income can't be merged away")
    into = await _find_category(ctx, a.into)
    if into is None:
        raise NotFound(f"there's no category called {a.into!r}")
    if into.id == source.id:
        raise InvalidInput("pick a different category to merge into")
    return source, into


async def _describe_merge_category(ctx: ToolContext, a: MergeCategoryArgs) -> str:
    source, into = await _merge_pair(ctx, a)
    return (
        f"Move everything filed under {source.name} into {into.name} and delete "
        f"{source.name}? This can't be undone automatically."
    )


async def _merge_category(ctx: ToolContext, a: MergeCategoryArgs) -> ToolResult:
    source, into = await _merge_pair(ctx, a)
    merged = await category_cases.merge_category(
        ctx.uow(), ctx.user.id, source.id, into.id, now=ctx.now
    )
    count = f"{merged.moved} transaction{'' if merged.moved == 1 else 's'}"
    return ToolResult(
        f"Merged {source.name} into {into.name}: {count} moved, and {source.name} is deleted.",
        wrote=True,
    )


SPECS: list[ToolSpec] = [
    ToolSpec("list_categories", "The user's categories.", NoArgs, _categories),
    ToolSpec(
        "add_category",
        "Add a category of the user's own.",
        CategoryNameArgs,
        _add_category,
    ),
    ToolSpec(
        "rename_category",
        "Rename one of the user's categories; its expenses move with it.",
        RenameCategoryArgs,
        _rename_category,
    ),
    ToolSpec(
        "delete_category",
        "Delete a category: its expenses and rules move to another category (Other "
        "unless the user names one). Other and Income can't be deleted. Asks the user "
        "to confirm.",
        DeleteCategoryArgs,
        _delete_category,
        confirm=_describe_delete_category,
    ),
    ToolSpec(
        "merge_category",
        "Fold one category into another: its expenses, rules and budget move over and "
        "it's deleted. Asks the user to confirm.",
        MergeCategoryArgs,
        _merge_category,
        confirm=_describe_merge_category,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"list_categories"})
