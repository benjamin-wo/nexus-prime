import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button, Row, RowList, Section } from "../components/ui";
import { healthApi, healthKey } from "./api";
import { inUnit, kcalRange, slotLabel } from "./bodyFormat";
import { useDay, useWeight, useWeightUnit } from "./bodyHooks";
import { HealthGate } from "./HealthGate";
import { MealSheet } from "./MealSheet";
import { CheckIn } from "./SafetyNotes";
import { WeightSheet } from "./WeightSheet";

function WorkoutStatus() {
  const today = useQuery({ queryKey: [...healthKey.all, "today"], queryFn: healthApi.today });
  if (today.isError) return <LoadError message="Couldn't load today's workout." query={today} />;
  if (!today.data) return <p className="state">Loading…</p>;
  const { in_progress: open, routine } = today.data;
  return (
    <RowList aria-label="Workout">
      <Row
        to="/health/gym"
        title={open ? "Workout in progress" : routine ? routine.name : "Nothing planned"}
        sub={open ? "Pick up where you left off" : routine ? `${routine.slots.length} ${routine.slots.length === 1 ? "exercise" : "exercises"}` : "Start an empty workout, or plan one"}
        trailing={open ? "Resume" : routine ? "Start" : undefined}
      />
    </RowList>
  );
}

function HomeBody() {
  const day = useDay(null);
  const weight = useWeight();
  const unit = useWeightUnit();
  const [sheet, setSheet] = useState<"food" | "weight" | null>(null);
  const d = day.data;
  const w = weight.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Health</h1>
        </div>
      </div>
      <Section id="home-workout" title="Workout">
        <WorkoutStatus />
      </Section>
      <Section
        id="home-food"
        title="Food so far"
        action={
          <Button variant="text" onClick={() => setSheet("food")}>
            Log food
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
          <RowList aria-label="Meals today">
            {d.meals.map((m) => (
              <Row key={m.id} title={slotLabel(m.meal)} sub={m.items.map((i) => i.name ?? "Food").join(", ")} trailing={m.totals ? <span className="health-fig">{kcalRange(m.totals)}</span> : undefined} />
            ))}
            {d.totals && !d.hidden && <Row title="So far" trailing={<span className="health-fig">{kcalRange(d.totals)}</span>} />}
          </RowList>
        )}
      </Section>
      <Section
        id="home-weight"
        title="Weight"
        action={
          <Button variant="text" onClick={() => setSheet("weight")}>
            Log weight
          </Button>
        }
      >
        {weight.isError ? (
          <LoadError message="Couldn't load your weight." query={weight} />
        ) : !w ? (
          <p className="state">Loading…</p>
        ) : (
          <RowList aria-label="Weight trend">
            <Row
              to="/health/weight"
              title={w.trend_words.charAt(0).toUpperCase() + w.trend_words.slice(1)}
              sub={w.hidden ? undefined : w.rate_text}
              trailing={!w.hidden && w.trend_kg ? <span className="health-fig">{`${inUnit(w.trend_kg, unit)} ${unit}`}</span> : undefined}
            />
          </RowList>
        )}
      </Section>
      {d && <CheckIn safety={d.safety} day={d.date} />}
      {sheet === "food" && <MealSheet day={null} onClose={() => setSheet(null)} />}
      {sheet === "weight" && <WeightSheet unit={unit} hidden={w?.hidden ?? false} onClose={() => setSheet(null)} />}
    </>
  );
}

export function HealthHome() {
  return (
    <HealthGate>
      <HomeBody />
    </HealthGate>
  );
}
