import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button, Chip, ChipGroup, Row, RowList } from "../components/ui";
import { bodyApi, type Cooking, type EstimateKind, type Food } from "./bodyApi";
import { COOKING } from "./bodyFormat";
import { useDebounced } from "./hooks";

/** One food in a meal, ready to send: the portion or grams chosen, and how it was cooked. */
export type PickedItem = { food_id: string; name: string; grams: string; label: string; kind: EstimateKind; cooking: Cooking | null; note: string | null };

const GRAMS = "grams";

/** Enter in a field here must not save the whole meal (the sheet is a form): it adds the item, or does nothing. */
const enter = (then?: () => void) => (e: KeyboardEvent) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  then?.();
};

/** A food chosen from the search: a portion from its list or a weight in grams, and a cooking style. */
function ItemForm({ food, onAdd, onBack }: { food: Food; onAdd: (item: PickedItem) => void; onBack: () => void }) {
  const [portion, setPortion] = useState(food.portions.length > 0 ? "0" : GRAMS);
  const [grams, setGrams] = useState("");
  const [cooking, setCooking] = useState<Cooking | null>(null);
  const chosen = portion === GRAMS ? null : food.portions[Number(portion)];
  const amount = chosen ? chosen.grams : grams.trim();
  const valid = Number(amount) > 0 && Number.isFinite(Number(amount));

  function add() {
    if (!valid) return;
    onAdd({
      food_id: food.id,
      name: food.name,
      grams: amount,
      label: chosen ? chosen.label : `${amount} g`,
      kind: chosen ? "portion" : "weighed",
      cooking,
      note: null,
    });
  }

  return (
    <div className="health-stack" role="group" aria-label={`Add ${food.name}`}>
      <p className="row-title">{food.name}</p>
      <label className="field">
        Portion
        <select className="input" value={portion} onChange={(e) => setPortion(e.target.value)}>
          {food.portions.map((p, i) => (
            <option key={`${p.label}-${i}`} value={String(i)}>
              {p.label}
            </option>
          ))}
          <option value={GRAMS}>Enter grams</option>
        </select>
      </label>
      {portion === GRAMS && (
        <label className="field">
          Grams
          <input className="input" type="number" inputMode="decimal" min="1" step="any" value={grams} onChange={(e) => setGrams(e.target.value)} onKeyDown={enter(add)} />
        </label>
      )}
      <ChipGroup role="radiogroup" aria-label="Cooking style">
        {COOKING.map((c) => (
          <Chip key={c.label} pressed={cooking === c.value} role="radio" aria-checked={cooking === c.value} onClick={() => setCooking(c.value)}>
            {c.label}
          </Chip>
        ))}
      </ChipGroup>
      <div className="health-actions health-inline">
        <Button variant="primary" disabled={!valid} onClick={add}>
          Add to meal
        </Button>
        <Button variant="text" onClick={onBack}>
          Back to search
        </Button>
      </div>
    </div>
  );
}

/** Search the food database, then choose a portion and a cooking style. The server works out the nutrients. */
export function FoodPicker({ onAdd, onCancel }: { onAdd: (item: PickedItem) => void; onCancel?: () => void }) {
  const [text, setText] = useState("");
  const [food, setFood] = useState<Food | null>(null);
  const search = useDebounced(text.trim());
  const found = useQuery({ queryKey: ["health", "foods", search], queryFn: () => bodyApi.foods(search), enabled: search.length > 0, staleTime: 5 * 60_000 });
  if (food) return <ItemForm food={food} onAdd={onAdd} onBack={() => setFood(null)} />;
  const list = found.data ?? [];
  return (
    <div className="health-search">
      <label className="field">
        <span className="sr-only">Search foods</span>
        <input className="input" type="search" placeholder="Search foods" aria-label="Search foods" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={enter()} />
      </label>
      {found.isError ? (
        <LoadError message="Couldn't load foods." query={found} />
      ) : search && found.isLoading ? (
        <p className="state">Loading…</p>
      ) : search && list.length === 0 ? (
        <p className="muted">No food matches that.</p>
      ) : (
        list.length > 0 && (
          <RowList aria-label="Foods">
            {list.map((f) => (
              <Row key={f.id} title={f.name} sub={f.portions[0]?.label} label={`Choose ${f.name}`} onClick={() => setFood(f)} />
            ))}
          </RowList>
        )
      )}
      {onCancel && (
        <Button variant="text" onClick={onCancel}>
          Cancel
        </Button>
      )}
    </div>
  );
}
