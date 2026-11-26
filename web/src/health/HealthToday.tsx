import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { LoadError } from "../components/LoadError";
import { Button, Row, RowList, Section } from "../components/ui";
import { healthApi, healthKey, type Routine } from "./api";
import { HealthGate } from "./HealthGate";
import { exerciseName, useExerciseMap } from "./hooks";
import { WorkoutScreen } from "./WorkoutScreen";

function slotLine(s: Routine["slots"][number]): string {
  const work = s.seconds !== null && s.reps === null ? `${s.sets} × ${s.seconds} s` : `${s.sets} × ${s.reps ?? "?"}`;
  return `${work} · rest ${s.rest_seconds} s`;
}

function Idle({ routine }: { routine: Routine | null }) {
  const client = useQueryClient();
  const names = useExerciseMap(routine?.slots.map((s) => s.exercise_id) ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(routineId: string | null) {
    setBusy(true);
    setError(null);
    try {
      await healthApi.startWorkout(routineId);
      await client.invalidateQueries({ queryKey: healthKey.all });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the workout");
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Workout</h1>
          <p className="muted">Your workout for today.</p>
        </div>
      </div>
      <Section id="today-routine" title={routine ? routine.name : "Today"}>
        {routine ? (
          <>
            <RowList aria-label={`${routine.name} exercises`}>
              {routine.slots.map((s, i) => (
                <Row key={`${s.exercise_id}-${i}`} title={exerciseName(names, s.exercise_id)} sub={slotLine(s)} />
              ))}
            </RowList>
            <div className="health-actions">
              <Button variant="primary" full disabled={busy} onClick={() => void start(routine.id)}>
                Start {routine.name}
              </Button>
            </div>
          </>
        ) : (
          <p className="muted">
            Nothing planned for today. <Link to="/health/gym/routines">Set up your routines</Link> or start without one.
          </p>
        )}
        <div className="health-actions">
          <Button variant={routine ? "text" : "primary"} full={!routine} disabled={busy} onClick={() => void start(null)}>
            Start an empty workout
          </Button>
        </div>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </Section>
    </>
  );
}

/** A workout that is open is resumed here; otherwise today's routine from the plan, or an empty workout. */
function TodayBody() {
  const today = useQuery({ queryKey: [...healthKey.all, "today"], queryFn: healthApi.today });
  const open = today.data?.in_progress ?? null;
  const detail = useQuery({
    queryKey: [...healthKey.all, "workout", open?.id],
    queryFn: () => healthApi.workout(open!.id),
    enabled: !!open,
  });
  if (today.isError) return <LoadError variant="page" message="Couldn't load today." query={today} />;
  if (today.isLoading) return <p className="state">Loading…</p>;
  if (open) {
    if (detail.isError) return <LoadError variant="page" message="Couldn't load your workout." query={detail} />;
    if (!detail.data) return <p className="state">Loading…</p>;
    return <WorkoutScreen workout={detail.data} />;
  }
  return <Idle routine={today.data?.routine ?? null} />;
}

export function HealthToday() {
  return (
    <HealthGate>
      <TodayBody />
    </HealthGate>
  );
}
