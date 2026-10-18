import { type FormEvent, useEffect, useState } from "react";

import {
  api,
  type Balance,
  type BalancePart,
  type Money,
  type PaidByOther,
  type PaidByOtherBody,
  type SettleResult,
  type SplitBody,
  type SplitResult,
  type Trip,
  type TripDetail,
} from "../api";
import { formatMoney, formatWithHome } from "../format";
import { CountUp } from "../motion";
import { day } from "./TripBits";
import { tripBody } from "./TripEntry";
import { balanceAmount, stageOf } from "./TripStage";

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
                  {formatWithHome(i.amount, i.home)}
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

const positive = (m: Money | null): m is Money => m !== null && Number(m.amount) > 0;

/** The set-aside plan in a sentence: "SGD 500.00 each payday: about SGD 100.00 so far, SGD 1,500.00
 * by the trip (3 paydays left, next 25 Oct)." What's saved so far and what it comes to by the trip
 * are left out when missing or zero; the rest still reads as one sentence. */
export function setAsideText(
  a: Pick<TripDetail["saving"], "per_payday" | "saved" | "by_start" | "paydays_left">,
  nextPayday: string | null,
): string {
  if (!a.per_payday) return "";
  const progress = [positive(a.saved) && `about ${formatMoney(a.saved)} so far`, positive(a.by_start) && `${formatMoney(a.by_start)} by the trip`].filter(Boolean);
  const left = `${plural(a.paydays_left, "payday")} left${nextPayday ? `, next ${nextPayday}` : ""}`;
  return `${formatMoney(a.per_payday)} each payday${progress.length > 0 ? `: ${progress.join(", ")}` : ""} (${left}).`;
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
      ) : positive(a.per_payday) ? (
        <>
          <p>{setAsideText(a, a.next_payday ? day(a.next_payday) : null)}</p>
          {a.covers_budget === false && positive(a.suggested) && (
            <p className="budget-state-warn">That's short of the budget: {formatMoney(a.suggested)} each payday would cover it.</p>
          )}
          {a.covers_budget && <p className="budget-state-ok-strong">That covers the budget.</p>}
          {a.fits === false && <p className="budget-state-over">With it, the cash-flow forecast to the trip goes below zero.</p>}
          {a.fits && <p className="caption">It fits the cash-flow forecast, where it shows on each payday.</p>}
        </>
      ) : positive(a.suggested) ? (
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

// --- Travellers, splitting, costs others paid, and settling up --------------------------

const failure = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);
const unsigned = (m: Money): Money => ({ ...m, amount: String(Math.abs(Number(m.amount))) });

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

const moneyList = (list: Money[]) => list.map(formatMoney).join(" + ");

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

/** Names as chips after "You", with a field to add more. It saves nothing: ``onChange`` gets
 * the new list (the trip form keeps it for Save, the Travellers card saves it at once).
 * ``addOnBlur``: a name typed and left behind is added, so Save doesn't lose it. */
