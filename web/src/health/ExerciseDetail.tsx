import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Sheet } from "../components/Sheet";
import { Button, Row, RowList } from "../components/ui";
import { type Exercise, healthApi, healthKey, type Slot } from "./api";
import { BodyMap } from "./body/BodyMap";
import { useRoutines } from "./hooks";

const NEW_SLOT = { sets: 3, reps: 10, seconds: null, rest_seconds: 90, note: null } as const;
export const slotFor = (exercise_id: string): Slot => ({ exercise_id, ...NEW_SLOT });

/** Where "Add to routine" goes: a routine of theirs, or a new one. A second view inside the sheet. */
function AddToRoutine({ exercise, onDone }: { exercise: Exercise; onDone: (message: string) => void }) {
  const client = useQueryClient();
  const routines = useRoutines();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(job: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError(null);
    try {
      await job();
      await client.invalidateQueries({ queryKey: [...healthKey.all, "routines"] });
      onDone(message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add it");
      setBusy(false);
    }
  }

  return (
    <div className="health-stack">
      {routines.data && routines.data.length > 0 && (
        <RowList aria-label="Your routines">
          {routines.data.map((r) => (
            <Row
              key={r.id}
              title={r.name}
              sub={`${r.slots.length} ${r.slots.length === 1 ? "exercise" : "exercises"}`}
              label={`Add ${exercise.name} to ${r.name}`}
              onClick={() =>
                busy
                  ? undefined
                  : void run(
                      () => healthApi.saveRoutine(r.id, { name: r.name, slots: [...r.slots, slotFor(exercise.id)] }),
                      `Added ${exercise.name} to ${r.name}.`,
                    )
              }
            />
          ))}
        </RowList>
      )}
      {routines.data?.length === 0 && <p className="muted">You have no routines yet.</p>}
      <form
        className="health-inline"
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = name.trim();
          if (trimmed)
            void run(
              () => healthApi.createRoutine({ name: trimmed, slots: [slotFor(exercise.id)] }),
              `Made ${trimmed} with ${exercise.name}.`,
            );
        }}
      >
        <label className="field">
          New routine
          <input className="input" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </label>
        <Button variant="primary" type="submit" disabled={busy || !name.trim()}>
          Make routine
        </Button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** An exercise in a sheet: photos, the steps, the muscles on a body map, and Add to routine. */
export function ExerciseDetail({ exercise, onClose, onAdded }: { exercise: Exercise; onClose: () => void; onAdded: (message: string) => void }) {
  const [adding, setAdding] = useState(false);
  const facts = [exercise.equipment, exercise.level, exercise.category, exercise.mechanic, exercise.force].filter(Boolean).join(" · ");
  return (
    <Sheet
      title={adding ? "Add to routine" : exercise.name}
      onClose={onClose}
      onBack={adding ? () => setAdding(false) : undefined}
      initialFocus={adding ? undefined : "dialog"}
      footer={
        adding ? undefined : (
          <Button variant="primary" full onClick={() => setAdding(true)}>
            Add to routine
          </Button>
        )
      }
    >
      {adding ? (
        <AddToRoutine exercise={exercise} onDone={(m) => { onAdded(m); onClose(); }} />
      ) : (
        <div className="health-stack">
          {facts && <p className="muted">{facts}</p>}
          {exercise.images.length > 0 && (
            <div className="health-photos">
              {exercise.images.map((src, i) => (
                <img key={src} src={src} loading="lazy" alt={`${exercise.name}, step ${i + 1} of ${exercise.images.length}`} />
              ))}
            </div>
          )}
          <div className="health-body-map">
            <BodyMap view="both" primary={exercise.primary_muscles} secondary={exercise.secondary_muscles} />
          </div>
          {exercise.instructions.length > 0 && (
            <ol className="health-steps" aria-label="Steps">
              {exercise.instructions.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Sheet>
  );
}
