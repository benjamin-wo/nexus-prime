import { Row, RowList } from "../components/ui";
import type { Meal } from "./bodyApi";
import { cookingLabel, kcalRange, slotLabel } from "./bodyFormat";

/** The meals of a day: the slot, the foods, and the server's range for the meal (none in numbers-free mode). */
export function MealList({ meals, onOpen }: { meals: Meal[]; onOpen: (meal: Meal) => void }) {
  return (
    <RowList aria-label="Meals">
      {meals.map((m) => (
        <Row
          key={m.id}
          title={slotLabel(m.meal)}
          sub={m.items.map((i) => `${i.name ?? "Food"}${i.cooking ? ` (${cookingLabel(i.cooking).toLowerCase()})` : ""}`).join(", ")}
          trailing={m.totals ? <span className="health-fig">{kcalRange(m.totals)}</span> : undefined}
          label={`Open ${slotLabel(m.meal)}`}
          onClick={() => onOpen(m)}
        />
      ))}
    </RowList>
  );
}
