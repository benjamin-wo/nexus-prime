import type { Budget, BudgetMonth, FeedItem, Money, Session, Today, TripDetail } from "./api";
import { DEPARTMENTS } from "./departments";
import { formatAmount, formatMoney } from "./format";

/** A run of a sentence: plain text, or a figure (set in Bricolage). */
export type Part = { text: string; hl?: boolean };

/** The biggest move among the stocks held, when it is big enough to be worth a line. */
export type MarketMove = { symbol: string; percent: number; session: Session };

/** A move this big, in percent, gets a row in For today. */
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
  overall?: Budget;
  lastMonthToDate?: Money;
  trip?: TripDetail | null;
  /** What is next on the trip that is on today (the first plan still to come), when there is one. */
  tripNext?: { text: string; time: string | null } | null;
  needs?: FeedItem[];
  /** This month's plan: what's left to spend once what's still due is paid. */
  plan?: BudgetMonth;
  /** The biggest held mover of the latest session, when notable (see `notableMove`). */
  move?: MarketMove | null;
};

function money(amount: number, currency: string, whole = false): string {
  return formatAmount({ amount: String(amount), currency }, { whole });
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
  /** The share of the month gone, when there is a budget to set it beside. */
  gone?: number;
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
    return { label, ahead: used > gone + 5, used, gone, detail: `${used}% of your budget used, ${gone}% through the month` };
  }
  if (lastMonthToDate) return { detail: `Last month by now: ${formatMoney(lastMonthToDate)}` };
  return null;
}

const inZone = (timezone: string, now: Date) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(now).split("-").map(Number) as [number, number, number];

const monthName = (year: number, month: number) =>
  new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, 1)));

