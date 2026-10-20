import { type FormEvent, type ReactNode, useEffect, useState } from "react";

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
  type ToSplit,
  type Trip,
  type TripDetail,
  type TripSaving,
  type TripSpending,
} from "../api";
import { Icon } from "../components/Icon";
import { formatMoney, formatWithHome } from "../format";
import { CountUp } from "../motion";
import { day } from "./TripBits";
import { tripBody } from "./TripEntry";
import { balanceAmount, stageOf } from "./TripStage";

const amount = (m: Money | null) => (m ? Number(m.amount) : 0);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const moneyOf = (value: number, currency: string): Money => ({ amount: String(Math.round(value * 100) / 100), currency });
const sameName = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

type TripCategory = TripSpending["categories"][number];

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

/** Spending by category (each opening to its expenses), and after the trip planned against actual. */
function WhereItGoes({ detail }: { detail: TripDetail }) {
  const { trip, spending: s } = detail;
  if (!s) return null; // a member of the trip gets no money
  const biggest = Math.max(1, ...s.categories.map((c) => Number(c.spent.amount)));
  const planned = s.categories.filter((c) => c.planned);
  const compare = trip.status === "finished" && (trip.budget !== null || planned.length > 0);
  const notes = [
    Number(s.before.amount) > 0 && `${formatMoney(s.before)} was spent before the trip.`,
    s.per_day && Number(s.per_day.amount) > 0 && `An average of ${formatMoney(s.per_day)} a day.`,
  ].filter(Boolean);
  return (
    <>
      <p className="money-note">Your share, in {s.spent.currency} at each day's rate</p>
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
        <p className="money-note">
          Nothing spent yet. Expenses in {trip.currency} between {day(trip.start)} and {day(trip.end)} count by themselves.
        </p>
      )}
      {notes.length > 0 && <p className="money-note">{notes.join(" ")}</p>}
      {s.unconverted > 0 && <p className="money-note">{s.unconverted} expenses have no exchange rate yet and aren't counted.</p>}
      {compare && (
        <div className="table-wrap">
          <table className="holdings" aria-label="Planned against actual">
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
              {trip.budget && (
                <tr>
                  <td>Whole trip</td>
                  <td className="num">{formatMoney(trip.budget)}</td>
                  <td className="num">{formatMoney(s.spent)}</td>
                </tr>
              )}
              {planned.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  <td className="num">{c.planned && formatMoney(c.planned)}</td>
                  <td className="num">{formatMoney(c.spent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

const positive = (m: Money | null): m is Money => m !== null && Number(m.amount) > 0;

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

function SetAside({ detail }: { detail: TripDetail }) {
  const a = detail.saving;
  if (!a) return null;
  return !a.pay_schedule ? (
    <p className="muted">Set your pay schedule (Accounting, Plan) and Nexus can plan an amount to put aside each payday.</p>
  ) : positive(a.per_payday) ? (
    <>
      <p>{setAsideText(a, a.next_payday ? day(a.next_payday) : null)}</p>
      {a.covers_budget === false && positive(a.suggested) && (
        <p className="budget-state-warn">That's short of the budget: {formatMoney(a.suggested)} each payday would cover it.</p>
      )}
      {a.covers_budget && <p className="budget-state-ok-strong">That covers the budget.</p>}
      {a.fits === false && <p className="budget-state-over">With it, the cash-flow forecast to the trip goes below zero.</p>}
      {a.fits && <p className="money-note">It fits the cash-flow forecast, where it shows on each payday.</p>}
    </>
  ) : positive(a.suggested) ? (
    <p className="muted">
      Put aside about {formatMoney(a.suggested)} on each of the {a.paydays_left} paydays before the trip to cover the budget. Edit the trip to plan it.
    </p>
  ) : (
    <p className="muted">Add a budget, or an amount to set aside, and Nexus plans it into your paydays.</p>
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
          <button type="button" className="btn btn-soft" disabled={busy || text.trim() === ""} onClick={add}>
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

/** Who's going, saved with the trip as people are added or removed, and whether costs are
 * offered for an even split. */
function TravellersPanel({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const save = (companions: string[]) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}`, { method: "PUT", body: tripBody(trip, { companions }) });
    }, "Couldn't save that");

  const setEvenly = (on: boolean) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}/split-evenly`, { method: "PUT", body: { on } });
    }, "Couldn't change that");

  return (
    <>
      <p className="money-note">Add the people going to split costs and settle up with them</p>
      <NameChips names={trip.companions} busy={busy} onChange={(names) => void save(names)} />
      {trip.companions.length > 0 && (
        <div className="money-switch">
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
          <p className="money-note" id="trip-split-note">
            {trip.split_evenly
              ? "Costs on this trip are offered for an even split. Nothing changes until you split them."
              : "Off: costs aren't offered for splitting here. You can still split a bill in chat."}
          </p>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
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


function BalanceParts({ b, id }: { b: Balance; id: string }) {
  const line = (p: BalancePart, fallback: string) => (
    <li key={`${p.kind}-${p.id}`} className="peek-row">
      <span className="caption peek-day">{p.on ? day(p.on) : ""}</span>
      <span className="wrap">{p.label ?? fallback}</span>
      <span className="num">{formatWithHome(p.amount, p.home)}</span>
    </li>
  );
  return (
    <div className="peek todo-parts" id={id}>
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

/** One person to settle with: where you stand, Settle up (confirmed in place first), and the items behind it. */
function SettleRow({ trip, b, onSettled }: { trip: Trip; b: Balance; onSettled: (result: SettleResult) => void }) {
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
    <li className="todo-item">
      <div className="todo-row">
        <span className="todo-avatar" aria-hidden="true">
          {b.person.trim().charAt(0).toUpperCase()}
        </span>
        <div className="todo-text">
          <span className="todo-title">{balanceWords(b)}</span>
          {b.net === null && b.net_by_currency.length > 0 && (
            <span className="todo-sub">Some of this is in other currencies with no exchange rate yet, so it isn't added into one amount.</span>
          )}
        </div>
        {hasParts && !confirming && (
          <button type="button" className="btn btn-soft" aria-label={`Settle up with ${b.person}`} onClick={() => setConfirming(true)}>
            Settle up
          </button>
        )}
      </div>
      {hasParts && (
        <button type="button" className="btn btn-ghost btn-small todo-more" aria-expanded={open} aria-controls={`settle-parts-${key}`} onClick={() => setOpen(!open)}>
          Details
          <Icon name="chevron" size={16} className="money-chev" />
        </button>
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
              {busy ? "Recording…" : "Mark settled"}
            </button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>
              Not now
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

/** What needs doing with the people going: costs to split and people to settle up with. Only
 * there when someone else is going (or something was just done); otherwise nothing. */
function TodoCard({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const { trip, balances } = detail;
  const home = detail.spending?.spent.currency ?? trip.currency; // spending is null only for a member, who never sees this
  const others = trip.companions;
  const items = detail.to_split;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [seeing, setSeeing] = useState(false);
  const [outcome, setOutcome] = useState<{ result: SplitResult; names: Map<string, string> } | null>(null);
  const [done, setDone] = useState<string[]>([]);
  useEffect(() => {
    if (items.length === 0) {
      setConfirming(false);
      setSeeing(false);
    }
  }, [items.length]);
  if (others.length === 0 && balances.length === 0 && !outcome && done.length === 0) return null;

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

  const keepMine = (ids: string[]) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}/keep-mine`, { method: "POST", body: { transaction_ids: ids, keep: true } });
      setOutcome(null);
    }, "Couldn't change that");

  return (
    <section className="card money-todo" aria-labelledby="money-todo">
      <h2 id="money-todo">To do</h2>
      {balances.length > 0 && <p className="money-note">Nexus records what you say happened. It doesn't move money.</p>}
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
      {done.length > 0 && (
        <div className="split-outcome" role="status">
          {done.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      )}
      {(items.length > 0 || balances.length > 0) && (
        <ul className="todo-list">
          {items.length > 0 && (
            <li className="todo-item">
              <div className="todo-row">
                <div className="todo-text">
                  <span className="todo-title">{plural(items.length, "cost")} to split</span>
                  <span className="todo-sub">{toSplitSub(items, home)}</span>
                </div>
                {!confirming && (
                  <button type="button" className="btn btn-soft" disabled={busy} aria-label="Split all evenly" onClick={() => setConfirming(true)}>
                    Split
                  </button>
                )}
              </div>
              {confirming && (
                <div className="confirm-box" role="group" aria-label="Confirm splitting all">
                  <p>{splitAskText(items, others, home)}</p>
                  <div className="people-actions">
                    <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void split({ all: true })}>
                      {busy ? "Splitting…" : "Split evenly"}
                    </button>
                    <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>
                      Not now
                    </button>
                  </div>
                </div>
              )}
              <button type="button" className="btn btn-ghost btn-small todo-more" aria-expanded={seeing} aria-controls="todo-costs" onClick={() => setSeeing(!seeing)}>
                See costs
                <Icon name="chevron" size={16} className="money-chev" />
              </button>
              {seeing && (
                <ul className="money-rows" id="todo-costs" aria-label="To split">
                  {items.map((i) => {
                    const name = i.counterparty ?? "this cost";
                    return (
                      <li key={i.transaction_id}>
                        <div className="money-row">
                          <div className="money-row-main">
                            <span className="money-row-title">{i.counterparty ?? "Expense"}</span>
                            <span className="money-row-sub">{day(i.day)}</span>
                          </div>
                          <span className="num money-row-amount">{formatWithHome(i.amount, i.home)}</span>
                          <span className="money-row-actions">
                            <button type="button" className="btn btn-soft btn-small" disabled={busy} aria-label={`Split ${name} evenly`} onClick={() => void split({ transaction_ids: [i.transaction_id] })}>
                              Split
                            </button>
                            <button type="button" className="btn btn-soft btn-small" disabled={busy} aria-label={`Keep ${name} as just mine`} onClick={() => void keepMine([i.transaction_id])}>
                              Just mine
                            </button>
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          )}
          {balances.map((b) => (
            <SettleRow
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
      {others.length > 0 && items.length === 0 && balances.length === 0 && <p className="todo-quiet">All split and settled with {joinNames(others)}.</p>}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}


/** What fellow travellers paid for, each with a way to change or remove it. Settled ones stay, muted. */
function PaidByOthersPanel({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const { trip, paid_by_others: payments } = detail;
  const home = detail.spending?.spent.currency ?? detail.trip.currency; // spending is null only for a member, who never sees this
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <>
      <p className="money-note">Your share is what you owe them</p>
      <ul className="money-rows" aria-label="Paid by others">
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
            <li key={p.id} className={p.settled ? "is-settled" : undefined}>
              <div className="money-row">
                <div className="money-row-main">
                  <span className="money-row-title">
                    {p.person} paid{p.note ? ` for ${p.note}` : ""}
                  </span>
                  <span className="money-row-sub">
                    {day(p.paid_on)} · split with you{p.split_with.length > 0 ? `, ${joinNames(p.split_with)}` : ""}
                    {p.settled && " · settled"}
                  </span>
                </div>
                <span className="money-row-amount">
                  <span className="num">{formatMoney(p.amount)}</span>
                  <span className="money-row-sub">your share {formatMoney(p.my_share)}</span>
                </span>
                {!p.settled && removing !== p.id && (
                  <span className="money-row-actions">
                    <button type="button" className="btn btn-ghost btn-small" aria-label={`Change what ${what} paid`} onClick={() => setEditing(p.id)}>
                      <Icon name="edit" size={16} />
                      Edit
                    </button>
                    <button type="button" className="btn btn-ghost btn-danger btn-small" aria-label={`Remove what ${what} paid`} onClick={() => setRemoving(p.id)}>
                      Remove
                    </button>
                  </span>
                )}
              </div>
              {removing === p.id && (
                <div className="confirm-box" role="group" aria-label={`Remove what ${what} paid`}>
                  <p>Remove this? It won't count towards what you owe {p.person}.</p>
                  <div className="people-actions">
                    <button type="button" className="btn btn-ghost btn-danger" disabled={busy} onClick={() => void remove(p)}>
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
    </>
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
        <button type="button" className="btn btn-soft" onClick={() => onPick("planned")}>
          A planned cost
        </button>
        <button type="button" className="btn btn-soft" onClick={() => onPick("paid")}>
          Someone else paid
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}

/** How an expense stands with the people going, from what the trip already says: still to
 * split, kept as just mine, or (once costs are offered and it isn't either) split. */
function expenseTag(detail: TripDetail, id: string): { text: string; split: boolean } | null {
  const { trip } = detail;
  if (trip.companions.length === 0) return null;
  if (detail.just_mine.includes(id)) return { text: "Just mine", split: false };
  if (!trip.split_evenly) return null;
  if (detail.to_split.some((c) => c.transaction_id === id)) return { text: "To split", split: true };
  return { text: `Split with ${joinNames(trip.companions)}`, split: false };
}

/** Every expense on the trip, each tagged and with a way to take it off; and where someone else's payment is added. */
function ExpensesPanel({
  detail,
  onTakeOff,
  onChange,
  paying,
  onPay,
  onPayDone,
}: {
  detail: TripDetail;
  onTakeOff: (transactionId: string) => void;
  onChange: () => void;
  paying: boolean;
  onPay: () => void;
  onPayDone: () => void;
}) {
  const { trip } = detail;
  const home = detail.spending?.spent.currency ?? trip.currency; // spending is null only for a member, who never sees this
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function offerAgain(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}/keep-mine`, { method: "POST", body: { transaction_ids: [id], keep: false } });
      onChange();
    } catch (e) {
      setError(failure(e, "Couldn't change that"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="money-note">To count something else, like flights paid earlier, tell Nexus "add it to {trip.destination}"</p>
      {detail.items.length === 0 ? (
        <p className="money-note">None yet.</p>
      ) : (
        <ul className="money-rows" aria-label="Trip expenses">
          {detail.items.map((i) => {
            const tag = expenseTag(detail, i.transaction_id);
            const name = i.counterparty ?? "this cost";
            return (
              <li key={i.transaction_id}>
                <div className="money-row">
                  <div className="money-row-main">
                    <span className="money-row-title">{i.counterparty ?? "Expense"}</span>
                    <span className="money-row-sub">
                      {day(i.day)}
                      {i.category && ` · ${i.category}`}
                      {i.linked && " · added by hand"}
                      {tag && (
                        <>
                          {" "}
                          <span className={`money-tag${tag.split ? " money-tag-split" : ""}`}>{tag.text}</span>
                        </>
                      )}
                    </span>
                  </div>
                  <span className="num money-row-amount">{formatWithHome(i.amount, i.home)}</span>
                  <span className="money-row-actions">
                    {tag?.text === "Just mine" && trip.split_evenly && (
                      <button type="button" className="btn btn-ghost btn-small" disabled={busy} aria-label={`Offer ${name} for splitting again`} onClick={() => void offerAgain(i.transaction_id)}>
                        Offer again
                      </button>
                    )}
                    <button type="button" className="btn btn-ghost btn-small" onClick={() => onTakeOff(i.transaction_id)} aria-label={`Take ${i.counterparty ?? "this expense"} off the trip`}>
                      Take off
                    </button>
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {trip.companions.length > 0 &&
        (paying ? (
          <div className="money-form">
            <p className="money-note">Your share is what you owe them. Nothing is added to your spending until you settle up.</p>
            <PaidForm trip={trip} home={home} onChange={onChange} onDone={onPayDone} />
          </div>
        ) : (
          <button type="button" className="btn btn-ghost money-add" onClick={onPay}>
            <Icon name="plus" size={16} />
            Someone else paid
          </button>
        ))}
    </>
  );
}

/** The costs planned for the trip, by name, in the home currency. A planned cost is part
 * of the trip itself, so changing one resends the trip as the trip form would. */
async function savePlanned(trip: Trip, planned: Record<string, string>) {
  await api(`/travel/trips/${trip.id}`, { method: "PUT", body: tripBody(trip, { planned }) });
}

/** One planned cost, a name and an amount. */
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
    <div className="money-form">
      <p className="money-note">Something you expect to pay for, like flights or a tour</p>
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
    </div>
  );
}

/** What's planned to be paid for, each with a way to drop it, and where one is added. */
function PlannedPanel({
  detail,
  onChange,
  adding,
  onAdd,
  onAddDone,
}: {
  detail: TripDetail;
  onChange: () => void;
  adding: boolean;
  onAdd: () => void;
  onAddDone: () => void;
}) {
  const { trip } = detail;
  const home = detail.spending?.spent.currency ?? trip.currency; // spending is null only for a member, who never sees this
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const entries = Object.entries(trip.planned);

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

  const spentIn = (name: string) =>
    (detail.spending?.categories ?? []).filter((c) => sameName(c.name, name)).reduce((t, c) => t + amount(c.spent), 0);

  return (
    <>
      <p className="money-note">Counted against the budget once they're spent</p>
      {entries.length === 0 ? (
        <p className="money-note">None yet.</p>
      ) : (
        <ul className="money-rows" aria-label="Planned costs">
          {entries.map(([name, cost]) => {
            const spent = spentIn(name);
            return (
              <li key={name}>
                <div className="money-row">
                  <div className="money-row-main">
                    <span className="money-row-title">{name}</span>
                    <span className="money-row-sub">{spent > 0 ? `${formatMoney(moneyOf(spent, home))} spent so far` : "Nothing spent yet"}</span>
                  </div>
                  <span className="num money-row-amount">{formatMoney(cost)}</span>
                  <span className="money-row-actions">
                    <button type="button" className="btn btn-ghost btn-danger btn-small" disabled={busy !== null} onClick={() => void remove(name)} aria-label={`Remove planned cost ${name}`}>
                      Remove
                    </button>
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {adding ? (
        <PlannedForm trip={trip} currency={home} onChange={onChange} onDone={onAddDone} />
      ) : (
        <button type="button" className="btn btn-ghost money-add" onClick={onAdd}>
          <Icon name="plus" size={16} />
          Add a planned cost
        </button>
      )}
    </>
  );
}

/** The bookings on the trip that carry a cost, and how much of it isn't logged as an expense yet. */
function BookingsPanel({ detail }: { detail: TripDetail }) {
  const costed = bookingsPaid(detail);
  const unlogged = detail.booked_unlogged;
  return (
    <>
      {positive(unlogged) && <p className="money-note">{formatMoney(unlogged)} not logged as an expense yet</p>}
      <ul className="money-rows" aria-label="Bookings paid">
        {costed.map((b) => (
          <li key={b.id}>
            <div className="money-row">
              <div className="money-row-main">
                <span className="money-row-title">{b.title}</span>
                <span className="money-row-sub">
                  {day(b.starts)} · {b.logged ? "Logged as an expense" : "Not logged yet"}
                </span>
              </div>
              <span className="num money-row-amount">{b.cost && formatMoney(b.cost)}</span>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

/** The trip's bookings that carry a cost (a place to visit with no day isn't booked yet). */
const bookingsPaid = (detail: TripDetail) => detail.bookings.filter((b) => b.cost !== null && b.scheduled);

type SectionId = "where" | "planned" | "aside" | "bookings" | "expenses" | "paid" | "travellers";

/** One row of the Details accordion: a 56px header button, and its content when open. */
function Section({ id, title, summary, open, onToggle, children }: { id: SectionId; title: string; summary: string; open: boolean; onToggle: () => void; children: ReactNode }) {
  const base = `money-sec-${id}`;
  return (
    <div className="money-sec">
      <h3 className="money-sec-h">
        <button type="button" className="money-sec-btn" aria-expanded={open} aria-controls={`${base}-panel`} onClick={onToggle}>
          <span className="money-sec-title" id={`${base}-title`}>
            {title}
          </span>
          <span className="money-sec-sum">{summary}</span>
          <Icon name="chevron" size={16} className="money-chev" />
        </button>
      </h3>
      <div className="money-sec-panel" id={`${base}-panel`} role="region" aria-labelledby={`${base}-title`} hidden={!open}>
        {open && children}
      </div>
    </div>
  );
}

/** The one card at the top of the Money tab. Before the trip: spent and booked against the
 * budget, with what's planned still to come. While it's on: spent so far. After: what it cost. */
export function MoneySummary({ detail }: { detail: TripDetail }) {
  const s = detail.spending;
  if (!s) return null; // a member of the trip gets no money
  const t = detail.trip;
  const stage = stageOf(detail);
  const after = stage === "after";
  const cur = s.spent.currency;
  const budget = t.budget ? Number(t.budget.amount) : null;
  const spent = amount(s.spent);
  const booked = after ? 0 : Math.max(0, amount(detail.booked_unlogged));
  const planned = after ? 0 : Math.max(0, plannedAhead(detail));
  const committed = spent + booked + planned;
  const headline = stage === "planning" || stage === "soon" ? spent + booked : spent;
  const label = after ? "The trip cost" : stage === "during" ? "Spent so far" : "Spent and booked";
  const parts = [
    { key: "spent", text: "Spent", value: spent },
    { key: "booked", text: "Booked", value: booked },
    { key: "planned", text: "Planned", value: planned },
  ].filter((p) => p.value > 0);
  const scale = budget !== null ? Math.max(budget, committed) : committed;
  const left = budget !== null ? budget - committed : null;
  const over = left !== null && left < 0;
  const diff = after && budget ? Math.round(((spent - budget) / budget) * 100) : null;
  const daysLeft = Math.max(t.days - (t.day_number ?? 1) + 1, 1);
  const local = detail.items.filter((i) => i.amount.currency === t.currency).reduce((sum, i) => sum + Number(i.amount.amount), 0);
  const nowLine = [
    positive(s.per_day_left) && `${formatMoney(s.per_day_left)} a day left for ${plural(daysLeft, "day")}`,
    positive(s.today) && `${formatMoney(s.today)} today`,
    local > 0 && t.currency !== cur && `${formatMoney(moneyOf(local, t.currency))} spent in ${t.currency}`,
  ].filter(Boolean);
  const barLabel = `${parts.map((p) => `${p.text.toLowerCase()} ${formatMoney(moneyOf(p.value, cur))}`).join(", ") || "nothing yet"}${t.budget ? ` of ${formatMoney(t.budget)}` : ""}`;

  return (
    <section className="card money-summary" aria-labelledby="money-summary">
      <h2 id="money-summary" className="money-label">
        {label}
      </h2>
      <p className="money-figure">
        <CountUp value={formatMoney(moneyOf(headline, cur))} />
        {t.budget && <> <span className="money-of">of {formatMoney(t.budget)}</span></>}
      </p>
      {budget !== null && scale > 0 && (
        <div className={`money-track${over || (diff !== null && diff > 0) ? " is-over" : ""}`} role="img" aria-label={barLabel}>
          {(after ? [{ key: "spent", text: "Spent", value: spent }] : parts).map((p) => (
            <span key={p.key} className={`money-seg money-seg-${p.key}`} style={{ width: `${(p.value / scale) * 100}%` }} />
          ))}
        </div>
      )}
      {!after && parts.length > 0 && (
        <p className="money-legend">
          {parts.map((p, n) => (
            <span key={p.key}>
              {n > 0 && <span aria-hidden="true"> · </span>}
              <span className={`money-key money-seg-${p.key}`} aria-hidden="true" />
              {p.text} {formatMoney(moneyOf(p.value, cur))}
            </span>
          ))}
        </p>
      )}
      {!after && left !== null && (
        <p className={`money-left${over ? " money-over" : ""}`}>
          {over ? "Over by " : "Left after planned costs "}
          <span className="num">{formatMoney(moneyOf(Math.abs(left), cur))}</span>
        </p>
      )}
      {stage === "during" && nowLine.length > 0 && <p className="money-note">{nowLine.join(" · ")}</p>}
      {stage === "during" && <p className="money-note">Log what you spend on Telegram: "ramen 1200 yen".</p>}
      {after && diff !== null && (
        <p className={`money-left${diff > 0 ? " money-over" : ""}`}>{diff === 0 ? "On budget" : `${Math.abs(diff)}% ${diff > 0 ? "over" : "under"} budget`}</p>
      )}
      {after && t.companions.length > 0 && <p className="money-note">Your share, with {joinNames(t.companions)}</p>}
    </section>
  );
}

/** The Money tab: one summary, what needs doing, then the details one section at a time.
 * ``adding``: the tab's + was pressed: a planned cost, or (with other travellers) a choice
 * between that and a cost someone else paid. */
export function MoneyTab({ detail, onChange, adding, onAddDone }: { detail: TripDetail; onChange: () => void; adding: boolean; onAddDone: () => void }) {
  const stage = stageOf(detail);
  const { trip } = detail;
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"planned" | "paid" | null>(null);
  const [form, setForm] = useState<"planned" | "paid" | null>(null);
  const [open, setOpen] = useState<SectionId | null>(null);
  const hasOthers = trip.companions.length > 0;
  useEffect(() => {
    if (!adding) setKind(null);
  }, [adding]);
  const adds = adding ? (hasOthers ? kind : "planned") : null;
  // The tab's + opens the section its form lives in.
  useEffect(() => {
    if (adds) setOpen(adds === "planned" ? "planned" : "expenses");
  }, [adds]);
  const showForm = (which: "planned" | "paid") => adds === which || form === which;
  const formDone = () => {
    setForm(null);
    if (adding) onAddDone();
  };

  async function takeOff(transactionId: string) {
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}/expenses/${transactionId}`, { method: "DELETE" });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't take that off");
    }
  }

  const s = detail.spending;
  const toggle = (id: SectionId) => setOpen(open === id ? null : id);
  const planned = Object.keys(trip.planned).length;
  const costed = bookingsPaid(detail);
  const payments = detail.paid_by_others;
  const todo = <TodoCard detail={detail} onChange={onChange} />;
  return (
    <>
      {adding && hasOthers && kind === null && <AddChoice onPick={setKind} onCancel={onAddDone} />}
      {/* After the trip, settling up comes first, then what it cost. */}
      {stage === "after" && todo}
      <MoneySummary detail={detail} />
      {stage !== "after" && todo}
      <section className="card money-details" aria-labelledby="money-details">
        <h2 id="money-details">Details</h2>
        <div className="money-secs">
          <Section id="where" title="Where it goes" summary={s ? plural(s.categories.length, "category", "categories") : ""} open={open === "where"} onToggle={() => toggle("where")}>
            <WhereItGoes detail={detail} />
          </Section>
          <Section id="planned" title="Planned costs" summary={planned === 0 ? "None yet" : plural(planned, "cost")} open={open === "planned"} onToggle={() => toggle("planned")}>
            <PlannedPanel detail={detail} onChange={onChange} adding={showForm("planned")} onAdd={() => setForm("planned")} onAddDone={formDone} />
          </Section>
          {detail.saving && trip.status === "upcoming" && (
            <Section id="aside" title="Setting money aside" summary={positive(detail.saving.per_payday) ? "Monthly" : "Not set"} open={open === "aside"} onToggle={() => toggle("aside")}>
              <SetAside detail={detail} />
            </Section>
          )}
          {costed.length > 0 && (
            <Section id="bookings" title="Bookings paid" summary={plural(costed.length, "booking")} open={open === "bookings"} onToggle={() => toggle("bookings")}>
              <BookingsPanel detail={detail} />
            </Section>
          )}
          <Section id="expenses" title="Expenses" summary={detail.items.length === 0 ? "None yet" : `${detail.items.length} so far`} open={open === "expenses"} onToggle={() => toggle("expenses")}>
            <ExpensesPanel detail={detail} onTakeOff={(t) => void takeOff(t)} onChange={onChange} paying={showForm("paid")} onPay={() => setForm("paid")} onPayDone={formDone} />
          </Section>
          {payments.length > 0 && (
            <Section id="paid" title="Paid by others" summary={plural(payments.length, "payment")} open={open === "paid"} onToggle={() => toggle("paid")}>
              <PaidByOthersPanel detail={detail} onChange={onChange} />
            </Section>
          )}
          <Section id="travellers" title="Travellers" summary={joinNames(["You", ...trip.companions])} open={open === "travellers"} onToggle={() => toggle("travellers")}>
            <TravellersPanel trip={trip} onChange={onChange} />
          </Section>
        </div>
      </section>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
