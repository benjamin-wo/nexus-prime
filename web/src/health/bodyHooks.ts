import { useQuery } from "@tanstack/react-query";

import { healthApi, healthKey, type WeightUnit } from "./api";
import { bodyApi, bodyKey } from "./bodyApi";

/** One day's food (null is today, by the server's clock). */
export const useDay = (date: string | null) => useQuery({ queryKey: bodyKey.day(date), queryFn: () => bodyApi.day(date) });
export const useWeight = () => useQuery({ queryKey: bodyKey.weight, queryFn: () => bodyApi.weight() });
export const useConsents = () => useQuery({ queryKey: bodyKey.consents, queryFn: bodyApi.consents, staleTime: 5 * 60_000 });
export const useProfile = () => useQuery({ queryKey: bodyKey.profile, queryFn: bodyApi.profile });

/** The unit weights are logged in (kg until the preference loads). */
export function useWeightUnit(): WeightUnit {
  const prefs = useQuery({ queryKey: healthKey.preferences, queryFn: healthApi.preferences });
  return prefs.data?.unit ?? "kg";
}
