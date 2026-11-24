import { useState } from "react";

import { Button, Row } from "../components/ui";
import type { SetEntry, SetInput, WeightUnit } from "./api";
import { formatSet, trimDecimal } from "./format";

export type Draft = { weight: string; reps: string; seconds: string; rpe: string };

export const draftOf = (s: Pick<SetEntry, "weight" | "reps" | "seconds" | "rpe">): Draft => ({
  weight: s.weight === null ? "" : trimDecimal(s.weight),
  reps: s.reps === null ? "" : String(s.reps),
  seconds: s.seconds === null ? "" : String(s.seconds),
  rpe: s.rpe === null ? "" : trimDecimal(s.rpe),
});

/** The API's set from what is typed: empty weight is bodyweight, empty RPE is none. Null when it is not a set yet. */
export function inputOf(d: Draft, timed: boolean): Omit<SetInput, "exercise_id" | "unit"> | string {
  const weight = d.weight.trim().replace(",", ".");
  if (weight !== "" && !Number.isFinite(Number(weight))) return "That weight isn't a number.";
  const rpe = d.rpe.trim().replace(",", ".");
  if (rpe !== "" && !Number.isFinite(Number(rpe))) return "That RPE isn't a number.";
  const count = Number(timed ? d.seconds : d.reps);
  if (!Number.isInteger(count) || count < 1) return timed ? "Enter the seconds." : "Enter the reps.";
  return {
    weight: weight === "" ? null : weight,
    reps: timed ? null : count,
    seconds: timed ? count : null,
    rpe: rpe === "" ? null : rpe,
  };
}

const same = (a: Draft, b: Draft) => a.weight === b.weight && a.reps === b.reps && a.seconds === b.seconds && a.rpe === b.rpe;

/** One set: its weight, reps (or seconds) and an optional RPE, typed in place; Log completes it, and a logged set
 * that is changed offers Save. */
export function SetRow({
  number,
  exercise,
  unit,
  timed,
  logged,
  initial,
  hint,
  best,
  onLog,
  onSave,
}: {
  number: number;
  exercise: string;
  unit: WeightUnit;
  timed: boolean;
  logged: SetEntry | null;
  initial: Draft;
  /** What it was last time, under the title. */
  hint: string | null;
  /** "New best: 85 kg × 5", plain text, for a set that beat what was done before. */
  best: string | null;
  onLog: (input: Omit<SetInput, "exercise_id">) => Promise<void>;
  onSave: (id: string, patch: Omit<SetInput, "exercise_id">) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = logged !== null && !same(draft, draftOf(logged));
  const field = (key: keyof Draft, label: string, mode: "decimal" | "numeric", extra = "") => (
    <label className="field">
      {label}
      <input
        className="input health-fig"
        inputMode={mode}
        aria-label={`${label}, set ${number} of ${exercise}`}
        value={draft[key]}
        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
        placeholder={extra}
      />
    </label>
  );

  async function submit() {
    const input = inputOf(draft, timed);
    if (typeof input === "string") return setError(input);
    setBusy(true);
    setError(null);
    try {
      if (logged) await onSave(logged.id, input);
      else await onLog({ ...input, unit });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that set");
    } finally {
      setBusy(false);
    }
  }

  const sub = logged ? (
    <>
      <span className="health-fig">{formatSet(logged)}</span>
      {best && <strong className="health-best"> · {best}</strong>}
    </>
  ) : (
    hint
  );
  return (
    <Row
      title={`Set ${number}`}
      sub={sub}
      className={logged ? "health-set is-done" : "health-set"}
    >
      <div className="health-fields">
        {field("weight", `Weight (${unit})`, "decimal", "0")}
        {timed ? field("seconds", "Seconds", "numeric") : field("reps", "Reps", "numeric")}
        {field("rpe", "RPE (optional)", "decimal")}
      </div>
      <div className="health-set-action">
        {logged ? (
          dirty ? (
            <Button size="sm" disabled={busy} onClick={() => void submit()} aria-label={`Save set ${number} of ${exercise}`}>
              Save
            </Button>
          ) : (
            <span className="health-done">Done</span>
          )
        ) : (
          <Button size="sm" variant="primary" disabled={busy} onClick={() => void submit()} aria-label={`Log set ${number} of ${exercise}`}>
            Log set
          </Button>
        )}
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Row>
  );
}