export function NameChips({
  names,
  onChange,
  busy = false,
  addOnBlur = false,
  max = 12,
}: {
  names: string[];
  onChange: (names: string[]) => void;
  busy?: boolean;
  addOnBlur?: boolean;
  max?: number;
}) {
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  function add() {
    const found = text.split(",").map((n) => n.trim()).filter(Boolean);
    if (found.length === 0) return;
    const next = [...names];
    for (const name of found) {
      if (!next.some((n) => n.toLowerCase() === name.toLowerCase()) && name.toLowerCase() !== "you") next.push(name);
    }
    if (next.length > max) {
      setProblem(`At most ${max} people on a trip`);
      return;
    }
    setProblem(null);
    setText("");
    if (next.length !== names.length) onChange(next);
  }

  return (
    <div className="name-chips-wrap">
      <ul className="name-chips" aria-label="Who's going">
        <li className="name-chip name-chip-you">You</li>
        {names.map((n) => (
          <li key={n} className="name-chip">
            <span className="wrap">{n}</span>
            <button type="button" className="chip-x" disabled={busy} aria-label={`Remove ${n}`} onClick={() => onChange(names.filter((x) => x !== n))}>
              <span aria-hidden="true">×</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="name-add">
        <label className="field">
          Add a traveller
          <input
            className="input"
            value={text}
            maxLength={100}
            disabled={busy}
            placeholder="A name"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                add();
              }
            }}
            onBlur={() => addOnBlur && add()}
          />
        </label>
        {!addOnBlur && (
          <button type="button" className="btn" disabled={busy || text.trim() === ""} onClick={add}>
            Add
          </button>
        )}
      </div>
      {problem && (
        <p className="error-text" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}

/** Who's going, saved with the trip as people are added or removed. */
function TravellersCard({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(companions: string[]) {
    setBusy(true);
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}`, { method: "PUT", body: tripBody(trip, { companions }) });
      onChange();
    } catch (e) {
      setError(failure(e, "Couldn't save that"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="trip-travellers">
      <div className="card-head">
        <h2 id="trip-travellers">Travellers</h2>
        <span className="caption">Add the people going to split costs and settle up with them</span>
      </div>
      <NameChips names={trip.companions} busy={busy} onChange={(names) => void save(names)} />
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** Costs not split yet, with a way to split each, split them all, or keep one as just mine. */
function SplitCard({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const { trip } = detail;
  const home = detail.spending.spent.currency;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [outcome, setOutcome] = useState<{ result: SplitResult; names: Map<string, string> } | null>(null);
  const others = trip.companions;
  if (others.length === 0) return null;
  const items = detail.to_split;
  const kept = detail.items.filter((i) => detail.just_mine.includes(i.transaction_id));

  async function run(work: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      await work();
      onChange();
    } catch (e) {
      setError(failure(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  const split = (body: SplitBody) =>
    run(async () => {
      const names = new Map(items.map((i) => [i.transaction_id, i.counterparty ?? "Expense"]));
      const result = await api<SplitResult>(`/travel/trips/${trip.id}/split`, { method: "POST", body });
      setConfirming(false);
      setOutcome({ result, names });
    }, "Couldn't split that");

  const keepMine = (ids: string[], keep: boolean) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}/keep-mine`, { method: "POST", body: { transaction_ids: ids, keep } });
      setOutcome(null);
    }, "Couldn't change that");

  const setEvenly = (on: boolean) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}/split-evenly`, { method: "PUT", body: { on } });
      setConfirming(false);
    }, "Couldn't change that");

  return (
    <section className="card" aria-labelledby="trip-split">
      <div className="card-head">
        <h2 id="trip-split">Split costs</h2>
        <span className="caption">With {joinNames(others)}</span>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={trip.split_evenly}
        aria-describedby="trip-split-note"
        className="switch-row"
        disabled={busy}
        onClick={() => void setEvenly(!trip.split_evenly)}
      >
        <span>Split costs evenly</span>
        <span className="switch-track" aria-hidden="true">
          <span className="switch-thumb" />
        </span>
      </button>
      <p className="caption" id="trip-split-note">
        {trip.split_evenly
          ? "Costs on this trip are offered for an even split. Nothing changes until you split them."
          : "Off: costs aren't offered for splitting here. You can still split a bill in chat."}
      </p>
      {trip.split_evenly &&
        (items.length === 0 ? (
          <p className="state">Nothing left to split.</p>
        ) : (
          <>
            <ul className="feed money-list" aria-label="To split">
              {items.map((i) => {
                const name = i.counterparty ?? "this cost";
                return (
                  <li key={i.transaction_id} className="run-row cost-row">
                    <span className="wrap">
                      {i.counterparty ?? "Expense"}
                      <br />
                      <span className="caption">{day(i.day)}</span>
                    </span>
                    <span className="num">{formatMoney(i.amount)}</span>
                    <span className="row-actions">
                      <button type="button" className="btn btn-small" disabled={busy} aria-label={`Split ${name} evenly`} onClick={() => void split({ transaction_ids: [i.transaction_id] })}>
                        Split
                      </button>
                      <button type="button" className="btn btn-small" disabled={busy} aria-label={`Keep ${name} as just mine`} onClick={() => void keepMine([i.transaction_id], true)}>
                        Just mine
                      </button>
                    </span>
                  </li>
                );
              })}
            </ul>
            {confirming ? (
              <div className="confirm-box" role="group" aria-label="Confirm splitting all">
                <p>{splitConfirmText(items, others, home)}</p>
                <div className="people-actions">
                  <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void split({ all: true })}>
                    {busy ? "Splitting…" : "Split them"}
                  </button>
                  <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="people-actions">
                <button type="button" className="btn btn-primary" disabled={busy} onClick={() => setConfirming(true)}>
                  Split all evenly
                </button>
              </div>
            )}
          </>
        ))}
      {outcome && (
        <div className="split-outcome" role="status">
          {outcome.result.done.length > 0 && (
            <p>
              Split {plural(outcome.result.done.length, "cost")} evenly with {joinNames(outcome.result.with_people)}. Your share is{" "}
              {moneyList(sumByCurrency(outcome.result.done.map((d) => d.own_share)))}.
            </p>
          )}
          {outcome.result.skipped.length > 0 && (
            <>
              <p>Left alone:</p>
              <ul>
                {outcome.result.skipped.map((s) => (
                  <li key={s.transaction_id}>
                    {outcome.names.get(s.transaction_id) ?? "Expense"}: {s.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {trip.split_evenly && kept.length > 0 && (
        <details className="more kept-mine">
          <summary>Kept as just mine ({kept.length})</summary>
          <ul className="feed money-list" aria-label="Kept as just mine">
            {kept.map((i) => (
              <li key={i.transaction_id} className="run-row cost-row">
                <span className="wrap">
                  {i.counterparty ?? "Expense"}
                  <br />
                  <span className="caption">{day(i.day)}</span>
                </span>
                <span className="num">{formatMoney(i.amount)}</span>
                <button type="button" className="btn btn-small" disabled={busy} aria-label={`Offer ${i.counterparty ?? "this cost"} for splitting again`} onClick={() => void keepMine([i.transaction_id], false)}>
                  Offer again
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

const today = () => new Date().toLocaleDateString("en-CA");

/** Someone else paid for something and the user shares it: who, how much, what, when and who
 * shares it. Adds a payment, or changes ``payment``. */
function PaidForm({ trip, home, payment, onChange, onDone }: { trip: Trip; home: string; payment?: PaidByOther; onChange: () => void; onDone: () => void }) {
  const travellers = payment && !trip.companions.includes(payment.person) ? [payment.person, ...trip.companions] : trip.companions;
  const [who, setWho] = useState(payment?.person ?? trip.companions[0] ?? "");
  const [value, setValue] = useState(payment ? String(Number(payment.amount.amount)) : "");
  const [currency, setCurrency] = useState(payment?.amount.currency ?? home);
  const [note, setNote] = useState(payment?.note ?? "");
  const [paidOn, setPaidOn] = useState(payment?.paid_on ?? today());
  const sharers = travellers.filter((n) => n !== who);
  // Everyone shares by default; these are the ones taken out.
  const [without, setWithout] = useState<string[]>(payment ? travellers.filter((n) => n !== payment.person && !payment.split_with.includes(n)) : []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = who !== "" && Number(value.replace(/,/g, "")) > 0 && /^[A-Za-z]{3}$/.test(currency.trim());

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    const body: PaidByOtherBody = {
      person: who,
      amount: value.replace(/,/g, "").trim(),
      currency: currency.trim().toUpperCase(),
      note: note.trim() || null,
      paid_on: paidOn || null,
      split_with: sharers.filter((n) => !without.includes(n)),
    };
    try {
      await api(`/travel/trips/${trip.id}/paid-by-others${payment ? `/${payment.id}` : ""}`, { method: payment ? "PUT" : "POST", body });
      onChange();
      onDone();
    } catch (e) {
      setError(failure(e, "Couldn't save that"));
      setBusy(false);
    }
  }

  const label = payment ? `Change what ${payment.person} paid` : "Someone else paid";
  return (
    <form className="paid-form" onSubmit={(e) => void submit(e)} aria-label={label}>
      <div className="paid-grid">
        <label className="field">
          Who paid
          <select className="input" value={who} onChange={(e) => setWho(e.target.value)} autoFocus>
            {travellers.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Amount
          <input className="input" value={value} inputMode="decimal" onChange={(e) => setValue(e.target.value)} placeholder="0" />
        </label>
        <label className="field">
          Currency
          <input className="input" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
        </label>
        <label className="field">
          What it was for
          <input className="input" value={note} maxLength={100} onChange={(e) => setNote(e.target.value)} placeholder="Ryokan, taxi, dinner…" />
        </label>
        <label className="field">
          Date
          <input className="input" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </label>
      </div>
      {sharers.length > 0 && (
        <fieldset className="field-group">
          <legend>Split with (you're in it too)</legend>
          <div className="check-list">
            {sharers.map((n) => (
              <label key={n} className="check-row">
                <input
                  type="checkbox"
                  checked={!without.includes(n)}
                  onChange={(e) => setWithout(e.target.checked ? without.filter((x) => x !== n) : [...without, n])}
                />
                {n}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <div className="people-actions">
        <button type="submit" className="btn btn-primary" disabled={!ready || busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn" onClick={onDone} disabled={busy}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

/** What fellow travellers paid for, each with a way to change or remove it. Settled ones stay, muted. */
function PaidByOthers({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const { trip, paid_by_others: payments } = detail;
  const home = detail.spending.spent.currency;
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (payments.length === 0) return null;

  async function remove(p: PaidByOther) {
    setBusy(true);
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}/paid-by-others/${p.id}`, { method: "DELETE" });
      setRemoving(null);
      onChange();
    } catch (e) {
      setError(failure(e, "Couldn't remove that"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="trip-paid">
      <div className="card-head">
        <h2 id="trip-paid">Paid by others</h2>
        <span className="caption">Your share is what you owe them</span>
      </div>
      <ul className="feed money-list" aria-label="Paid by others">
        {payments.map((p) => {
          const what = `${p.person}${p.note ? `, ${p.note}` : ""}`;
          if (editing === p.id) {
            return (
              <li key={p.id}>
                <PaidForm trip={trip} home={home} payment={p} onChange={onChange} onDone={() => setEditing(null)} />
              </li>
            );
          }
          return (
            <li key={p.id} className={`paid-row${p.settled ? " is-settled" : ""}`}>
              <div className="run-row cost-row">
                <span className="wrap">
                  {p.person} paid{p.note ? ` for ${p.note}` : ""}
                  <br />
                  <span className="caption">
                    {day(p.paid_on)} · split with you{p.split_with.length > 0 ? `, ${joinNames(p.split_with)}` : ""}
                    {p.settled && " · settled"}
                  </span>
                </span>
                <span className="num">
                  {formatMoney(p.amount)}
                  <br />
                  <span className="caption">your share {formatMoney(p.my_share)}</span>
                </span>
                {!p.settled && removing !== p.id && (
                  <span className="row-actions">
                    <button type="button" className="btn btn-small" aria-label={`Change what ${what} paid`} onClick={() => setEditing(p.id)}>
                      Edit
                    </button>
                    <button type="button" className="btn btn-small" aria-label={`Remove what ${what} paid`} onClick={() => setRemoving(p.id)}>
                      Remove
                    </button>
                  </span>
                )}
              </div>
              {removing === p.id && (
                <div className="confirm-box" role="group" aria-label={`Remove what ${what} paid`}>
                  <p>Remove this? It won't count towards what you owe {p.person}.</p>
                  <div className="people-actions">
                    <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void remove(p)}>
                      Remove
                    </button>
                    <button type="button" className="btn" disabled={busy} onClick={() => setRemoving(null)}>
                      Keep
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function BalanceParts({ b, id }: { b: Balance; id: string }) {
  const line = (p: BalancePart, fallback: string) => (
    <li key={`${p.kind}-${p.id}`} className="peek-row">
      <span className="caption peek-day">{p.on ? day(p.on) : ""}</span>
      <span className="wrap">{p.label ?? fallback}</span>
      <span className="num">
        {formatWithHome(p.amount, p.home)}
      </span>
    </li>
  );
  return (
    <div className="peek" id={id}>
      {b.owes_you.length > 0 && (
        <>
          <h3 className="caption">{b.person} owes you</h3>
          <ul className="peek-list" aria-label={`What ${b.person} owes you`}>
            {b.owes_you.map((p) => line(p, "Shared bill"))}
          </ul>
        </>
      )}
      {b.you_owe.length > 0 && (
        <>
          <h3 className="caption">You owe {b.person}</h3>
          <ul className="peek-list" aria-label={`What you owe ${b.person}`}>
            {b.you_owe.map((p) => line(p, `Paid by ${b.person}`))}
          </ul>
        </>
      )}
    </div>
  );
}

/** One person: where you stand, the items behind it, and Mark settled (confirmed first). */
function BalanceRow({ trip, b, onSettled }: { trip: Trip; b: Balance; onSettled: (result: SettleResult) => void }) {
  const key = b.person.replace(/\W+/g, "-");
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [log, setLog] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasParts = b.owes_you.length + b.you_owe.length > 0;
  const hasShare = b.you_owe.length > 0;

  async function settle() {
    setBusy(true);
    setError(null);
    try {
      const result = await api<SettleResult>(`/travel/trips/${trip.id}/settle`, {
        method: "POST",
        body: { person: b.person, log: hasShare && log },
      });
      onSettled(result);
    } catch (e) {
      setError(failure(e, "Couldn't mark that settled"));
      setBusy(false);
    }
  }

  return (
    <li className="settle-row">
      <div className="settle-head">
        {hasParts ? (
          <button type="button" className="settle-main" aria-expanded={open} aria-controls={`settle-parts-${key}`} onClick={() => setOpen(!open)}>
            <span className="wrap">{balanceWords(b)}</span>
            <span className="chevron" aria-hidden="true" />
          </button>
        ) : (
          <span className="settle-main wrap">{balanceWords(b)}</span>
        )}
        {hasParts && !confirming && (
          <button type="button" className="btn btn-small" aria-label={`Mark settled with ${b.person}`} onClick={() => setConfirming(true)}>
            Mark settled
          </button>
        )}
      </div>
      {b.net === null && b.net_by_currency.length > 0 && (
        <p className="caption">Some of this is in other currencies with no exchange rate yet, so it isn't added into one amount.</p>
      )}
      {open && <BalanceParts b={b} id={`settle-parts-${key}`} />}
      {confirming && (
        <div className="confirm-box" role="group" aria-label={`Settle up with ${b.person}`}>
          <p>{settleConfirmText(b, hasShare && log)}</p>
          {hasShare && (
            <label className="check-row">
              <input type="checkbox" checked={log} disabled={busy} onChange={(e) => setLog(e.target.checked)} />
              Also record my share as spent
            </label>
          )}
          <div className="people-actions">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void settle()}>
              {busy ? "Recording…" : "Yes, mark settled"}
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** One row per person you split with: what they owe you net of what you owe them. */
export function SettleUp({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const [done, setDone] = useState<string[]>([]);
  const { balances, trip } = detail;
  if (balances.length === 0 && done.length === 0 && trip.companions.length === 0) return null;
  return (
    <section className="card" aria-labelledby="settle-up">
      <div className="card-head">
        <h2 id="settle-up">Settle up</h2>
        <span className="caption">Nexus records what you say happened. It doesn't move money.</span>
      </div>
      {done.length > 0 && (
        <div className="split-outcome" role="status">
          {done.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      )}
      {balances.length === 0 ? (
        <p className="state">Nothing left to settle.</p>
      ) : (
        <ul className="feed settle-list" aria-label="Still to settle">
          {balances.map((b) => (
            <BalanceRow
              key={b.person}
              trip={trip}
              b={b}
              onSettled={(result) => {
                setDone((was) => [...was, settledText(result)]);
                onChange();
              }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/** The + on the Money tab, once someone else is going: a planned cost, or a cost someone else paid. */
function AddChoice({ onPick, onCancel }: { onPick: (kind: "planned" | "paid") => void; onCancel: () => void }) {
  return (
    <section className="card" aria-labelledby="add-choice">
      <div className="card-head">
        <h2 id="add-choice">What are you adding?</h2>
      </div>
      <div className="people-actions choice-actions">
        <button type="button" className="btn" onClick={() => onPick("planned")}>
          A planned cost
        </button>
        <button type="button" className="btn" onClick={() => onPick("paid")}>
          Someone else paid
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}

function PaidAdd({ trip, home, onChange, onDone }: { trip: Trip; home: string; onChange: () => void; onDone: () => void }) {
  return (
    <section className="card" aria-labelledby="paid-add">
      <div className="card-head">
        <h2 id="paid-add">Someone else paid</h2>
        <span className="caption">Your share is what you owe them. Nothing is added to your spending until you settle up.</span>
      </div>
      <PaidForm trip={trip} home={home} onChange={onChange} onDone={onDone} />
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
                {formatWithHome(i.amount, i.home)}
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
 * ``adding``: the tab's + was pressed: a planned cost, or (with other travellers) a choice
 * between that and a cost someone else paid. */
export function MoneyTab({ detail, onChange, adding, onAddDone }: { detail: TripDetail; onChange: () => void; adding: boolean; onAddDone: () => void }) {
  const stage = stageOf(detail);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"planned" | "paid" | null>(null);
  const home = detail.spending.spent.currency;
  const hasOthers = detail.trip.companions.length > 0;
  useEffect(() => {
    if (!adding) setKind(null);
  }, [adding]);
  const adds = adding ? (hasOthers ? kind : "planned") : null;

  async function takeOff(transactionId: string) {
    setError(null);
    try {
      await api(`/travel/trips/${detail.trip.id}/expenses/${transactionId}`, { method: "DELETE" });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't take that off");
    }
  }

  const splitting = (
    <>
      <SplitCard detail={detail} onChange={onChange} />
      <PaidByOthers detail={detail} onChange={onChange} />
    </>
  );
  return (
    <>
      {adding && hasOthers && kind === null && <AddChoice onPick={setKind} onCancel={onAddDone} />}
      {adds === "planned" && <PlannedForm trip={detail.trip} currency={home} onChange={onChange} onDone={onAddDone} />}
      {adds === "paid" && <PaidAdd trip={detail.trip} home={home} onChange={onChange} onDone={onAddDone} />}
      {/* After the trip, settling up comes first, then what it cost. */}
      {stage === "after" && (
        <>
          <SettleUp detail={detail} onChange={onChange} />
          {splitting}
        </>
      )}
      {stage === "during" ? <SpendingNow detail={detail} /> : stage === "after" ? <TripTotals detail={detail} /> : <MoneyBar detail={detail} />}
      <Spending detail={detail} />
      <PlannedVsActual detail={detail} />
      <PlannedCosts trip={detail.trip} onChange={onChange} />
      <SetAside detail={detail} />
      <TravellersCard trip={detail.trip} onChange={onChange} />
      {stage !== "after" && (
        <>
          {splitting}
          <SettleUp detail={detail} onChange={onChange} />
        </>
      )}
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
        {positive(detail.booked) ? `Booked ${formatMoney(detail.booked)}` : "Nothing booked yet"}
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
        {positive(s.per_day_left)
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
