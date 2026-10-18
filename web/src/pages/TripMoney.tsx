import { type FormEvent, useState } from "react";

import { api, type Money, type Trip, type TripDetail } from "../api";
import { formatMoney } from "../format";
import { CountUp } from "../motion";
import { day } from "./TripBits";
import { tripBody } from "./TripEntry";
import { stageOf } from "./TripStage";

const amount = (m: Money | null) => (m ? Number(m.amount) : 0);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

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
        <h2 id="trip-spending">Where it goes</h2>
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

/** Every expense on the trip, each with a way to take it off. */
export function Expenses({ detail, onTakeOff }: { detail: TripDetail; onTakeOff: (transactionId: string) => void }) {
  return (
    <section className="card" aria-labelledby="trip-expenses">
      <div className="card-head">
        <h2 id="trip-expenses">Expenses</h2>
        <span className="caption">To count something else, like flights paid earlier, tell Nexus "add it to {detail.trip.destination}"</span>
      </div>
      {detail.items.length === 0 ? (
        <p className="state">None yet.</p>
      ) : (
        <ul className="feed money-list" aria-label="Trip expenses">
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
  );
}

/** The costs planned for the trip, by name, in the home currency. A planned cost is part
 * of the trip itself, so changing one resends the trip as the trip form would. */
async function savePlanned(trip: Trip, planned: Record<string, string>) {
  await api(`/travel/trips/${trip.id}`, { method: "PUT", body: tripBody(trip, { planned }) });
}

/** The + on the Money tab: one planned cost, a name and an amount. */
function PlannedForm({ trip, currency, onChange, onDone }: { trip: Trip; currency: string; onChange: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = name.trim() !== "" && Number(value) > 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await savePlanned(trip, { ...tripBody(trip).planned, [name.trim()]: String(Number(value)) });
      onChange();
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="planned-add">
      <div className="card-head">
        <h2 id="planned-add">Add a planned cost</h2>
        <span className="caption">Something you expect to pay for, like flights or a tour</span>
      </div>
      <form className="budget-add planned-form" onSubmit={(e) => void submit(e)} aria-label="Add a planned cost">
        <label className="field">
          Name
          <input className="input" value={name} maxLength={60} autoFocus onChange={(e) => setName(e.target.value)} placeholder="Flights, Tour, Visa…" />
        </label>
        <label className="field">
          Amount ({currency})
          <input className="input" value={value} inputMode="decimal" onChange={(e) => setValue(e.target.value)} placeholder="0" />
        </label>
        <button type="submit" className="btn btn-primary" disabled={!ready || busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn" onClick={onDone} disabled={busy}>
          Cancel
        </button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** What's planned to be paid for, each with a way to drop it. Nothing when there are none. */
function PlannedCosts({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const entries = Object.entries(trip.planned);
  if (entries.length === 0) return null;

  async function remove(name: string) {
    const { [name]: _gone, ...rest } = tripBody(trip).planned;
    setBusy(name);
    setError(null);
    try {
      await savePlanned(trip, rest);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove that");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card" aria-labelledby="planned-costs">
      <div className="card-head">
        <h2 id="planned-costs">Planned costs</h2>
        <span className="caption">Counted against the budget once they're spent</span>
      </div>
      <ul className="feed money-list" aria-label="Planned costs">
        {entries.map(([name, cost]) => (
          <li key={name} className="run-row">
            <span className="wrap">{name}</span>
            <span className="num">{formatMoney(cost)}</span>
            <button type="button" className="btn btn-small" disabled={busy !== null} onClick={() => void remove(name)} aria-label={`Remove planned cost ${name}`}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** The Money tab: the summary for where the trip is, then everything behind it, unfolded.
 * ``adding``: the tab's + was pressed (a planned cost). */
export function MoneyTab({ detail, onChange, adding, onAddDone }: { detail: TripDetail; onChange: () => void; adding: boolean; onAddDone: () => void }) {
  const stage = stageOf(detail);
  const [error, setError] = useState<string | null>(null);

  async function takeOff(transactionId: string) {
    setError(null);
    try {
      await api(`/travel/trips/${detail.trip.id}/expenses/${transactionId}`, { method: "DELETE" });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't take that off");
    }
  }

  return (
    <>
      {adding && <PlannedForm trip={detail.trip} currency={detail.spending.spent.currency} onChange={onChange} onDone={onAddDone} />}
      {/* After the trip, settling up comes first, then what it cost. */}
      {stage === "after" && <SettleUp detail={detail} />}
      {stage === "during" ? <SpendingNow detail={detail} /> : stage === "after" ? <TripTotals detail={detail} /> : <MoneyBar detail={detail} />}
      <Spending detail={detail} />
      <PlannedVsActual detail={detail} />
      <PlannedCosts trip={detail.trip} onChange={onChange} />
      <SetAside detail={detail} />
      {stage !== "after" && <SettleUp detail={detail} />}
      <Expenses detail={detail} onTakeOff={(t) => void takeOff(t)} />
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/** Before the trip: what's booked and spent against the budget, in one bar.
 * Without ``onOpen`` it has no Details button (the Money tab is already the details). */
export function MoneyBar({ detail, onOpen }: { detail: TripDetail; onOpen?: () => void }) {
  const budget = detail.trip.budget;
  const committed = amount(detail.spending.spent) + amount(detail.booked_unlogged);
  const currency = detail.spending.spent.currency;
  const percent = budget ? Math.min(100, Math.round((committed / Number(budget.amount)) * 100)) : 0;
  return (
    <section className="card money-bar" aria-labelledby="money-bar">
      <div className="money-bar-head">
        <h2 id="money-bar">
          Money
        </h2>
        {onOpen && (
          <button type="button" className="btn btn-ghost btn-small" onClick={onOpen}>
            Details
          </button>
        )}
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
      <h2 id="spending-now">
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
      <h2 id="trip-totals">
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
