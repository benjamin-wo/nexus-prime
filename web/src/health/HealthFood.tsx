import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { LoadError } from "../components/LoadError";
import { Toast } from "../components/Toast";
import { Button, Section } from "../components/ui";
import { dayHeading, shiftDay } from "../format";
import { healthKey } from "./api";
import { bodyApi, type Meal } from "./bodyApi";
import { localToday } from "./bodyFormat";
import { useDay } from "./bodyHooks";
import { DayTotals } from "./DayTotals";
import { HealthGate } from "./HealthGate";
import { MealList } from "./MealList";
import { MealSheet } from "./MealSheet";
import { CheckIn } from "./SafetyNotes";

/** What a deleted meal needs to be put back as it was. */
const restore = (m: Meal) => ({
  meal: m.meal,
  eaten_at: m.eaten_at,
  ...(m.note ? { note: m.note } : {}),
  items: m.items.map((i) => ({ food_id: i.food_id, grams: i.grams, label: i.label, kind: i.kind, cooking: i.cooking, note: i.note })),
});

function FoodBody() {
  const client = useQueryClient();
  const [date, setDate] = useState<string | null>(null); // null is today
  const [sheet, setSheet] = useState<Meal | "new" | null>(null);
  const [removed, setRemoved] = useState<Meal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const day = useDay(date);
  const closeToast = useCallback(() => setRemoved(null), []);
  const today = localToday();
  const shown = day.data?.date ?? date ?? today;
  const go = (by: number) => {
    const next = shiftDay(shown, by);
    setDate(next >= today ? null : next);
  };

  async function undo() {
    if (!removed) return;
    const gone = removed;
    setRemoved(null);
    try {
      await bodyApi.logMeal(restore(gone));
      await client.invalidateQueries({ queryKey: healthKey.all });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't put the meal back");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Food</h1>
          <p className="muted">What you ate, as ranges.</p>
        </div>
        <Button variant="primary" onClick={() => setSheet("new")}>
          Log food
        </Button>
      </div>
      <div className="health-daynav" role="group" aria-label="Day">
        <Button variant="text" aria-label="Previous day" onClick={() => go(-1)}>
          ‹
        </Button>
        <h2 className="health-daynav-title" aria-live="polite">
          {dayHeading(shown, today)}
        </h2>
        <Button variant="text" aria-label="Next day" disabled={date === null} onClick={() => go(1)}>
          ›
        </Button>
      </div>
      {day.isError ? (
        <LoadError variant="page" message="Couldn't load this day." query={day} />
      ) : !day.data ? (
        <p className="state">Loading…</p>
      ) : (
        <>
          <Section id="meals" title="Meals">
            {day.data.meals.length === 0 ? <p className="muted">Nothing logged for this day.</p> : <MealList meals={day.data.meals} onOpen={setSheet} />}
          </Section>
          <DayTotals day={day.data} />
          <CheckIn safety={day.data.safety} day={day.data.date} />
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {sheet && <MealSheet meal={sheet === "new" ? undefined : sheet} day={date} onClose={() => setSheet(null)} onDeleted={setRemoved} />}
      {removed && <Toast message="Meal deleted." action={{ label: "Undo", run: () => void undo() }} onClose={closeToast} />}
    </>
  );
}

export function HealthFood() {
  return (
    <HealthGate>
      <FoodBody />
    </HealthGate>
  );
}
