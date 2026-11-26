import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button, Figure, Row, RowList, Section } from "../components/ui";
import { formatDate, formatShortDate, shiftDay } from "../format";
import { healthApi, healthKey, type WorkoutDetail } from "./api";
import { byDone, formatDuration, formatSet, formatVolume, volumeKg } from "./format";
import { HealthGate } from "./HealthGate";
import { useExerciseMap } from "./hooks";
import { ProgressChart } from "./ProgressChart";
import { VolumeView } from "./VolumeView";
import { WorkoutDetailSheet } from "./WorkoutDetailSheet";

const WINDOW_DAYS = 90;

function Progress({ ids, names }: { ids: string[]; names: ReturnType<typeof useExerciseMap> }) {
  const [chosen, setChosen] = useState("");
  const id = chosen || ids[0] || "";
  const progress = useQuery({
    queryKey: [...healthKey.all, "progress", id],
    queryFn: () => healthApi.progress(id),
    enabled: !!id,
  });
  const points = progress.data ?? [];
  const best = points.reduce<(typeof points)[number] | null>((b, p) => (!b || Number(p.e1rm_kg) > Number(b.e1rm_kg) ? p : b), null);
  const name = names.get(id)?.name ?? "Exercise";
  return (
    <Section id="progress" title="Progress">
      {ids.length === 0 ? (
        <p className="muted">Finish a workout to see how each exercise is going.</p>
      ) : (
        <>
          <label className="field">
            Exercise
            <select className="input" value={id} onChange={(e) => setChosen(e.target.value)}>
              {ids.map((i) => (
                <option key={i} value={i}>
                  {names.get(i)?.name ?? "Exercise"}
                </option>
              ))}
            </select>
          </label>
          {progress.isError ? (
            <LoadError message="Couldn't load the progress." query={progress} />
          ) : !progress.data ? (
            <p className="state">Loading…</p>
          ) : points.length === 0 ? (
            <p className="muted">No sets with a weight and reps yet.</p>
          ) : (
            <>
              {best && (
                <div className="mini-tiles health-tiles">
                  <Figure size="sm" label="Best set" value={formatSet({ weight: best.weight, unit: best.unit, reps: best.reps, seconds: null })} extra={formatDate(best.at)} />
                  <Figure size="sm" label="Estimated max" value={`${Math.round(Number(best.e1rm_kg))} kg`} />
                </div>
              )}
              <ProgressChart points={points} name={name} />
              <RowList aria-label={`${name} workouts`}>
                {[...points].reverse().slice(0, 8).map((p) => (
                  <Row
                    key={p.workout_id}
                    title={formatShortDate(p.at)}
                    sub={`Estimated max ${Math.round(Number(p.e1rm_kg))} kg`}
                    trailing={<span className="health-fig">{formatSet({ weight: p.weight, unit: p.unit, reps: p.reps, seconds: null })}</span>}
                  />
                ))}
              </RowList>
            </>
          )}
        </>
      )}
    </Section>
  );
}

export function HealthHistory() {
  const [days, setDays] = useState(WINDOW_DAYS);
  const [open, setOpen] = useState<WorkoutDetail | null>(null);
  const start = shiftDay(new Date().toISOString().slice(0, 10), -days);
  const workouts = useQuery({ queryKey: [...healthKey.all, "workouts", start], queryFn: () => healthApi.workouts({ start }) });
  const done = useMemo(() => (workouts.data ?? []).filter((w) => w.finished_at), [workouts.data]);
  const ids = useMemo(() => [...new Set(done.flatMap((w) => byDone(w.sets).map((s) => s.exercise_id)))], [done]);
  const names = useExerciseMap(ids);
  return (
    <HealthGate>
      <div className="page-head">
        <div>
          <h1>History</h1>
          <p className="muted">What you did, and how it is going.</p>
        </div>
      </div>
      <Section id="workouts" title="Workouts">
        {workouts.isError ? (
          <LoadError message="Couldn't load your workouts." query={workouts} />
        ) : workouts.isLoading ? (
          <p className="state">Loading…</p>
        ) : done.length === 0 ? (
          <p className="muted">No workouts in the last {days} days.</p>
        ) : (
          <RowList aria-label="Past workouts">
            {done.map((w) => {
              const seconds = Math.round((Date.parse(w.finished_at!) - Date.parse(w.started_at)) / 1000);
              const first = [...new Set(byDone(w.sets).map((s) => names.get(s.exercise_id)?.name))].filter(Boolean).slice(0, 3).join(", ");
              return (
                <Row
                  key={w.id}
                  title={formatDate(w.started_at)}
                  sub={[`${w.sets.length} sets`, formatDuration(seconds), first].filter(Boolean).join(" · ")}
                  trailing={<span className="health-fig">{formatVolume(volumeKg(w.sets))}</span>}
                  label={`Open the workout of ${formatDate(w.started_at)}`}
                  onClick={() => setOpen(w)}
                />
              );
            })}
          </RowList>
        )}
        {!workouts.isLoading && (
          <Button variant="text" onClick={() => setDays((d) => d + WINDOW_DAYS)}>
            Show earlier
          </Button>
        )}
      </Section>
      <Progress ids={ids} names={names} />
      <VolumeView />
      {open && <WorkoutDetailSheet workout={open} names={names} onClose={() => setOpen(null)} />}
    </HealthGate>
  );
}
