import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { ConfirmBox } from "../components/ConfirmBox";
import { Sheet } from "../components/Sheet";
import { Button, Chip, ChipGroup, Row, RowList } from "../components/ui";
import { healthKey } from "./api";
import { bodyApi, type ItemInput, type Meal, type MealSlot } from "./bodyApi";
import { cookingLabel, kcalRange, SLOTS, slotLabel } from "./bodyFormat";
import { FoodPicker, type PickedItem } from "./FoodPicker";

const guessSlot = (): MealSlot => {
  const h = new Date().getHours();
  return h < 10 ? "breakfast" : h < 15 ? "lunch" : h < 21 ? "dinner" : "snack";
};

const toInput = (i: PickedItem): ItemInput => ({ food_id: i.food_id, grams: i.grams, label: i.label, kind: i.kind, cooking: i.cooking, note: i.note });

/**
 * Add a meal, or edit one: its slot and its items. Each item is a food from the database with a portion or grams and a
 * cooking style. The server works out the nutrients; after saving the sheet shows the range it sent back.
 * `day` is a YYYY-MM-DD other than today, so the meal is put on that day.
 */
export function MealSheet({ meal, day, onClose, onDeleted }: { meal?: Meal; day: string | null; onClose: () => void; onDeleted?: (meal: Meal) => void }) {
  const client = useQueryClient();
  const [slot, setSlot] = useState<MealSlot>(meal?.meal ?? guessSlot());
  const [items, setItems] = useState<PickedItem[]>(meal?.items.map((i) => ({ ...i, name: i.name ?? "Food" })) ?? []);
  const [adding, setAdding] = useState(!meal);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Meal | null>(null);

  async function run(work: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      await work();
      await client.invalidateQueries({ queryKey: healthKey.all });
    } catch (e) {
      setError(e instanceof Error ? e.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    if (items.length === 0) return;
    void run(async () => {
      const body = { meal: slot, items: items.map(toInput) };
      setSaved(
        meal
          ? await bodyApi.editMeal(meal.id, body)
          : await bodyApi.logMeal({ ...body, ...(day ? { eaten_at: new Date(`${day}T12:00:00`).toISOString() } : {}) }),
      );
    }, "Couldn't save the meal");
  }

  if (saved) {
    return (
      <Sheet title="Saved" onClose={onClose} footer={<Button variant="primary" full onClick={onClose}>Done</Button>}>
        <p role="status">
          {slotLabel(saved.meal)} saved{saved.totals ? `: ${kcalRange(saved.totals)}.` : "."}
        </p>
      </Sheet>
    );
  }

  return (
    <Sheet
      title={meal ? "Edit meal" : "Log food"}
      as="form"
      onSubmit={save}
      onClose={onClose}
      footer={
        <Button variant="primary" full type="submit" disabled={busy || items.length === 0}>
          Save meal
        </Button>
      }
    >
      <div className="health-stack">
        <ChipGroup role="radiogroup" aria-label="Meal">
          {SLOTS.map((s) => (
            <Chip key={s.value} pressed={slot === s.value} role="radio" aria-checked={slot === s.value} onClick={() => setSlot(s.value)}>
              {s.label}
            </Chip>
          ))}
        </ChipGroup>
        {items.length > 0 && (
          <RowList aria-label="Foods in this meal">
            {items.map((i, idx) => (
              <Row
                key={`${i.food_id}-${idx}`}
                title={i.name}
                sub={[i.label, i.cooking && cookingLabel(i.cooking)].filter(Boolean).join(" · ")}
                actions={
                  <Button size="sm" variant="text" aria-label={`Remove ${i.name}`} onClick={() => setItems(items.filter((_, j) => j !== idx))}>
                    Remove
                  </Button>
                }
              />
            ))}
          </RowList>
        )}
        {adding ? (
          <FoodPicker
            onAdd={(item) => {
              setItems([...items, item]);
              setAdding(false);
            }}
            onCancel={items.length > 0 ? () => setAdding(false) : undefined}
          />
        ) : (
          <Button onClick={() => setAdding(true)}>Add a food</Button>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {meal &&
          (confirming ? (
            <ConfirmBox
              label="Delete meal"
              question="Delete this meal?"
              confirm="Delete meal"
              busy={busy}
              onConfirm={() =>
                void run(async () => {
                  await bodyApi.deleteMeal(meal.id);
                  onDeleted?.(meal);
                  onClose();
                }, "Couldn't delete the meal")
              }
              onKeep={() => setConfirming(false)}
            />
          ) : (
            <Button variant="danger" onClick={() => setConfirming(true)}>
              Delete meal
            </Button>
          ))}
      </div>
    </Sheet>
  );
}
