import { type Balance, type BalancePart, type Money, type SettleResult, type ToSplit, type TripDetail, type TripSaving } from "../api";
import { formatMoney } from "../format";
import { balanceAmount } from "./TripStage";

export const amount = (m: Money | null) => (m ? Number(m.amount) : 0);
export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
export const moneyOf = (value: number, currency: string): Money => ({ amount: String(Math.round(value * 100) / 100), currency });
export const sameName = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

export const positive = (m: Money | null): m is Money => m !== null && Number(m.amount) > 0;

/** The set-aside plan in a sentence: "SGD 500.00 each payday: about SGD 100.00 so far, SGD 1,500.00
 * by the trip (3 paydays left, next 25 Oct)." What's saved so far and what it comes to by the trip
 * are left out when missing or zero; the rest still reads as one sentence. */
export function setAsideText(
  a: Pick<TripSaving, "per_payday" | "saved" | "by_start" | "paydays_left">,
  nextPayday: string | null,
): string {
  if (!a.per_payday) return "";
  const progress = [positive(a.saved) && `about ${formatMoney(a.saved)} so far`, positive(a.by_start) && `${formatMoney(a.by_start)} by the trip`].filter(Boolean);
  const left = `${plural(a.paydays_left, "payday")} left${nextPayday ? `, next ${nextPayday}` : ""}`;
  return `${formatMoney(a.per_payday)} each payday${progress.length > 0 ? `: ${progress.join(", ")}` : ""} (${left}).`;
}

export const failure = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);
export const unsigned = (m: Money): Money => ({ ...m, amount: String(Math.abs(Number(m.amount))) });

/** "Alex", "Alex and Sam", "Alex, Sam and Ben". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The home-currency total of costs, and how many of them had no exchange rate to count. */
export function totalOf(items: { home: Money | null }[], currency: string): { total: Money; unrated: number } {
  let sum = 0;
  let unrated = 0;
  for (const i of items) {
    if (i.home && i.home.currency === currency) sum += Number(i.home.amount);
    else unrated += 1;
  }
  return { total: { amount: String(Math.round(sum * 100) / 100), currency }, unrated };
}

/** The question before splitting: "Split 6 costs (SGD 2,140.00) evenly with Alex and Sam?" */
export function splitConfirmText(items: { home: Money | null }[], names: string[], home: string): string {
  const { total, unrated } = totalOf(items, home);
  const counted = items.length - unrated;
  const sum =
    counted === 0 ? "" : unrated > 0 ? ` (${formatMoney(total)}, not counting ${plural(unrated, "cost")} with no exchange rate yet)` : ` (${formatMoney(total)})`;
  return `Split ${plural(items.length, "cost")}${sum} evenly with ${joinNames(names)}?`;
}

/** Where the user stands with a person, in a sentence: "Alex owes you SGD 768.00", "You owe
 * Sam SGD 40.00", "All square with Ben". With amounts in several currencies and no single
 * total, each side is named: "Alex owes you JPY 4,000 and you owe Alex SGD 20.00". */
