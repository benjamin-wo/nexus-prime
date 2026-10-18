import type { Balance, Booking, TripDetail } from "../api";
import { Icon } from "../components/Icon";
import { formatMoney, formatShortDate } from "../format";
import { sortKey, stopOfDay, stopsOf } from "./TripBits";

/** Where the trip is, which decides what its page shows first: the gaps while
 * planning, getting ready in the last week, today while it's on, settling up after. */
export type Stage = "planning" | "soon" | "during" | "after";

/** Days before the start when getting ready (check-in, packing, weather) comes first. */
export const SOON_DAYS = 7;

export function stageOf(detail: TripDetail): Stage {
  const t = detail.trip;
  if (t.status === "finished") return "after";
  if (t.status === "ongoing") return "during";
  return t.days_until <= SOON_DAYS ? "soon" : "planning";
}

const day = (iso: string) => formatShortDate(iso, "UTC");
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export type Fix = { kind: "hotel" | "flight"; day?: string } | "budget";

/** What the trip still needs, each with the one action that fixes it. */
export function stillToSort(detail: TripDetail): { text: string; action: string; fix: Fix }[] {
  const r = detail.ready;
  const items: { text: string; action: string; fix: Fix }[] = [];
  const nights = r.nights_without_stay;
  if (nights.length > 0) {
    items.push({
      text: `${plural(nights.length, "night")} without a place to stay (${nights.map(day).join(", ")})`,
      action: "Add",
      fix: { kind: "hotel", day: nights[0] },
    });
  }
  if (!r.has_transport) items.push({ text: "No flight or train yet", action: "Add", fix: { kind: "flight" } });
  if (!r.has_budget) items.push({ text: "No budget yet", action: "Set", fix: "budget" });
  return items;
}

/** Whether nothing is on a day: no plan, flight, train leg or check-in starting, landing
 * or leaving then, and no check-out. Staying the night somewhere doesn't fill a day. */
export function dayIsFree(detail: Pick<TripDetail, "bookings">, iso: string): boolean {
  return !detail.bookings.some(
    (b) =>
      b.scheduled &&
      (b.starts === iso ||
        (b.kind === "hotel" && b.check_in !== null && b.check_out === iso) ||
        b.segments.some((s) => s.departs?.slice(0, 10) === iso || s.arrives?.slice(0, 10) === iso)),
  );
}

/** Where a "Next up" button goes: another tab (a day on Plan or Ideas), or a fix. */
export type Go = { tab: "ideas"; day?: string } | { tab: "prep" } | { tab: "money" } | { fix: Fix } | { tab: "plan"; day: string };

const DAY_MS = 86400000;
const localDay = (when: Date) => when.toLocaleDateString("en-CA");

