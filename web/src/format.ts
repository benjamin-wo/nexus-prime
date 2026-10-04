import type { Money } from "./api";

export function formatMoney(money: Money): string {
  const value = Number(money.amount);
  try {
    // Always the ISO code ("USD 33.80", never "$33.80"): symbols are ambiguous,
    // and many currencies here share "$".
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: money.currency,
      currencyDisplay: "code",
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${money.currency}`;
  }
}

export function formatDate(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", timeZone }).format(
    new Date(iso),
  );
}

/** Day and month only ("25 Sep"), for tight spaces. */
export function formatShortDate(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone }).format(new Date(iso));
}

/** YYYY-MM-DD of an instant in the user's timezone (for date inputs). */
export function isoDay(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(iso));
}

/** A signed change: "+USD 12.30", "−SGD 4.00". */
export function formatChange(money: Money): string {
  const value = Number(money.amount);
  const text = formatMoney({ ...money, amount: String(Math.abs(value)) });
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

/** A signed percentage: "+4.2%", "−0.8%". */
export function formatPercent(percent: string): string {
  const value = Number(percent);
  const text = `${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}
