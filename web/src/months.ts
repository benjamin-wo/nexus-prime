import { isoDay } from "./format";

/** A calendar month as "YYYY-MM", the way the address and the API write it. */
export type MonthKey = string;

/** How far back a month can be picked. */
export const MONTHS_BACK = 24;

const PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

export function monthKey(date: Date): MonthKey {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function shiftMonth(key: MonthKey, by: number): MonthKey {
  const [year, month] = key.split("-").map(Number);
  return monthKey(new Date(Date.UTC(year, month - 1 + by, 1)));
}

/** "October 2026". */
export function monthLabel(key: MonthKey): string {
  const [year, month] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(year, month - 1, 1)),
  );
}

/** "September", for "S$180 less than September". */
export function monthName(key: MonthKey): string {
  const [year, month] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "long", timeZone: "UTC" }).format(
    new Date(Date.UTC(year, month - 1, 1)),
  );
}

/** The month it is now, in the user's timezone. */
export function currentMonth(timezone: string, now: Date = new Date()): MonthKey {
  return isoDay(now.toISOString(), timezone).slice(0, 7);
}

/** The earliest month that can be picked, counted back from the current one. */
export function earliestMonth(current: MonthKey): MonthKey {
  return shiftMonth(current, -MONTHS_BACK);
}

/** What the address asks for, or the current month when that is missing, not a month,
 * in the future, or further back than can be picked. */
export function pickedMonth(raw: string | null, current: MonthKey): MonthKey {
  if (!raw || !PATTERN.test(raw)) return current;
  return raw <= current && raw >= earliestMonth(current) ? raw : current;
}

/** First and last day of a month, as YYYY-MM-DD (the end is inclusive, as `/summary` takes it). */
export function monthRange(key: MonthKey): { start: string; end: string } {
  const [year, month] = key.split("-").map(Number);
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return { start: `${key}-01`, end: `${key}-${String(last).padStart(2, "0")}` };
}
