import type { Money, TripDetail } from "../api";
import { formatMoney, formatShortDate } from "../format";
import { CountUp } from "../motion";

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
const amount = (m: Money | null) => (m ? Number(m.amount) : 0);
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

/** The gaps, first on a trip that's being planned. Nothing when it's all sorted. */
export function StillToSort({ detail, onFix, quiet = false }: { detail: TripDetail; onFix: (fix: Fix) => void; quiet?: boolean }) {
  const items = stillToSort(detail);
  if (items.length === 0) {
    return quiet ? null : (
      <p className="sorted-line" role="status">
        <span aria-hidden="true">✓</span> All sorted: a place every night, a way there and a budget.
      </p>
    );
  }
  return (
    <section className="card to-sort" aria-labelledby="to-sort">
      <h2 id="to-sort" className="eyebrow">
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

/** Before the trip: what's booked and spent against the budget, in one bar. */
export function MoneyBar({ detail, onOpen }: { detail: TripDetail; onOpen: () => void }) {
  const budget = detail.trip.budget;
  const committed = amount(detail.spending.spent) + amount(detail.booked_unlogged);
  const currency = detail.spending.spent.currency;
  const percent = budget ? Math.min(100, Math.round((committed / Number(budget.amount)) * 100)) : 0;
  return (
    <section className="card money-bar" aria-labelledby="money-bar">
      <div className="money-bar-head">
        <h2 id="money-bar" className="eyebrow">
          Money
        </h2>
        <button type="button" className="btn btn-ghost btn-small" onClick={onOpen}>
          Details
        </button>
      </div>
      <p className="money-bar-figure">
        <CountUp value={formatMoney({ amount: String(committed), currency })} />
        <span className="caption"> {budget ? `of ${formatMoney(budget)}` : "booked and spent · no budget yet"}</span>
      </p>
      {budget && (
        <div className={`meter${committed > Number(budget.amount) ? " meter-over" : ""}`} aria-hidden="true">
          <span style={{ width: `${percent}%` }} />
        </div>
      )}
      <p className="caption">
        {detail.booked ? `Booked ${formatMoney(detail.booked)}` : "Nothing booked yet"}
        {amount(detail.spending.spent) > 0 && ` · spent ${formatMoney(detail.spending.spent)}`}
      </p>
    </section>
  );
}

/** While the trip is on: spent against the budget, what's left each day, and what's
 * been spent in the trip's own currency (logged on Telegram). */
export function SpendingNow({ detail }: { detail: TripDetail }) {
  const s = detail.spending;
  const t = detail.trip;
  const budget = t.budget;
  const local = detail.items.filter((i) => i.amount.currency === t.currency).reduce((sum, i) => sum + Number(i.amount.amount), 0);
  const daysLeft = Math.max(t.days - (t.day_number ?? 1) + 1, 1);
  const over = (s.percent ?? 0) > 100;
  return (
    <section className="card spending-now" aria-labelledby="spending-now">
      <h2 id="spending-now" className="eyebrow">
        Spent so far
      </h2>
      <p className="money-bar-figure">
        <CountUp value={formatMoney(s.spent)} />
        {budget && <span className="caption"> of {formatMoney(budget)}</span>}
      </p>
      {budget && (
        <div className={`meter${over ? " meter-over" : ""}`} aria-hidden="true">
          <span style={{ width: `${Math.min(s.percent ?? 0, 100)}%` }} />
        </div>
      )}
      <p className="caption">
        {s.per_day_left
          ? `${formatMoney(s.per_day_left)} a day left for ${plural(daysLeft, "day")}`
          : budget
            ? over
              ? "Over budget"
              : "On budget"
            : "No budget set"}
        {local > 0 && ` · ${formatMoney({ amount: String(local), currency: t.currency })} spent in ${t.currency}`}
        {s.today && amount(s.today) > 0 && ` · ${formatMoney(s.today)} today`}
      </p>
      <p className="caption">Log what you spend on Telegram: "ramen 1200 yen".</p>
    </section>
  );
}

/** After the trip: the total against the budget, by category. */
export function TripTotals({ detail }: { detail: TripDetail }) {
  const s = detail.spending;
  const budget = detail.trip.budget;
  const total = amount(s.spent);
  const diff = budget ? Math.round(((total - Number(budget.amount)) / Number(budget.amount)) * 100) : null;
  const cats = [...s.categories].sort((a, b) => amount(b.spent) - amount(a.spent));
  return (
    <section className="card trip-totals" aria-labelledby="trip-totals">
      <h2 id="trip-totals" className="eyebrow">
        The trip in numbers
      </h2>
      <p className="money-bar-figure">
        <CountUp value={formatMoney(s.spent)} />
        {budget && (
          <span className="caption">
            {" "}
            of {formatMoney(budget)}
            {diff !== null && diff !== 0 && ` · ${Math.abs(diff)}% ${diff > 0 ? "over" : "under"}`}
          </span>
        )}
      </p>
      {cats.length > 0 && (
        <ul className="totals-list" aria-label="By category">
          {cats.map((c) => (
            <li key={c.name}>
              <span>{c.name}</span>
              <span className="num">{formatMoney(c.spent)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
