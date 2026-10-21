import type { Budget, BudgetMonth, FeedItem, Money, Session, Today, TripDetail } from "./api";
import { formatMoney } from "./format";

/** A run of the brief: plain text, or a figure shown in the accent colour. */
export type Part = { text: string; hl?: boolean };

/** The biggest move among the stocks held, when it is big enough to be worth a line. */
export type MarketMove = { symbol: string; percent: number; session: Session };

/** A move this big, in percent, is mentioned in the brief. */
export const NOTABLE_MOVE = 3;

/** The held stock that moved most in the latest US session, if it moved by at least
 * `NOTABLE_MOVE` percent. */
export function notableMove(today?: Today | null): MarketMove | null {
  let best: MarketMove | null = null;
  for (const m of today?.movers ?? []) {
    const percent = Number(m.day_percent);
    if (!m.held || !Number.isFinite(percent)) continue;
    if (!best || Math.abs(percent) > Math.abs(best.percent)) best = { symbol: m.symbol, percent, session: today!.session };
  }
  return best && Math.abs(best.percent) >= NOTABLE_MOVE ? best : null;
}

export type BriefInput = {
  spent?: Money;
  overall?: Budget;
  lastMonthToDate?: Money;
  trip?: TripDetail | null;
  needs?: FeedItem[];
  /** This month's plan: what's left to spend once what's still due is paid. */
  plan?: BudgetMonth;
  /** The biggest held mover of the latest session, when notable (see `notableMove`). */
  move?: MarketMove | null;
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

/** How far through the month it is, 0 to 100, on the user's calendar. */
export function monthShare(timezone: string, now: Date = new Date()): number {
  const [y, m, d] = new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(now).split("-").map(Number);
  return Math.round((d / new Date(Date.UTC(y, m, 0)).getUTCDate()) * 100);
}

export type Pace = {
  /** "Ahead of pace", "On pace" or "Under pace"; only against a budget. */
  label?: string;
  /** Spending is running ahead of the month. */
  ahead?: boolean;
  /** The share of the overall budget used, when there is one. */
  used?: number;
  detail: string;
};

/** How spending is going for the month: against the overall budget (the share used next
 * to the share of the month gone), else against last month by the same date. Null when
 * there is nothing to compare with. */
export function pace({
  overall,
  lastMonthToDate,
  timezone,
  now,
}: Pick<BriefInput, "overall" | "lastMonthToDate"> & { timezone: string; now?: Date }): Pace | null {
  if (overall) {
    const gone = monthShare(timezone, now);
    const used = overall.percent;
    const label = used > gone + 5 ? "Ahead of pace" : used < gone - 5 ? "Under pace" : "On pace";
    return { label, ahead: used > gone + 5, used, detail: `${used}% of your budget used, ${gone}% through the month` };
  }
  if (lastMonthToDate) return { detail: `Last month by now: ${formatMoney(lastMonthToDate)}` };
  return null;
}

/** Home's opening lines, written in code from the user's own figures: this month's
 * spending against the budget (or last month), a notable move in the stocks held, the
 * next trip, and what needs them.
 * Nothing here is a model's words, so every figure is the app's own. */
export function brief({
  spent,
  overall,
  lastMonthToDate,
  trip,
  needs,
  plan,
  move,
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
  if (move) {
    const down = move.percent < 0;
    const shown = `${Math.round(Math.abs(move.percent))}%`;
    const space = parts.length ? " " : "";
    if (move.session === "live")
      parts.push({ text: `${space}${move.symbol} is ${down ? "down" : "up"} ` }, { text: shown, hl: true }, { text: " today." });
    else
      parts.push(
        { text: `${space}${move.symbol} ${down ? "fell" : "rose"} ` },
        { text: shown, hl: true },
        { text: move.session === "closed_today" ? " today." : " in the last session." },
      );
  }
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
