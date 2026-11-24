import { api } from "../api";
import type { Muscle } from "./body/muscles";

/** The Health department's API (`/api/health/...`). Weights come as decimal strings and go back the same way. */
export type WeightUnit = "kg" | "lb";
export type SetKind = "warmup" | "working";
export type PrKind = "heaviest_weight" | "best_e1rm" | "most_reps";

export const EQUIPMENT = [
  "bands", "barbell", "body only", "cable", "dumbbell", "e-z curl bar", "exercise ball", "foam roll",
  "kettlebells", "machine", "medicine ball", "other",
] as const;
export const LEVELS = ["beginner", "intermediate", "expert"] as const;

export type Exercise = {
  id: string;
  name: string;
  category: string;
  level: string;
  equipment: string | null;
  force: string | null;
  mechanic: string | null;
  primary_muscles: Muscle[];
  secondary_muscles: Muscle[];
  instructions: string[];
  images: string[];
};

export type ExerciseFilter = { text?: string; muscle?: string; equipment?: string; level?: string; limit?: number };

export type Slot = {
  exercise_id: string;
  sets: number;
  reps: number | null;
  seconds: number | null;
  rest_seconds: number;
  note: string | null;
};
export type Routine = { id: string; name: string; slots: Slot[]; created_at: string; updated_at: string };
export type RoutineInput = { name: string; slots: Slot[] };

export type Plan = { kind: "weekly" | "rotation"; weekly: Record<string, string>; rotation: string[] };
export type PlanInput = { kind: "weekly" | "rotation"; weekly: Record<number, string>; rotation: string[] };

export type Workout = {
  id: string;
  routine_id: string | null;
  started_at: string;
  finished_at: string | null;
  note: string | null;
};
export type SetEntry = {
  id: string;
  workout_id: string;
  exercise_id: string;
  position: number;
  kind: SetKind;
  reps: number | null;
  weight: string | null;
  unit: WeightUnit;
  seconds: number | null;
  rpe: string | null;
  done_at: string;
};
export type WorkoutDetail = Workout & { sets: SetEntry[] };
export type Today = { routine: Routine | null; in_progress: Workout | null };
export type SetInput = {
  exercise_id: string;
  kind?: SetKind;
  reps?: number | null;
  weight?: string | null;
  unit?: WeightUnit;
  seconds?: number | null;
  rpe?: string | null;
};
export type SetPatch = Partial<Omit<SetInput, "exercise_id">> & { exercise_id?: string };
export type Summary = {
  workout_id: string;
  duration_seconds: number;
  sets: number;
  volume_kg: string;
  prs: Record<string, PrKind[]>;
};
export type ProgressPoint = {
  workout_id: string;
  at: string;
  weight: string | null;
  unit: WeightUnit;
  reps: number | null;
  e1rm_kg: string;
};
export type MuscleVolume = { muscle: Muscle; volume_kg: string; sets: number; secondary_sets: number };
export type Volume = { week_start: string; muscles: MuscleVolume[] };
export type Consent = { consented_at: string | null };

const base = "/health";

export const healthKey = {
  all: ["health"] as const,
  consent: ["health", "consent"] as const,
};

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const healthApi = {
  consent: () => api<Consent>(`${base}/consent`),
  giveConsent: () => api<Consent>(`${base}/consent`, { method: "POST" }),
  withdrawConsent: () => api<null>(`${base}/consent`, { method: "DELETE" }),

  exercises: (f: ExerciseFilter) => api<Exercise[]>(`${base}/exercises${query({ ...f })}`),
  exercise: (id: string) => api<Exercise>(`${base}/exercises/${encodeURIComponent(id)}`),
  lastSets: (id: string) => api<SetEntry[]>(`${base}/exercises/${encodeURIComponent(id)}/last`),
  progress: (id: string) => api<ProgressPoint[]>(`${base}/exercises/${encodeURIComponent(id)}/progress`),

  routines: () => api<Routine[]>(`${base}/routines`),
  routine: (id: string) => api<Routine>(`${base}/routines/${id}`),
  createRoutine: (body: RoutineInput) => api<Routine>(`${base}/routines`, { method: "POST", body }),
  saveRoutine: (id: string, body: RoutineInput) => api<Routine>(`${base}/routines/${id}`, { method: "PUT", body }),
  deleteRoutine: (id: string) => api<null>(`${base}/routines/${id}`, { method: "DELETE" }),

  plan: () => api<Plan | null>(`${base}/plan`),
  savePlan: (body: PlanInput) => api<Plan>(`${base}/plan`, { method: "PUT", body }),

  today: () => api<Today>(`${base}/today`),
  startWorkout: (routine_id: string | null) => api<Workout>(`${base}/workouts`, { method: "POST", body: { routine_id } }),
  workouts: (range: { start?: string; end?: string } = {}) => api<WorkoutDetail[]>(`${base}/workouts${query(range)}`),
  workout: (id: string) => api<WorkoutDetail>(`${base}/workouts/${id}`),
  finishWorkout: (id: string, note?: string) =>
    api<Summary>(`${base}/workouts/${id}/finish`, { method: "POST", body: note ? { note } : {} }),
  discardWorkout: (id: string) => api<null>(`${base}/workouts/${id}`, { method: "DELETE" }),
  logSet: (workout: string, body: SetInput) =>
    api<SetEntry>(`${base}/workouts/${workout}/sets`, { method: "POST", body }),
  undoSet: (workout: string) => api<SetEntry>(`${base}/workouts/${workout}/undo`, { method: "POST" }),
  editSet: (id: string, body: SetPatch) => api<SetEntry>(`${base}/sets/${id}`, { method: "PATCH", body }),

  volume: (week?: string) => api<Volume>(`${base}/volume${query({ week })}`),
};
