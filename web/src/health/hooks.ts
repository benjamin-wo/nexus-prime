import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { type Exercise, healthApi, healthKey } from "./api";

/** A value that follows `value` after it has stood still for `ms`. */
export function useDebounced<T>(value: T, ms = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

const STALE = 10 * 60_000; // the catalogue barely changes

export function useExercise(id: string | null | undefined) {
  return useQuery({
    queryKey: [...healthKey.all, "exercise", id],
    queryFn: () => healthApi.exercise(id as string),
    enabled: !!id,
    staleTime: STALE,
  });
}

/** Exercises by id, for naming sets and slots. An exercise still loading is missing from the map. */
export function useExerciseMap(ids: readonly string[]): Map<string, Exercise> {
  const unique = [...new Set(ids)];
  const results = useQueries({
    queries: unique.map((id) => ({
      queryKey: [...healthKey.all, "exercise", id],
      queryFn: () => healthApi.exercise(id),
      staleTime: STALE,
    })),
  });
  const map = new Map<string, Exercise>();
  results.forEach((r, i) => {
    if (r.data) map.set(unique[i], r.data);
  });
  return map;
}

/** The name of an exercise, or a quiet stand-in while it loads. */
export const exerciseName = (map: Map<string, Exercise>, id: string) => map.get(id)?.name ?? "Exercise";

export function useRoutines() {
  return useQuery({ queryKey: [...healthKey.all, "routines"], queryFn: healthApi.routines });
}
