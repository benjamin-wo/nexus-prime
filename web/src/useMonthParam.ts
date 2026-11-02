import { useSearchParams } from "react-router-dom";

import { currentMonth, type MonthKey, pickedMonth } from "./months";

/** The month a page shows, kept in the address as `?month=YYYY-MM` so a month can be
 * linked to and Back steps through the months picked. Anything that isn't a month
 * from the last two years up to this one means this month, which has no `?month=`. */
export function useMonthParam(timezone: string): {
  month: MonthKey;
  current: MonthKey;
  past: boolean;
  setMonth: (next: MonthKey) => void;
} {
  const [params, setParams] = useSearchParams();
  const current = currentMonth(timezone);
  const month = pickedMonth(params.get("month"), current);

  function setMonth(next: MonthKey) {
    // Each pick is a history entry; picking the month already shown adds none.
    if (next === month) return;
    setParams((previous) => {
      const updated = new URLSearchParams(previous);
      if (next === current) updated.delete("month");
      else updated.set("month", next);
      return updated;
    });
  }

  return { month, current, past: month !== current, setMonth };
}
