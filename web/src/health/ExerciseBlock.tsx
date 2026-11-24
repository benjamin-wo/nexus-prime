import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, RowList, Section } from "../components/ui";
import { healthApi, healthKey, type SetEntry, type SetInput, type Slot } from "./api";
import { byDone, formatSet } from "./format";
import { draftOf, SetRow } from "./SetRow";

const DEFAULT_SETS = 3;
const DEFAULT_REST = 90;
export const restFor = (slot: Slot | undefined) => slot?.rest_seconds ?? DEFAULT_REST;

/** One exercise of the workout: its sets in order, prefilled from the last time (the backend's `last` sets), and a
 * way to add one more. The sets are the workout's own; a row is logged when the workout has a set for its place. */
export function ExerciseBlock({
  id,
  name,
  slot,
  sets,
  bests,
  onLog,
  onSave,
}: {
  id: string;
  name: string;
  slot?: Slot;
  /** This exercise's sets in this workout. */
  sets: SetEntry[];
  /** "New best" lines by set id. */
  bests: Record<string, string>;
  onLog: (exerciseId: string, input: Omit<SetInput, "exercise_id">, rest: number) => Promise<void>;
  onSave: (setId: string, patch: Omit<SetInput, "exercise_id">) => Promise<void>;
}) {
  const last = useQuery({
    queryKey: [...healthKey.all, "last", id],
    queryFn: () => healthApi.lastSets(id),
    staleTime: 60_000,
  });
  const [extra, setExtra] = useState(0);
  const done = byDone(sets);
  const before = (last.data ?? []).filter((s) => s.kind === "working");
  const planned = slot?.sets ?? (before.length || DEFAULT_SETS);
  const total = Math.max(planned + extra, done.length);
  const timed = slot ? slot.seconds !== null && slot.reps === null : before.length > 0 && before[0].reps === null && before[0].seconds !== null;
  const unit = done[0]?.unit ?? before[0]?.unit ?? "kg";

  const rows = Array.from({ length: total }, (_, i) => {
    const logged = done[i] ?? null;
    const ref = before[i] ?? before[before.length - 1];
    const initial = logged
      ? draftOf(logged)
      : ref
        ? draftOf(ref)
        : { weight: "", reps: slot?.reps ? String(slot.reps) : "", seconds: slot?.seconds ? String(slot.seconds) : "", rpe: "" };
    return { i, logged, initial, hint: before[i] ? `Last time ${formatSet(before[i])}` : null };
  });

  // A row's draft is state of the row, set once from `initial`, so the prefill waits for the last sets to arrive.
  if (last.isLoading) return <Section id={`ex-${id}`} title={name}><p className="state">Loading…</p></Section>;
  return (
    <Section
      id={`ex-${id}`}
      title={name}
      action={
        <Button variant="text" onClick={() => setExtra((n) => n + 1)} aria-label={`Add a set to ${name}`}>
          Add set
        </Button>
      }
    >
      <RowList aria-label={`${name} sets`}>
        {rows.map((r) => (
          <SetRow
            key={r.i}
            number={r.i + 1}
            exercise={name}
            unit={unit}
            timed={timed}
            logged={r.logged}
            initial={r.initial}
            hint={r.hint}
            best={r.logged ? (bests[r.logged.id] ?? null) : null}
            onLog={(input) => onLog(id, input, restFor(slot))}
            onSave={onSave}
          />
        ))}
      </RowList>
    </Section>
  );
}