/** "Fri 2 Apr", in English whatever the browser's language, like the sentence around it. */
function dayWords(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).formatToParts(new Date(iso));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("weekday")} ${part("day")} ${part("month")}`;
}

/** The HH:MM an entry was booked or planned for, if it has one. */
const statedTime = (b: Booking): string | null => b.at ?? b.segments[0]?.departs?.slice(11, 16) ?? null;

/** An entry as a short phrase: "SQ 638", "check in at Hotel Ume", "Dinner at Sushi Ten". */
function entryWords(b: Booking): string {
  if (b.kind === "flight" || b.kind === "rail") return b.segments[0]?.number ?? b.title;
  if (b.kind === "hotel") return `check in at ${b.hotel ?? b.title}`;
  return b.title;
}

/** The one thing worth doing next on the trip, for the strip under its header, or
 * null when there's nothing. ``ideasFor``: how many ideas could fill a given day. */
export function nextUp(detail: TripDetail, ideasFor: (day: string) => number, now: Date = new Date()): { text: string; action: string; go: Go } | null {
  const stage = stageOf(detail);
  const today = localDay(now);
  if (stage === "planning") {
    const [first] = stillToSort(detail);
    if (first) return { text: first.text, action: first.action, go: { fix: first.fix } };
    const trip = detail.trip;
    const stops = stopsOf(detail);
    for (let t = Date.parse(trip.start), n = 1; t <= Date.parse(trip.end); t += DAY_MS, n += 1) {
      const iso = new Date(t).toISOString().slice(0, 10);
      if (!dayIsFree(detail, iso)) continue;
      const ideas = ideasFor(iso);
      // "Day 4 in Tokyo": the stop it falls in, which on a travel day is where you arrive.
      const stop = stopOfDay(stops, iso);
      return {
        text: `Day ${n}${stop ? ` in ${stop.name}` : ""} is still free.${ideas > 0 ? ` ${ideas} of your ideas could fill it.` : ""}`,
        action: "Find ideas",
        go: { tab: "ideas", day: iso },
      };
    }
    return null;
  }
  if (stage === "soon") {
    const next = detail.bookings.filter((b) => b.scheduled && b.starts >= today).sort((a, b) => sortKey(a).localeCompare(sortKey(b)))[0];
    if (next) {
      const time = statedTime(next);
      return { text: `Next: ${entryWords(next)} on ${dayWords(next.starts)}${time ? ` at ${time}` : ""}`, action: "Open day", go: { tab: "plan", day: next.starts } };
    }
    const left = (detail.trip.packing ?? []).filter((p) => !p.done).length;
    if (left > 0) return { text: `${plural(left, "thing")} left to pack`, action: "Open packing", go: { tab: "prep" } };
    return null;
  }
  if (stage === "during") {
    const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    // A check-in with no time is taken as 15:00; a plan with none can't be told from now.
    const at = (b: Booking) => statedTime(b) ?? (b.kind === "hotel" ? "15:00" : "");
    const upcoming = detail.bookings
      .filter((b) => b.scheduled && b.starts === today && at(b) > time)
      .sort((a, b) => at(a).localeCompare(at(b)))[0];
    if (!upcoming) return null;
    return { text: `Next: ${entryWords(upcoming)} at ${at(upcoming)}`, action: "Open today", go: { tab: "plan", day: today } };
  }
  // After the trip: who is left to settle with, from the balances (open items only).
  const open = detail.balances.filter((b) => b.direction !== "even");
  if (open.length === 0) return null;
  const [first] = open;
  const text =
    open.length === 1
      ? first.direction === "you_owe"
        ? `You still owe ${first.person} ${balanceAmount(first)}`
        : first.direction === "owes_you"
          ? `${first.person} still owes you ${balanceAmount(first)}`
          : `Settle up with ${first.person}`
      : open.every((b) => b.direction === "owes_you")
        ? `${open.length} people still owe you`
        : `${open.length} people to settle up with`;
  return { text, action: "Settle up", go: { tab: "money" } };
}

/** What a balance comes to, as an unsigned amount: the net in the home currency, or when
 * a part has no exchange rate yet, each currency's amount side by side ("JPY 4,000 + SGD 20.00"). */
export function balanceAmount(b: Pick<Balance, "net" | "net_by_currency">): string {
  const unsigned = (m: { amount: string; currency: string }) => formatMoney({ ...m, amount: String(Math.abs(Number(m.amount))) });
  if (b.net) return unsigned(b.net);
  return b.net_by_currency.map(unsigned).join(" + ");
}

/** The gaps, first on a trip that's being planned. Nothing when it's all sorted. */
export function StillToSort({ detail, onFix, quiet = false }: { detail: TripDetail; onFix: (fix: Fix) => void; quiet?: boolean }) {
  const items = stillToSort(detail);
  if (items.length === 0) {
    return quiet ? null : (
      <p className="sorted-line" role="status">
        <Icon name="check" size={16} className="icon-inline" />
        All sorted: a place every night, a way there and a budget.
      </p>
    );
  }
  return (
    <section className="card to-sort" aria-labelledby="to-sort">
      <h2 id="to-sort">
        Still to sort · {items.length}
      </h2>
      <ul className="to-sort-list">
        {items.map((i) => (
          <li key={i.text}>
            <span className="to-sort-dot" aria-hidden="true" />
            <span className="wrap">{i.text}</span>
            <button type="button" className="btn btn-small" onClick={() => onFix(i.fix)} aria-label={`${i.action}: ${i.text}`}>
              {i.action}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

// The money summaries live with the rest of the Money tab; re-exported while the old page still imports them here.