export function balanceWords(b: Balance): string {
  if (b.direction === "even") return `All square with ${b.person}`;
  if (b.direction === "owes_you") return `${b.person} owes you ${balanceAmount(b)}`;
  if (b.direction === "you_owe") return `You owe ${b.person} ${balanceAmount(b)}`;
  const theirs = b.net_by_currency.filter((m) => Number(m.amount) > 0).map((m) => formatMoney(m));
  const yours = b.net_by_currency.filter((m) => Number(m.amount) < 0).map((m) => formatMoney(unsigned(m)));
  const pieces = [theirs.length > 0 && `${b.person} owes you ${theirs.join(" + ")}`, yours.length > 0 && `you owe ${b.person} ${yours.join(" + ")}`].filter(
    (p): p is string => p !== false,
  );
  if (pieces.length === 0) return `All square with ${b.person}`;
  const text = pieces.join(" and ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Amounts added up per currency, in the currency each was in. */
export function sumByCurrency(list: Money[]): Money[] {
  const sums = new Map<string, number>();
  for (const m of list) sums.set(m.currency, (sums.get(m.currency) ?? 0) + Number(m.amount));
  return [...sums].map(([currency, sum]) => ({ amount: String(Math.round(sum * 100) / 100), currency }));
}

export const partsTotal = (parts: BalancePart[]) => sumByCurrency(parts.map((p) => p.amount));

export const moneyList = (list: Money[]) => list.map(formatMoney).join(" + ");

/** What Mark settled will record, before it is confirmed. Nexus only writes down what the
 * user says happened; it never moves money. */
export function settleConfirmText(b: Balance, log: boolean): string {
  const owedToYou = b.owes_you.length > 0 ? moneyList(partsTotal(b.owes_you)) : null;
  const owedByYou = b.you_owe.length > 0 ? moneyList(partsTotal(b.you_owe)) : null;
  const sentences: string[] = [];
  if (owedToYou) sentences.push(`This records that ${b.person} paid you back ${owedToYou}.`);
  if (owedByYou) {
    const lead = owedToYou ? "It also " : "This ";
    sentences.push(
      log
        ? `${lead}records that you paid ${b.person} ${owedByYou} and counts it as spent.`
        : `${lead}marks the ${owedByYou} you owe ${b.person} as paid, without adding it to what you've spent.`,
    );
  }
  sentences.push("Nexus doesn't move any money.");
  return sentences.join(" ");
}

/** What a settle recorded, in words. */
export function settledText(r: SettleResult): string {
  const parts: string[] = [];
  if (r.ious_repaid > 0) {
    parts.push(`${plural(r.ious_repaid, "IOU")} from ${r.person} marked paid back${r.income.length > 0 ? `, ${moneyList(r.income)} recorded as money in` : ""}`);
  }
  if (r.payments_settled > 0) {
    parts.push(
      `${plural(r.payments_settled, "payment")} you owed ${r.person} marked paid${r.expenses.length > 0 ? `, ${moneyList(r.expenses)} recorded as spent` : ", nothing added to what you've spent"}`,
    );
  }
  return parts.length === 0 ? `Nothing was left to settle with ${r.person}.` : `Settled with ${r.person}: ${parts.join("; ")}.`;
}

/** "Split 3 costs (SGD 612.40) evenly with Alex? Each share is SGD 306.20." The share is
 * left out when some costs have no exchange rate yet (the total isn't whole). */
export function splitAskText(items: { home: Money | null }[], names: string[], home: string): string {
  const question = splitConfirmText(items, names, home);
  const { total, unrated } = totalOf(items, home);
  if (unrated > 0 || items.length === 0) return question;
  const cents = Math.round(Number(total.amount) * 100);
  const people = names.length + 1;
  const share = moneyOf(cents / people / 100, home);
  return `${question} Each share is ${cents % people === 0 ? "" : "about "}${formatMoney(share)}.`;
}

/** The line under "3 costs to split": the total, then the first three titles and how many more. */
export function toSplitSub(items: ToSplit[], home: string): string {
  const titles = items.slice(0, 3).map((i) => i.counterparty ?? "Expense");
  const names = items.length > 3 ? `${titles.join(", ")} and ${items.length - 3} more` : titles.join(", ");
  const { total, unrated } = totalOf(items, home);
  return unrated < items.length ? `${formatMoney(total)} · ${names}` : names;
}

/** What's planned and not spent yet: each planned cost less what's already spent in that
 * category and what's booked for it and not logged (in the home currency). */
export function plannedAhead(detail: TripDetail): number {
  const s = detail.spending;
  if (!s) return 0;
  let sum = 0;
  for (const [name, cost] of Object.entries(detail.trip.planned)) {
    const spent = s.categories.filter((c) => sameName(c.name, name)).reduce((t, c) => t + amount(c.spent), 0);
    const booked = detail.bookings
      .filter((b) => b.scheduled && !b.logged && b.cost && b.cost.currency === s.spent.currency && b.category && sameName(b.category, name))
      .reduce((t, b) => t + amount(b.cost), 0);
    sum += Math.max(0, amount(cost) - spent - booked);
  }
  return sum;
}
