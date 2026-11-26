import type { Exercise, Routine, SetEntry, Workout } from "./api";

/** Made-up data for the Health tests. */
export const bench: Exercise = {
  id: "Barbell_Bench_Press",
  name: "Barbell bench press",
  category: "strength",
  level: "beginner",
  equipment: "barbell",
  force: "push",
  mechanic: "compound",
  primary_muscles: ["chest"],
  secondary_muscles: ["triceps", "shoulders"],
  instructions: ["Lie on the bench.", "Lower the bar to your chest.", "Press it back up."],
  images: ["https://img.test/bench/0.jpg", "https://img.test/bench/1.jpg"],
};
export const squat: Exercise = {
  ...bench,
  id: "Barbell_Squat",
  name: "Barbell squat",
  primary_muscles: ["quadriceps"],
  secondary_muscles: ["glutes"],
  images: [],
};
export const exercises = [bench, squat];

export const push: Routine = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Push day",
  slots: [{ exercise_id: bench.id, sets: 2, reps: 5, seconds: null, rest_seconds: 90, note: null }],
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-01T08:00:00Z",
};

export const workout: Workout = {
  id: "22222222-2222-2222-2222-222222222222",
  routine_id: null,
  started_at: "2026-11-24T08:00:00Z",
  finished_at: null,
  note: null,
};

export function setEntry(over: Partial<SetEntry> = {}): SetEntry {
  return {
    id: "s1",
    workout_id: workout.id,
    exercise_id: bench.id,
    position: 1,
    kind: "working",
    reps: 5,
    weight: "80.00",
    unit: "kg",
    seconds: null,
    rpe: null,
    done_at: "2026-11-24T08:10:00Z",
    ...over,
  };
}
