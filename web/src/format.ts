import type { Money, PriceKind, Transaction } from "./api";

export type MoneyOptions = {
  /** No decimals, for figures that are whole numbers ("SGD 4,602"). */
  whole?: boolean;
};

function moneyFormat(currency: string, whole: boolean | undefined): Intl.NumberFormat {
  // Always the ISO code ("USD 33.80", never "$33.80"): symbols are ambiguous,
  // and many currencies here share "$".
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    currencyDisplay: "code",
    ...(whole ? { minimumFractionDigits: 0, maximumFractionDigits: 0 } : {}),
  });
}

function show(money: Money, whole: boolean | undefined): string {
  const value = Number(money.amount);
  try {
    return moneyFormat(money.currency, whole).format(value);
  } catch {
    return `${whole ? Math.round(value) : value.toFixed(2)} ${money.currency}`;
  }
}

export const formatMoney = (money: Money): string => show(money, false);

/** For figures that are whole numbers at the source: "SGD 6,760". */
export const formatWholeMoney = (money: Money): string => show(money, true);

/** A range with the currency once and an en dash: "SGD 4,602–6,760". One amount when both ends
 * are the same; "SGD 90.00 – USD 70.00" when the currencies differ. */
export function formatRange(lo: Money, hi: Money, opts?: MoneyOptions): string {
  if (lo.currency !== hi.currency) return `${show(lo, opts?.whole)} – ${show(hi, opts?.whole)}`;
  try {
    const format = moneyFormat(lo.currency, opts?.whole);
    const numbers = (m: Money) =>
      format
        .formatToParts(Number(m.amount))
        .filter((p) => p.type !== "currency" && p.type !== "literal")
        .map((p) => p.value)
        .join("");
    const low = numbers(lo);
    const high = numbers(hi);
    if (low === high) return format.format(Number(lo.amount));
    // Keep the first amount as the locale writes it and swap its number for "lo–hi".
    let placed = false;
    return format
      .formatToParts(Number(lo.amount))
      .map((p) => {
        if (p.type === "currency" || p.type === "literal") return p.value;
        if (placed) return "";
        placed = true;
        return `${low}–${high}`;
      })
      .join("");
  } catch {
    return `${show(lo, opts?.whole)} – ${show(hi, opts?.whole)}`;
  }
}

/** A foreign amount followed by what it is at home: "JPY 2,000 · SGD 18.00". Just the amount
 * when there is no home figure or it is in the same currency. */
export function formatWithHome(amount: Money, home: Money | null | undefined): string {
  const text = formatMoney(amount);
  return home && home.currency !== amount.currency ? `${text} · ${formatMoney(home)}` : text;
}

/** Where a move went: "→ IBKR" from Spending, "Savings → Spending" from anywhere else. */
export function moveLabel(tx: Pick<Transaction, "from_wallet" | "to_wallet">): string {
  const { from_wallet: from, to_wallet: to } = tx;
  if (!to) return "Move";
  return !from || from.kind === "spending" ? `→ ${to.name}` : `${from.name} → ${to.name}`;
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

/** When a price is from: "Live, 10:42 pm", "Close of 25 Sep, not final", or "Close of 25 Sep". */
export function priceWhen(kind: PriceKind | null, at: string | null, day: string | null): string {
  if (kind === "live" && at) {
    return `Live, ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(at))}`;
  }
  const close = day ? `Close of ${formatShortDate(day, "UTC")}` : "Close";
  return kind === "provisional_close" ? `${close}, not final` : close;
}
