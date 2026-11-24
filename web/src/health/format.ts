import type { SetEntry, WeightUnit } from "./api";

/** A decimal string without trailing zeros: "85.00" is "85", "82.50" is "82.5". Anything else is left as it is. */
export function trimDecimal(value: string): string {
  if (!/^-?\d+(\.\d+)?$/.test(value)) return value;
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

/** "85 kg", "82.5 lb"; the figure is the tabular one (callers set it in `.health-fig`). */
export function formatWeight(weight: string | null, unit: WeightUnit = "kg"): string {
  return weight === null ? "Bodyweight" : `${trimDecimal(weight)} ${unit}`;
}

/** "85 kg × 5", "Bodyweight × 12" or "45 s". */
export function formatSet(s: Pick<SetEntry, "weight" | "unit" | "reps" | "seconds">): string {
  if (s.reps === null && s.seconds !== null) return `${s.weight ? `${formatWeight(s.weight, s.unit)} · ` : ""}${s.seconds} s`;
  return `${formatWeight(s.weight, s.unit)} × ${s.reps ?? 0}`;
}

const KG_PER_LB = 0.45359237;
export const toKg = (weight: number, unit: WeightUnit) => (unit === "lb" ? weight * KG_PER_LB : weight);

/** Epley, as the backend does it: one rep is the weight itself; none outside 1 to 12 reps. */
export function e1rm(weightKg: number, reps: number): number | null {
  if (!(weightKg > 0) || reps < 1 || reps > 12) return null;
  return reps === 1 ? weightKg : weightKg * (1 + reps / 30);
}

/** Volume of the working sets, in kg. */
export function volumeKg(sets: readonly SetEntry[]): number {
  return sets.reduce(
    (sum, s) => (s.kind === "working" && s.weight !== null && s.reps !== null ? sum + toKg(Number(s.weight), s.unit) * s.reps : sum),
    0,
  );
}

/** "1,240 kg" for a volume. */
export function formatVolume(kg: number | string): string {
  const n = typeof kg === "string" ? Number(kg) : kg;
  return `${Math.round(n).toLocaleString("en-US")} kg`;
}

/** "52 min", "1 h 05 min", "40 s". */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

/** "1:30" for a rest timer. */
export function formatClockSeconds(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const PR_WORDS = { heaviest_weight: "Heaviest weight", best_e1rm: "Best estimated max", most_reps: "Most reps" } as const;

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

/** The sets of one exercise in the order they were done. */
export function byDone(sets: readonly SetEntry[]): SetEntry[] {
  return [...sets].sort((a, b) => a.done_at.localeCompare(b.done_at) || a.position - b.position);
}
