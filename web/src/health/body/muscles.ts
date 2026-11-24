import type { Region } from "./paths";

/** The muscle names of free-exercise-db (the exercise library the Gym app uses), exactly as it spells them. */
export const MUSCLES = [
  "abdominals",
  "abductors",
  "adductors",
  "biceps",
  "calves",
  "chest",
  "forearms",
  "glutes",
  "hamstrings",
  "lats",
  "lower back",
  "middle back",
  "neck",
  "quadriceps",
  "shoulders",
  "traps",
  "triceps",
] as const;

export type Muscle = (typeof MUSCLES)[number];

/**
 * Where each muscle is drawn: one or more MuscleMap regions (names as in paths.ts). A region that does not exist
 * in a view is simply not drawn there, so one list serves front and back.
 *
 * MuscleMap has no abductors region: they are mapped to the glutes (gluteus medius) and the hip flexors (TFL).
 * Lats are its "upperBack"; middle back is the rhomboids and the lower trapezius, the muscles between the blades.
 */
export const MUSCLE_REGIONS: Record<Muscle, readonly Region[]> = {
  abdominals: ["abs", "obliques", "upperAbs", "lowerAbs"],
  abductors: ["gluteal", "hipFlexors"],
  adductors: ["adductors"],
  biceps: ["biceps"],
  calves: ["calves"],
  chest: ["chest", "upperChest", "lowerChest"],
  forearms: ["forearm"],
  glutes: ["gluteal"],
  hamstrings: ["hamstring"],
  lats: ["upperBack"],
  "lower back": ["lowerBack"],
  "middle back": ["rhomboids", "lowerTrapezius"],
  neck: ["neck"],
  quadriceps: ["quadriceps", "innerQuad", "outerQuad"],
  shoulders: ["deltoids", "frontDeltoid", "rearDeltoid"],
  traps: ["trapezius", "upperTrapezius"],
  triceps: ["triceps"],
};