/** "Sunday, 22 November": the Label over the headline. */
export function dateLabel(timezone: string, now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: timezone }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("weekday")}, ${get("day")} ${get("month")}`;
}

export type Headline = {
  /** The key figure, always positive; the currency is not shown beside it. */
  figure: Money;
  /** Over the overall budget: the figure is the month's spending, in rose. */
  over: boolean;
  /** What the figure is: the first words of `sentence`. */
  kind: "left" | "spent";
  /** The Body sentence under the figure, with its figures marked. */
  sentence: Part[];
};

/** Home's headline, written in code from the user's own figures (never a model's words): what is left of the
 * overall budget for the month (else what was spent), what that comes to a day, and how the month compares with
 * last month by this date. Null until the month's spending is known. */
export function headline({
  spent,
  overall,
  lastMonthToDate,
  timezone,
  now = new Date(),
}: Pick<BriefInput, "overall" | "lastMonthToDate"> & { spent?: Money; timezone: string; now?: Date }): Headline | null {
  if (!spent) return null;
  const [year, month, day] = inZone(timezone, now);
  const thisMonth = monthName(year, month);
  const lastMonth = monthName(month === 1 ? year - 1 : year, month === 1 ? 12 : month - 1);
  const daysLeft = new Date(Date.UTC(year, month, 0)).getUTCDate() - day;
  const spentNow = Number(spent.amount);
  const cur = spent.currency;
  const fig = (n: number, whole = false): Part => ({ text: money(n, cur, whole), hl: true });

  // "1,364.70 less spent than by this time in October": only when last month's figure is known, in words.
  const diff = lastMonthToDate ? spentNow - Number(lastMonthToDate.amount) : 0;
  const compare = (shape: "spent-after" | "plain"): Part[] =>
    !lastMonthToDate || diff === 0
      ? []
      : shape === "spent-after"
        ? [fig(Math.abs(diff)), { text: ` ${diff < 0 ? "less" : "more"} spent than by this time in ${lastMonth}` }]
        : [fig(Math.abs(diff)), { text: ` ${diff < 0 ? "less" : "more"} than by this time in ${lastMonth}` }];

  if (overall) {
    const left = Number(overall.limit.amount) - spentNow;
    if (left < 0) {
      const sentence: Part[] = [{ text: `spent, over for ${thisMonth} by ` }, fig(-left)];
      const c = compare("spent-after");
      if (c.length) sentence.push({ text: ", and " }, ...c);
      sentence.push({ text: "." });
      return { figure: { amount: String(spentNow), currency: cur }, over: true, kind: "spent", sentence };
    }
    const sentence: Part[] = [{ text: `left for ${thisMonth}` }];
    // Left divided by the days still to come, in whole units of the home currency; not on the last day.
    const perDay = daysLeft > 0 ? Math.round(left / daysLeft) : 0;
    const c = compare("spent-after");
    if (perDay >= 1) {
      sentence.push({ text: ". About " }, fig(perDay, true), { text: ` a day for the next ${daysLeft === 1 ? "day" : `${daysLeft} days`}` });
      if (c.length) sentence.push({ text: ", and " }, ...c);
    } else if (c.length) sentence.push({ text: ", with " }, ...c);
    sentence.push({ text: "." });
    return { figure: { amount: String(left), currency: cur }, over: false, kind: "left", sentence };
  }
  const sentence: Part[] = [{ text: `spent in ${thisMonth}` }];
  const c = compare("plain");
  if (c.length) sentence.push({ text: ", " }, ...c);
  sentence.push({ text: "." });
  return { figure: spent, over: false, kind: "spent", sentence };
}


/** One row of For today: what, a muted line, and the word at its right. */
export type TodayRow = {
  key: string;
  kind: "market" | "trip" | "plan" | "need";
  title: string;
  sub?: string;
  /** The plain word at the right: "Look", "Today", ... */
  word: string;
  /** How soon: `now` puts the word in the warning colour, `today` says Today quietly. */
  when: "now" | "today" | "soon";
  /** Where the thing is settled. */
  link: string;
  /** The needs-you item behind it, whose actions settle it in place. */
  item?: FeedItem;
};

/** For today, written in code from the user's own figures: a need that is urgent, the trip, a notable move in the
 * stocks held, a tighter plan than the budget says, then everything else that needs the person, in the order the
 * server gave. A row says what it is; none counts how many things there are. */
export function forToday({ trip, tripNext, needs, plan, overall, move }: BriefInput): TodayRow[] {
  const urgent: TodayRow[] = [];
  const later: TodayRow[] = [];
  for (const item of needs ?? []) {
    const label = DEPARTMENTS.find((d) => d.name === item.department)?.label;
    const row: TodayRow = {
      key: `need:${item.kind}:${item.text}`,
      kind: "need",
      title: item.text,
      sub: label,
      word: item.when === "today" ? "Today" : "Look",
      when: item.when,
      link: item.link,
      item,
    };
    (item.when === "now" ? urgent : later).push(row);
  }
  const rows: TodayRow[] = [...urgent];

  if (trip && trip.trip.status !== "finished") {
    const t = trip.trip;
    const link = `/travel/trips/${t.id}`;
    if (t.status === "ongoing") {
      if (tripNext)
        rows.push({
          key: "trip",
          kind: "trip",
          title: tripNext.text,
          sub: `${t.destination}${tripNext.time ? `, from ${tripNext.time}` : ""}`,
          word: "Today",
          when: "today",
          link,
        });
    } else {
      const gaps = trip.ready.nights_without_stay.length;
      const starts = t.days_until === 1 ? "tomorrow" : `in ${t.days_until} days`;
      if (gaps > 0)
        rows.push({ key: "trip", kind: "trip", title: `${t.destination} still needs a place to stay`, sub: `Starts ${starts}`, word: "Look", when: "soon", link });
      else if (t.days_until <= 7)
        rows.push({ key: "trip", kind: "trip", title: `${t.destination} starts ${starts}`, sub: "Your next trip", word: "Look", when: "soon", link });
    }
  }

  if (move) {
    const down = move.percent < 0;
    const shown = `${Math.round(Math.abs(move.percent))}%`;
    const title =
      move.session === "live"
        ? `${move.symbol} is ${down ? "down" : "up"} ${shown} today`
        : `${move.symbol} ${down ? "fell" : "rose"} ${shown} ${move.session === "closed_today" ? "today" : "in the last session"}`;
    rows.push({ key: "market", kind: "market", title, sub: "One of your holdings", word: "Look", when: "soon", link: `/investment/stocks/${move.symbol}` });
  }

  // Only worth a row when the budget on its own would mislead: less is really left to spend than it says, or
  // the bills still due take it from left to over.
  if (overall && plan?.budget_left) {
    if (plan.tighter === "left_to_spend" && Number(plan.left_to_spend.amount) < Number(plan.budget_left.amount))
      rows.push({
        key: "plan",
        kind: "plan",
        title: "Less to spend than your budget says",
        sub: `Left to spend is ${formatMoney(plan.left_to_spend)} after what's still due, below the ${formatMoney(plan.budget_left)} budget left.`,
        word: "Look",
        when: "soon",
        link: "/accounting/budgets",
      });
    else if (
      plan.tighter === "budget" &&
      plan.budget_left_after_due &&
      Number(plan.budget_left.amount) >= 0 &&
      Number(plan.budget_left_after_due.amount) < 0
    )
      rows.push({
        key: "plan",
        kind: "plan",
        title: "Bills still due take you over budget",
        sub: `Once the ${formatMoney(plan.spending_due)} still due is paid you'll be ${formatMoney({ ...plan.budget_left_after_due, amount: String(-Number(plan.budget_left_after_due.amount)) })} over.`,
        word: "Look",
        when: "soon",
        link: "/accounting/budgets",
      });
  }
  return [...rows, ...later];
}
