import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ConfirmBox } from "../components/ConfirmBox";
import { Sheet } from "../components/Sheet";
import { Button, Row, RowList } from "../components/ui";
import { type Routine, healthApi, healthKey, type Slot } from "./api";
import { slotFor } from "./ExerciseDetail";
import { ExerciseSearch } from "./ExerciseSearch";
import { exerciseName, useExerciseMap } from "./hooks";

const num = (v: string): number | null => (v.trim() === "" ? null : Math.max(0, Math.floor(Number(v))));

/** Moves item `i` by `by` places; out of range changes nothing. */
export function move<T>(items: readonly T[], i: number, by: number): T[] {
  const j = i + by;
  if (j < 0 || j >= items.length) return [...items];
  const next = [...items];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

function SlotFields({ slot, name, onChange }: { slot: Slot; name: string; onChange: (s: Slot) => void }) {
  const timed = slot.seconds !== null && slot.reps === null;
  return (
    <div className="health-fields">
      <label className="field">
        Sets
        <input
          className="input"
          inputMode="numeric"
          aria-label={`Sets, ${name}`}
          value={slot.sets || ""}
          onChange={(e) => onChange({ ...slot, sets: num(e.target.value) ?? 0 })}
        />
      </label>
      <label className="field">
        {timed ? "Seconds" : "Reps"}
        <input
          className="input"
          inputMode="numeric"
          aria-label={`${timed ? "Seconds" : "Reps"}, ${name}`}
          value={(timed ? slot.seconds : slot.reps) ?? ""}
          onChange={(e) => {
            const n = num(e.target.value);
            onChange(timed ? { ...slot, seconds: n } : { ...slot, reps: n });
          }}
        />
      </label>
      <label className="field">
        Rest (s)
        <input
          className="input"
          inputMode="numeric"
          aria-label={`Rest in seconds, ${name}`}
          value={slot.rest_seconds}
          onChange={(e) => onChange({ ...slot, rest_seconds: num(e.target.value) ?? 0 })}
        />
      </label>
      <Button
        variant="text"
        size="sm"
        onClick={() => onChange(timed ? { ...slot, reps: 10, seconds: null } : { ...slot, reps: null, seconds: 30 })}
      >
        {timed ? "Count reps instead" : "Time it instead"}
      </Button>
    </div>
  );
}

/** A routine in a sheet: its name and its slots (exercise, sets, reps or time, rest), reordered with up and down. */
export function RoutineEditor({ routine, onClose, onSaved }: { routine: Routine | null; onClose: () => void; onSaved: (message: string) => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(routine?.name ?? "");
  const [slots, setSlots] = useState<Slot[]>(routine?.slots ?? []);
  const [picking, setPicking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const names = useExerciseMap(slots.map((s) => s.exercise_id));

  async function run(job: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError(null);
    try {
      await job();
      await client.invalidateQueries({ queryKey: healthKey.all });
      onSaved(message);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
      setBusy(false);
    }
  }

  const save = () => {
    const body = { name: name.trim(), slots };
    return run(() => (routine ? healthApi.saveRoutine(routine.id, body) : healthApi.createRoutine(body)), `Saved ${body.name}.`);
  };
  const update = (i: number, slot: Slot) => setSlots((all) => all.map((s, j) => (j === i ? slot : s)));
  const valid = name.trim() !== "" && slots.every((s) => s.sets >= 1 && (s.reps ?? s.seconds ?? 0) >= 1);

  if (picking) {
    return (
      <Sheet title="Add an exercise" onBack={() => setPicking(false)} backLabel="Back to the routine" onClose={onClose}>
        <ExerciseSearch
          onPick={(e) => {
            setSlots((all) => [...all, slotFor(e.id)]);
            setPicking(false);
          }}
        />
      </Sheet>
    );
  }
  return (
    <Sheet
      as="form"
      title={routine ? "Edit routine" : "New routine"}
      onClose={onClose}
      onSubmit={(e) => {
        e.preventDefault();
        if (valid && !busy) void save();
      }}
      footer={
        <Button variant="primary" full type="submit" disabled={busy || !valid}>
          Save routine
        </Button>
      }
    >
      <div className="health-stack">
        <label className="field">
          Name
          <input className="input" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </label>
        {slots.length === 0 ? (
          <p className="muted">No exercises yet.</p>
        ) : (
          <RowList aria-label="Exercises in this routine">
            {slots.map((slot, i) => {
              const ex = exerciseName(names, slot.exercise_id);
              return (
                <Row
                  key={`${slot.exercise_id}-${i}`}
                  title={ex}
                  sub={`Exercise ${i + 1} of ${slots.length}`}
                  actions={
                    <>
                      <Button size="sm" variant="text" disabled={i === 0} aria-label={`Move ${ex} up`} onClick={() => setSlots((a) => move(a, i, -1))}>
                        Up
                      </Button>
                      <Button size="sm" variant="text" disabled={i === slots.length - 1} aria-label={`Move ${ex} down`} onClick={() => setSlots((a) => move(a, i, 1))}>
                        Down
                      </Button>
                      <Button size="sm" variant="danger" aria-label={`Remove ${ex}`} onClick={() => setSlots((a) => a.filter((_, j) => j !== i))}>
                        Remove
                      </Button>
                    </>
                  }
                >
                  <SlotFields slot={slot} name={ex} onChange={(s) => update(i, s)} />
                </Row>
              );
            })}
          </RowList>
        )}
        <div>
          <Button onClick={() => setPicking(true)}>Add exercise</Button>
        </div>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {routine &&
          (confirming ? (
            <ConfirmBox
              label="Delete routine"
              question={`Delete ${routine.name}? Workouts you did with it stay.`}
              confirm="Delete routine"
              busy={busy}
              onConfirm={() => void run(() => healthApi.deleteRoutine(routine.id), `Deleted ${routine.name}.`)}
              onKeep={() => setConfirming(false)}
            />
          ) : (
            <div>
              <Button variant="danger" onClick={() => setConfirming(true)}>
                Delete routine
              </Button>
            </div>
          ))}
      </div>
    </Sheet>
  );
}
