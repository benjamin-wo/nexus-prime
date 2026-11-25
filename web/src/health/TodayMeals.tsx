import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { LoadError } from "../components/LoadError";
import { Toast } from "../components/Toast";
import { Button, Row, RowList, Section } from "../components/ui";
import { healthKey } from "./api";
import { bodyApi, type Meal } from "./bodyApi";
import { gramsRange, kcalRange, slotLabel } from "./bodyFormat";
import { useDay } from "./bodyHooks";
import { foodsLine, hasEstimate, restore } from "./mealRestore";
import { MealSheet } from "./MealSheet";
import { CheckIn } from "./SafetyNotes";
import { TodayDayLine } from "./TodayDayLine";

/** "about 600 kcal · about 30 g protein", and "rough guide" for an estimate. Nothing in numbers-free mode. */
function figures(m: Meal): string | undefined {
  const parts = [m.totals && kcalRange(m.totals), m.totals && `${gramsRange(m.totals, "protein_g")} protein`, hasEstimate(m) ? "rough guide" : null];
  const line = parts.filter(Boolean).join(" · ");
  return line || undefined;
}

/** Meals today, the day's line, and the edit sheet (opened by a tap or by `?meal=<id>`). Delete has Undo. */
export function TodayMeals() {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const day = useDay(null);
  const [sheet, setSheet] = useState<Meal | "new" | null>(null);
  const [removed, setRemoved] = useState<Meal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeToast = useCallback(() => setRemoved(null), []);
  const wanted = params.get("meal");
  const d = day.data;

  useEffect(() => {
    const found = wanted ? d?.meals.find((m) => m.id === wanted) : undefined;
    if (found) setSheet(found);
  }, [wanted, d]);

  function close() {
    setSheet(null);
    if (wanted) {
      params.delete("meal");
      setParams(params, { replace: true });
    }
  }

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
      <Section
        id="home-food"
        title="Today's food"
        action={
          <Button variant="text" onClick={() => setSheet("new")}>
            Add food
          </Button>
        }
      >
        {day.isError ? (
          <LoadError message="Couldn't load today's food." query={day} />
        ) : !d ? (
          <p className="state">Loading…</p>
        ) : d.meals.length === 0 ? (
          <p className="muted">Nothing logged yet.</p>
        ) : (
          <>
            <RowList aria-label="Meals today">
              {d.meals.map((m) => (
                <Row key={m.id} title={`${slotLabel(m.meal)} · ${foodsLine(m)}`} sub={figures(m)} label={`Open ${slotLabel(m.meal)}`} onClick={() => setSheet(m)} />
              ))}
            </RowList>
            <TodayDayLine day={d} />
          </>
        )}
      </Section>
      {d && <CheckIn safety={d.safety} day={d.date} />}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {sheet && <MealSheet meal={sheet === "new" ? undefined : sheet} day={null} onClose={close} onDeleted={setRemoved} />}
      {removed && <Toast message="Meal deleted." action={{ label: "Undo", run: () => void undo() }} onClose={closeToast} />}
    </>
  );
}
