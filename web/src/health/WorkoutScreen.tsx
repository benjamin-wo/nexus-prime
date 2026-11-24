import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import { ConfirmBox } from "../components/ConfirmBox";
import { Sheet } from "../components/Sheet";
import { Toast } from "../components/Toast";
import { Button } from "../components/ui";
import { nativeHaptic } from "../native";
import { healthApi, healthKey, type SetEntry, type SetInput, type Slot, type Summary, type WorkoutDetail } from "./api";
import { ExerciseBlock } from "./ExerciseBlock";
import { ExerciseSearch } from "./ExerciseSearch";
import { FinishSheet } from "./FinishSheet";
import { e1rm, formatDuration, formatSet, toKg } from "./format";
import { exerciseName, useExerciseMap } from "./hooks";
import { RestTimer } from "./RestTimer";

type Toasted = { message: string; undo?: boolean };

/** The workout that is open: its exercises in order with their sets, the rest timer, undo, and Finish. */
export function WorkoutScreen({ workout }: { workout: WorkoutDetail }) {
  const client = useQueryClient();
  const routine = useQuery({
    queryKey: [...healthKey.all, "routine", workout.routine_id],
    queryFn: () => healthApi.routine(workout.routine_id as string),
    enabled: !!workout.routine_id,
  });
  const [added, setAdded] = useState<string[]>([]);
  const [picking, setPicking] = useState(false);
  const [rest, setRest] = useState<{ seconds: number; run: number } | null>(null);
  const [toast, setToast] = useState<Toasted | null>(null);
  const [bests, setBests] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<Summary | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const closeToast = useCallback(() => setToast(null), []);

  // The exercises: the routine's, then any that have sets, then the ones added by hand.
  const slots = routine.data?.slots ?? [];
  const order = useMemo(() => {
    const ids = [...slots.map((s) => s.exercise_id), ...workout.sets.map((s) => s.exercise_id), ...added];
    return [...new Set(ids)];
  }, [slots, workout.sets, added]);
  const names = useExerciseMap(order);
  const slotOf = (id: string): Slot | undefined => {
    const mine = slots.filter((s) => s.exercise_id === id);
    return mine.length ? { ...mine[0], sets: mine.reduce((n, s) => n + s.sets, 0) } : undefined;
  };
  const refresh = () => client.invalidateQueries({ queryKey: [...healthKey.all, "workout", workout.id] });

  async function newBest(set: SetEntry) {
    // Only a working set with a weight and 1 to 12 reps has an estimated max; the best of earlier workouts is the bar.
    if (set.kind !== "working" || set.weight === null || set.reps === null) return null;
    const mine = e1rm(toKg(Number(set.weight), set.unit), set.reps);
    if (mine === null) return null;
    const points = await client.fetchQuery({
      queryKey: [...healthKey.all, "progress", set.exercise_id],
      queryFn: () => healthApi.progress(set.exercise_id),
      staleTime: 5 * 60_000,
    });
    const before = points.filter((p) => p.workout_id !== workout.id).map((p) => Number(p.e1rm_kg));
    if (before.length === 0 || mine <= Math.max(...before)) return null;
    return `New best: ${formatSet({ weight: set.weight, unit: set.unit, reps: set.reps, seconds: null })}`;
  }

  async function log(exerciseId: string, input: Omit<SetInput, "exercise_id">, restSeconds: number) {
    const set = await healthApi.logSet(workout.id, { ...input, exercise_id: exerciseId });
    const best = await newBest(set).catch(() => null);
    if (best) setBests((b) => ({ ...b, [set.id]: best }));
    await refresh();
    setRest({ seconds: restSeconds, run: Date.now() });
    nativeHaptic("success");
    setToast({ message: `Logged ${formatSet(set)}.`, undo: true });
  }

  async function save(setId: string, patch: Omit<SetInput, "exercise_id">) {
    await healthApi.editSet(setId, patch);
    await refresh();
  }

  async function undo() {
    setToast(null);
    try {
      const removed = await healthApi.undoSet(workout.id);
      setRest(null);
      await refresh();
      setToast({ message: `Removed ${formatSet(removed)}.` });
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "Couldn't undo that" });
    }
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      setSummary(await healthApi.finishWorkout(workout.id));
      setRest(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't finish the workout");
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    setBusy(true);
    try {
      await healthApi.discardWorkout(workout.id);
      await client.invalidateQueries({ queryKey: healthKey.all });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't discard the workout");
      setBusy(false);
    }
  }

  const doneSets = workout.sets.length;
  const started = Math.max(0, Math.round((Date.now() - new Date(workout.started_at).getTime()) / 1000));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{routine.data?.name ?? "Workout"}</h1>
          <p className="muted">
            {started < 60 ? "Just started" : `Started ${formatDuration(started)} ago`} · {doneSets} {doneSets === 1 ? "set" : "sets"} logged
          </p>
        </div>
        <div className="quick">
          <Button onClick={() => setPicking(true)}>Add exercise</Button>
          {doneSets > 0 && <Button onClick={() => void undo()}>Undo last set</Button>}
          <Button variant="primary" disabled={busy} onClick={() => void finish()}>
            Finish workout
          </Button>
        </div>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {rest && (
        <div className="health-rest-dock">
          <RestTimer seconds={rest.seconds} run={rest.run} onSkip={() => setRest(null)} />
        </div>
      )}
      {order.length === 0 && <p className="muted">An empty workout. Add the first exercise.</p>}
      {order.map((id) => (
        <ExerciseBlock
          key={id}
          id={id}
          name={exerciseName(names, id)}
          slot={slotOf(id)}
          sets={workout.sets.filter((s) => s.exercise_id === id)}
          bests={bests}
          onLog={log}
          onSave={save}
        />
      ))}
      {confirming ? (
        <ConfirmBox
          label="Discard workout"
          question="Discard this workout? Its sets are deleted."
          confirm="Discard workout"
          busy={busy}
          onConfirm={() => void discard()}
          onKeep={() => setConfirming(false)}
        />
      ) : (
        <div>
          <Button variant="danger" onClick={() => setConfirming(true)}>
            Discard workout
          </Button>
        </div>
      )}
      {picking && (
        <Sheet title="Add an exercise" onClose={() => setPicking(false)}>
          <ExerciseSearch
            onPick={(e) => {
              setAdded((a) => [...a, e.id]);
              setPicking(false);
            }}
          />
        </Sheet>
      )}
      {toast && (
        <Toast message={toast.message} action={toast.undo ? { label: "Undo", run: () => void undo() } : undefined} onClose={closeToast} />
      )}
      {summary && (
        <FinishSheet
          summary={summary}
          names={names}
          onClose={() => {
            setSummary(null);
            void client.invalidateQueries({ queryKey: healthKey.all });
          }}
        />
      )}
    </>
  );
}
