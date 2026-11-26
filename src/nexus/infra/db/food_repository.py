"""PostgreSQL storage for food logging: the food database (shared by every user, so no user_id)
and each user's meals and items (every query filters on user_id)."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Row, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus.domain.ledger import UserId
from nexus.domain.nutrition import (
    Cooking,
    EntrySource,
    EstimateKind,
    Food,
    FoodItem,
    FoodSource,
    MealEntry,
    MealSlot,
    Nutrients,
    Portion,
    words,
)
from nexus.infra.db.tables import foods, meal_entries, meal_items

D = Decimal


def _food(row: Row[Any]) -> Food:
    return Food(
        id=row.id,
        source=FoodSource(row.source),
        name=row.name,
        aliases=tuple(row.aliases),
        per_100g=Nutrients(
            row.kcal_100g,
            row.protein_g_100g,
            row.carbs_g_100g,
            row.fat_g_100g,
            row.fibre_g_100g,
        ),
        portions=tuple(Portion(p["label"], D(str(p["grams"]))) for p in row.portions),
    )


def _food_values(food: Food) -> dict[str, Any]:
    n = food.per_100g
    return {
        "id": food.id,
        "source": food.source.value,
        "name": food.name,
        "aliases": list(food.aliases),
        "kcal_100g": n.kcal,
        "protein_g_100g": n.protein_g,
        "carbs_g_100g": n.carbs_g,
        "fat_g_100g": n.fat_g,
        "fibre_g_100g": n.fibre_g,
        "portions": [{"label": p.label, "grams": str(p.grams)} for p in food.portions],
    }


def _item(row: Row[Any]) -> FoodItem:
    return FoodItem(
        food_id=row.food_id,
        grams=row.grams,
        label=row.portion_label,
        nutrients=Nutrients(row.kcal, row.protein_g, row.carbs_g, row.fat_g, row.fibre_g),
        kind=EstimateKind(row.estimate_kind),
        cooking=Cooking(row.cooking) if row.cooking else None,
        extra_uncertainty=row.extra_uncertainty,
        note=row.note,
        id=row.id,
    )


def _item_values(user_id: UserId, entry_id: UUID, position: int, item: FoodItem) -> dict[str, Any]:
    n = item.nutrients
    return {
        "id": item.id or uuid4(),
        "user_id": user_id,
        "entry_id": entry_id,
        "position": position,
        "food_id": item.food_id,
        "grams": item.grams,
        "portion_label": item.label,
        "estimate_kind": item.kind.value,
        "cooking": item.cooking.value if item.cooking else None,
        "extra_uncertainty": item.extra_uncertainty,
        "note": item.note,
        "kcal": n.kcal,
        "protein_g": n.protein_g,
        "carbs_g": n.carbs_g,
        "fat_g": n.fat_g,
        "fibre_g": n.fibre_g,
    }


def _entry(row: Row[Any], items: Sequence[FoodItem]) -> MealEntry:
    return MealEntry(
        id=row.id,
        user_id=UserId(row.user_id),
        meal=MealSlot(row.meal),
        eaten_at=row.eaten_at,
        source=EntrySource(row.source),
        note=row.note,
        items=tuple(items),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlFoodRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    # --- the shared food database --------------------------------------------------------

    async def get_food(self, food_id: str) -> Food | None:
        row = (await self._connection.execute(select(foods).where(foods.c.id == food_id))).first()
        return _food(row) if row else None

    async def get_foods(self, ids: Sequence[str]) -> dict[str, Food]:
        if not ids:
            return {}
        rows = await self._connection.execute(select(foods).where(foods.c.id.in_(ids)))
        return {r.id: _food(r) for r in rows}

    async def find_foods(self, text: str, *, limit: int) -> list[Food]:
        clauses = [
            or_(
                foods.c.name.ilike(f"%{word}%"),
                func.array_to_string(foods.c.aliases, " ").ilike(f"%{word}%"),
            )
            for word in words(text)
        ]
        query = (
            select(foods)
            .where(*clauses)
            .order_by(func.length(foods.c.name), foods.c.id)
            .limit(limit)
        )
        return [_food(r) for r in (await self._connection.execute(query)).all()]

    async def upsert_foods(self, catalogue: Sequence[Food]) -> int:
        """Insert new foods and update changed ones; leave identical rows alone and never
        delete. Returns how many rows were written."""
        have = {r.id: _food(r) for r in await self._connection.execute(select(foods))}
        changed = [f for f in catalogue if have.get(f.id) != f]
        for start in range(0, len(changed), 2000):  # stay under the driver's parameter limit
            insert = pg_insert(foods)
            await self._connection.execute(
                insert.on_conflict_do_update(
                    index_elements=[foods.c.id],
                    set_={c.name: insert.excluded[c.name] for c in foods.c if c.name != "id"},
                ),
                [_food_values(f) for f in changed[start : start + 2000]],
            )
        return len(changed)

    # --- one user's meals ----------------------------------------------------------------

    async def add_meal(self, entry: MealEntry) -> None:
        await self._connection.execute(
            meal_entries.insert().values(
                id=entry.id,
                user_id=entry.user_id,
                meal=entry.meal.value,
                eaten_at=entry.eaten_at,
                source=entry.source.value,
                note=entry.note,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
            )
        )
        await self._add_items(entry)

    async def _add_items(self, entry: MealEntry) -> None:
        if entry.items:
            await self._connection.execute(
                meal_items.insert(),
                [
                    _item_values(entry.user_id, entry.id, i, item)
                    for i, item in enumerate(entry.items)
                ],
            )

    async def replace_meal(self, entry: MealEntry) -> bool:
        result = await self._connection.execute(
            update(meal_entries)
            .where(meal_entries.c.id == entry.id, meal_entries.c.user_id == entry.user_id)
            .values(
                meal=entry.meal.value,
                eaten_at=entry.eaten_at,
                source=entry.source.value,
                note=entry.note,
                updated_at=entry.updated_at,
            )
        )
        if not result.rowcount:
            return False
        await self._connection.execute(
            delete(meal_items).where(
                meal_items.c.entry_id == entry.id, meal_items.c.user_id == entry.user_id
            )
        )
        await self._add_items(entry)
        return True

    async def delete_meal(self, user_id: UserId, meal_id: UUID) -> bool:
        await self._connection.execute(
            delete(meal_items).where(
                meal_items.c.entry_id == meal_id, meal_items.c.user_id == user_id
            )
        )
        result = await self._connection.execute(
            delete(meal_entries).where(
                meal_entries.c.id == meal_id, meal_entries.c.user_id == user_id
            )
        )
        return bool(result.rowcount)

    async def _with_items(self, user_id: UserId, rows: Sequence[Row[Any]]) -> list[MealEntry]:
        if not rows:
            return []
        found = await self._connection.execute(
            select(meal_items)
            .where(meal_items.c.user_id == user_id, meal_items.c.entry_id.in_([r.id for r in rows]))
            .order_by(meal_items.c.entry_id, meal_items.c.position)
        )
        by_entry: dict[UUID, list[FoodItem]] = {}
        for item in found:
            by_entry.setdefault(item.entry_id, []).append(_item(item))
        return [_entry(r, by_entry.get(r.id, [])) for r in rows]

    async def get_meal(self, user_id: UserId, meal_id: UUID) -> MealEntry | None:
        row = (
            await self._connection.execute(
                select(meal_entries).where(
                    meal_entries.c.id == meal_id, meal_entries.c.user_id == user_id
                )
            )
        ).first()
        return (await self._with_items(user_id, [row]))[0] if row else None

    async def list_meals(
        self, user_id: UserId, *, start: datetime, end: datetime, limit: int
    ) -> list[MealEntry]:
        rows = (
            await self._connection.execute(
                select(meal_entries)
                .where(
                    meal_entries.c.user_id == user_id,
                    meal_entries.c.eaten_at >= start,
                    meal_entries.c.eaten_at < end,
                )
                .order_by(meal_entries.c.eaten_at, meal_entries.c.id)
                .limit(limit)
            )
        ).all()
        return await self._with_items(user_id, rows)
