import type { Budget, BudgetMonth, FeedItem, Money, TripDetail } from "./api";
import { formatMoney } from "./format";

/** A run of the brief: plain text, or a figure shown in the accent colour. */
export type Part = { text: string; hl?: boolean };

export type BriefInput = {
  spent?: Money;
  overall?: Budget;
  lastMonthToDate?: Money;
  trip?: TripDetail | null;
  needs?: FeedItem[];
  /** This month's plan: what's left to spend once what's still due is paid. */
  plan?: BudgetMonth;
};

function money(amount: number, currency: string): string {
  return formatMoney({ amount: String(amount), currency });
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** How this month stands, in words: against the overall budget if there is one,
 * else against last month by the same date. ``good`` when it's the better side. */
export function standing({ spent, overall, lastMonthToDate }: BriefInput): { text: string; good: boolean } | null {
  if (!spent) return null;
  const now = Number(spent.amount);
  if (overall) {
    const left = Number(overall.limit.amount) - now;
    return { text: `${money(Math.abs(left), spent.currency)} ${left >= 0 ? "left in your budget" : "over your budget"}`, good: left >= 0 };
  }
  if (!lastMonthToDate) return null;
  const diff = now - Number(lastMonthToDate.amount);
  if (diff === 0) return { text: "The same as by this time last month", good: true };
  return {
    text: `${money(Math.abs(diff), spent.currency)} ${diff < 0 ? "less" : "more"} than by this time last month`,
    good: diff < 0,
  };
}

/** Home's opening lines, written in code from the user's own figures: this month's
 * spending against the budget (or last month), the next trip, and what needs them.
 * Nothing here is a model's words, so every figure is the app's own. */
export function brief({
  spent,
  overall,
  lastMonthToDate,
  trip,
  needs,
  plan,
}: BriefInput): Part[] {
  const parts: Part[] = [];
  if (spent) {
    parts.push(
      { text: "You've spent " },
      { text: formatMoney(spent), hl: true },
      { text: " this month" },
    );
    const now = Number(spent.amount);
    if (overall) {
      const left = Number(overall.limit.amount) - now;
      parts.push(
        { text: ", " },
        {
          text: `${money(Math.abs(left), spent.currency)} ${left >= 0 ? "left" : "over"}`,
          hl: true,
        },
        { text: left >= 0 ? " in your budget." : " your budget." },
      );
    } else if (lastMonthToDate) {
      const diff = now - Number(lastMonthToDate.amount);
      if (diff === 0)
        parts.push({ text: ", the same as by this time last month." });
      else
        parts.push(
          { text: ", " },
          {
            text: `${money(Math.abs(diff), spent.currency)} ${diff < 0 ? "less" : "more"}`,
            hl: true,
          },
          { text: " than by this time last month." },
        );
    } else parts.push({ text: "." });
  }
  // Only worth a line when the budget on its own would mislead: less is really left
  // to spend than the budget says.
  if (
    overall &&
    plan?.tighter === "left_to_spend" &&
    plan.budget_left &&
    Number(plan.left_to_spend.amount) < Number(plan.budget_left.amount)
  )
    parts.push(
      { text: `${parts.length ? " " : ""}Left to spend is ` },
      { text: formatMoney(plan.left_to_spend), hl: true },
      { text: " after what's still due — less than your " },
      { text: formatMoney(plan.budget_left), hl: true },
      { text: " budget left." },
    );
  if (trip && trip.trip.status !== "finished") {
    const t = trip.trip;
    const gaps = trip.ready.nights_without_stay.length;
    if (t.status === "ongoing") {
      parts.push(
        {
          text: `${parts.length ? " " : ""}You're on day ${t.day_number} of ${t.days} in `,
        },
        { text: t.destination, hl: true },
        { text: "." },
      );
    } else {
      parts.push(
        { text: `${parts.length ? " " : ""}Your ` },
        { text: `${t.destination} trip`, hl: true },
        {
          text:
            t.days_until === 1
              ? " starts tomorrow"
              : ` is in ${t.days_until} days`,
        },
      );
      parts.push(
        gaps
          ? {
              text: ` and still needs ${plural(gaps, "night", "nights")} of lodging.`,
            }
          : { text: "." },
      );
    }
  }
  const waiting = needs?.length ?? 0;
  if (waiting)
    parts.push({
      text: `${parts.length ? " " : ""}${plural(waiting, "thing needs", "things need")} you below.`,
    });
  if (!parts.length)
    parts.push({
      text: "Nothing needs you right now. Ask me anything about your money, plans or trips.",
    });
  return parts;
}

/** Questions worth one tap, from what's going on. */
export function suggestions({
  trip,
  holdings,
}: {
  trip?: TripDetail | null;
  holdings?: string[];
}): string[] {
  const found = ["Where did my money go this month?"];
  if (
    trip &&
    trip.trip.status === "upcoming" &&
    trip.ready.nights_without_stay.length
  )
    found.push(`Find a place to stay in ${trip.trip.destination}`);
  else if (trip && trip.trip.status !== "finished")
    found.push(`How is my ${trip.trip.destination} budget looking?`);
  if (holdings?.length) found.push(`Plan for ${holdings[0]}`);
  else found.push("What bills are coming up?");
  return found;
}
