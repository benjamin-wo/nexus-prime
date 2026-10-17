import { useState } from "react";

import type { Money, TripDetail } from "../api";
import { formatMoney } from "../format";
import { day } from "./TripBits";

export function Figure({ label, value, note }: { label: string; value: Money | null; note?: string }) {
  if (!value) return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd className="num">{formatMoney(value)}</dd>
      {note && <dd className="caption">{note}</dd>}
    </div>
  );
}

export function BudgetMeter({ percent }: { percent: number }) {
  const tone = percent >= 100 ? " meter-over" : percent >= 80 ? " meter-warn" : "";
  return (
    <div className={`meter${tone}`} role="progressbar" aria-label="Budget used" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  );
}

type TripCategory = TripDetail["spending"]["categories"][number];

/** One category's bar; tapping it lists the trip's expenses in it. */
export function SpendingRow({ category: c, biggest, items }: { category: TripCategory; biggest: number; items: TripDetail["items"] }) {
  const [open, setOpen] = useState(false);
  const id = `trip-cat-${c.name.replace(/\W+/g, "-")}`;
  const row = (
    <>
      <span className="wrap">{c.name}</span>
      <span className="bar-track">
        <span className="bar" style={{ width: `${(Number(c.spent.amount) / biggest) * 100}%` }} />
      </span>
      <span className="num">
        {formatMoney(c.spent)}
        {c.planned && <span className="caption"> of {formatMoney(c.planned)}</span>}
      </span>
    </>
  );
  if (items.length === 0) {
    return <li className="bar-row">{row}</li>;
  }
  return (
    <li className="bar-item">
      <button
        type="button"
        className="bar-row bar-toggle"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`${c.name}: ${formatMoney(c.spent)}${c.planned ? ` of ${formatMoney(c.planned)}` : ""}, ${items.length} ${items.length === 1 ? "expense" : "expenses"}`}
        onClick={() => setOpen(!open)}
      >
        {row}
        <span className="chevron" aria-hidden="true" />
      </button>
      {open && (
        <div className="peek" id={id}>
          <ul className="peek-list" aria-label={`${c.name} expenses`}>
            {items.map((i) => (
              <li key={i.transaction_id} className="peek-row">
                <span className="caption peek-day">{day(i.day)}</span>
                <span className="wrap">{i.counterparty ?? "Expense"}</span>
                <span className="num">
                  {formatMoney(i.amount)}
                  {i.home && i.home.currency !== i.amount.currency && <span className="caption"> ({formatMoney(i.home)})</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

export function Spending({ detail }: { detail: TripDetail }) {
  const { trip, spending: s } = detail;
  const biggest = Math.max(1, ...s.categories.map((c) => Number(c.spent.amount)));
  return (
    <section className="card" aria-labelledby="trip-spending">
      <div className="card-head">
        <h2 id="trip-spending">Trip spending</h2>
        <span className="caption">Your share, in {s.spent.currency} at each day's rate</span>
      </div>
      {trip.budget && s.percent !== null && (
        <div className="budget solo">
          <div className="budget-head">
            <span>
              {formatMoney(s.spent)} of {formatMoney(trip.budget)}
            </span>
            <span className={`num ${s.percent >= 100 ? "budget-state-over" : s.percent >= 80 ? "budget-state-warn" : ""}`}>{s.percent}%</span>
          </div>
          <BudgetMeter percent={s.percent} />
        </div>
      )}
      <dl className="totals" aria-label="Trip totals">
        <Figure label="Spent" value={s.spent} note={Number(s.before.amount) > 0 ? `${formatMoney(s.before)} before the trip` : undefined} />
        {s.left && <Figure label={Number(s.left.amount) < 0 ? "Over budget" : "Left"} value={{ ...s.left, amount: String(Math.abs(Number(s.left.amount))) }} />}
        <Figure label="Today" value={s.today} />
        <Figure label="Average a day" value={s.per_day} />
        <Figure label="To stay on budget" value={s.per_day_left} note="a day, for the rest of the trip" />
        <Figure
          label="Booked"
          value={detail.booked}
          note={detail.booked_unlogged && Number(detail.booked_unlogged.amount) > 0 ? `${formatMoney(detail.booked_unlogged)} not logged yet` : undefined}
        />
        {detail.booked && <Figure label="Still to spend" value={detail.to_spend} note="the budget less what's spent and booked" />}
      </dl>
      {s.categories.length > 0 && (
        <ul className="bars" aria-label="Biggest categories">
          {s.categories.slice(0, trip.status === "finished" ? undefined : 5).map((c) => (
            <SpendingRow
              key={c.name}
              category={c}
              biggest={biggest}
              items={detail.items.filter((i) => (i.category ?? "Uncategorised") === c.name)}
            />
          ))}
        </ul>
      )}
      {detail.items.length === 0 && (
        <p className="state">
          Nothing spent yet. Expenses in {trip.currency} between {day(trip.start)} and {day(trip.end)} count by themselves.
        </p>
      )}
      {s.unconverted > 0 && <p className="caption">{s.unconverted} expenses have no exchange rate yet and aren't counted.</p>}
    </section>
  );
}

export function PlannedVsActual({ detail }: { detail: TripDetail }) {
  const rows = detail.spending.categories.filter((c) => c.planned);
  if (detail.trip.status !== "finished" || (!detail.trip.budget && rows.length === 0)) return null;
  return (
    <section className="card" aria-labelledby="planned-actual">
      <div className="card-head">
        <h2 id="planned-actual">Planned against actual</h2>
      </div>
      <div className="table-wrap">
      <table className="holdings">
        <thead>
          <tr>
            <th scope="col">What</th>
            <th scope="col" className="num">
              Planned
            </th>
            <th scope="col" className="num">
              Actual
            </th>
          </tr>
        </thead>
        <tbody>
          {detail.trip.budget && (
            <tr>
              <td>Whole trip</td>
              <td className="num">{formatMoney(detail.trip.budget)}</td>
              <td className="num">{formatMoney(detail.spending.spent)}</td>
            </tr>
          )}
          {rows.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              <td className="num">{c.planned && formatMoney(c.planned)}</td>
              <td className="num">{formatMoney(c.spent)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </section>
  );
}

export function SetAside({ detail }: { detail: TripDetail }) {
  const { trip, saving: a } = detail;
  if (trip.status !== "upcoming") return null;
  return (
    <section className="card" aria-labelledby="set-aside">
      <div className="card-head">
        <h2 id="set-aside">Setting money aside</h2>
      </div>
      {!a.pay_schedule ? (
        <p className="muted">Set your pay schedule (Accounting, Plan) and Nexus can plan an amount to put aside each payday.</p>
      ) : a.per_payday ? (
        <>
          <p>
            {formatMoney(a.per_payday)} each payday: about {a.saved && formatMoney(a.saved)} so far, {a.by_start && formatMoney(a.by_start)} by the
            trip ({a.paydays_left} {a.paydays_left === 1 ? "payday" : "paydays"} left
            {a.next_payday && `, next ${day(a.next_payday)}`}).
          </p>
          {a.covers_budget === false && a.suggested && (
            <p className="budget-state-warn">That's short of the budget: {formatMoney(a.suggested)} each payday would cover it.</p>
          )}
          {a.covers_budget && <p className="budget-state-ok-strong">That covers the budget.</p>}
          {a.fits === false && <p className="budget-state-over">With it, the cash-flow forecast to the trip goes below zero.</p>}
          {a.fits && <p className="caption">It fits the cash-flow forecast, where it shows on each payday.</p>}
        </>
      ) : a.suggested ? (
        <p className="muted">
          Put aside about {formatMoney(a.suggested)} on each of the {a.paydays_left} paydays before the trip to cover the budget. Edit the trip
          to plan it.
        </p>
      ) : (
        <p className="muted">Add a budget, or an amount to set aside, and Nexus plans it into your paydays.</p>
      )}
    </section>
  );
}

export function SettleUp({ detail }: { detail: TripDetail }) {
  if (detail.owed.length === 0 && detail.trip.companions.length === 0) return null;
  return (
    <section className="card" aria-labelledby="settle-up">
      <div className="card-head">
        <h2 id="settle-up">Settle up</h2>
      </div>
      {detail.owed.length === 0 ? (
        <p className="muted">Nobody owes you for this trip. Split a bill in chat ("split the hotel with Ann") and it shows here.</p>
      ) : (
        <ul className="feed" aria-label="Still owed">
          {detail.owed.map((o) => (
            <li key={o.name} className="run-row">
              <span className="wrap">{o.name}</span>
              <span className="num">
                {o.amounts.map(formatMoney).join(" + ")}
                {o.home && o.amounts.some((m) => m.currency !== o.home?.currency) && <span className="caption"> (about {formatMoney(o.home)})</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Everything about the trip's money, folded away until it's wanted. */
export function MoneyDetails({ detail, open, onToggle, onTakeOff, title = "Money details" }: {
  detail: TripDetail;
  open: boolean;
  onToggle: (open: boolean) => void;
  onTakeOff: (transactionId: string) => void;
  title?: string;
}) {
  return (
    <details id="trip-money-details" className="card section" open={open} onToggle={(e) => onToggle((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <h2>{title}</h2>
        <span className="caption">{detail.items.length ? `${detail.items.length} expenses` : "Spending, set-aside, settle-up"}</span>
      </summary>
      <div className="money-details">
        <Spending detail={detail} />
        <PlannedVsActual detail={detail} />
        <SetAside detail={detail} />
        {detail.trip.status !== "finished" && <SettleUp detail={detail} />}
        <section className="card" aria-labelledby="trip-expenses">
          <div className="card-head">
            <h2 id="trip-expenses">Expenses</h2>
            <span className="caption">To count something else, like flights paid earlier, tell Nexus "add it to {detail.trip.destination}"</span>
          </div>
          {detail.items.length === 0 ? (
            <p className="state">None yet.</p>
          ) : (
            <ul className="feed" aria-label="Trip expenses">
              {detail.items.map((i) => (
                <li key={i.transaction_id} className="run-row">
                  <span className="wrap">
                    {i.counterparty ?? "Expense"}
                    <br />
                    <span className="caption">
                      {day(i.day)}
                      {i.category && ` · ${i.category}`}
                      {i.linked && " · added by hand"}
                    </span>
                  </span>
                  <span className="num">
                    {formatMoney(i.amount)}
                    {i.home && i.home.currency !== i.amount.currency && <span className="caption"> ({formatMoney(i.home)})</span>}
                  </span>
                  <button type="button" className="btn btn-small" onClick={() => onTakeOff(i.transaction_id)} aria-label={`Take ${i.counterparty ?? "this expense"} off the trip`}>
                    Take off
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </details>
  );
}
