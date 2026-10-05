import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type Bill, type Me } from "../api";
import { formatMoney } from "../format";

const CADENCES = [
  { value: "monthly", label: "Every month" },
  { value: "weekly", label: "Every week" },
  { value: "yearly", label: "Every year" },
  { value: "once", label: "Just once" },
] as const;

function when(bill: Bill): string {
  const day = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(bill.due));
  if (bill.days_until < 0) return `Overdue since ${day}`;
  if (bill.days_until === 0) return `Due today, ${day}`;
  if (bill.days_until === 1) return `Due tomorrow, ${day}`;
  return `Due in ${bill.days_until} days, ${day}`;
}

function state(bill: Bill): "ok" | "warn" | "over" {
  if (bill.days_until < 0) return "over";
  if (bill.days_until <= 3) return "warn";
  return "ok";
}

type Paid = { message: string; logged: boolean; needs_amount: boolean };

function BillRow({ bill, home, onChanged, onPaid }: {
  bill: Bill;
  home: string;
  onChanged: () => void;
  onPaid: (message: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [paying, setPaying] = useState(false);
  const [paidAmount, setPaidAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function act(path: string, method = "POST") {
    setError(null);
    try {
      await api(`/bills/${bill.id}${path}`, { method });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update");
    }
  }

  async function markPaid(amount: string | null) {
    setError(null);
    try {
      const paid = await api<Paid>(`/bills/${bill.id}/paid`, { method: "POST", body: { amount } });
      setPaying(false);
      setPaidAmount("");
      onPaid(paid.message);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update");
    }
  }

  function startPaid() {
    // Without a set amount, ask what was paid so it can count in the month's spending.
    if (bill.amount) void markPaid(null);
    else setPaying(true);
  }

  const repeats = CADENCES.find((c) => c.value === bill.cadence)?.label ?? bill.cadence;
  return (
    <li className="budget">
      <div className="budget-head">
        <h3 className="wrap">{bill.name}</h3>
        <span className="num">{bill.amount ? formatMoney(bill.amount) : <span className="muted">No amount</span>}</span>
      </div>
      <div className="budget-foot">
        <span className={`caption budget-state-${state(bill)}`}>
          {when(bill)} · {repeats}
          {bill.snoozed && " · reminders snoozed"}
        </span>
        {paying ? (
          <form
            className="quick"
            aria-label={`What you paid for ${bill.name}`}
            onSubmit={(e) => {
              e.preventDefault();
              void markPaid(paidAmount.trim() || null);
            }}
          >
            <label className="field">
              Paid ({home})
              <input
                className="input"
                inputMode="decimal"
                placeholder="120"
                value={paidAmount}
                onChange={(e) => setPaidAmount(e.target.value)}
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={!paidAmount.trim()}>
              Log and mark paid
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => void markPaid(null)}>
              Just mark paid
            </button>
            <button type="button" className="btn" onClick={() => setPaying(false)}>
              Cancel
            </button>
          </form>
        ) : !confirming ? (
          <span className="quick">
            <button type="button" className="btn btn-ghost" onClick={startPaid}>
              Mark paid
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => act("/snooze")} disabled={bill.snoozed}>
              Snooze
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
              Remove
            </button>
          </span>
        ) : (
          <span className="quick">
            <span>Stop tracking this bill?</span>
            <button type="button" className="btn btn-danger" onClick={() => act("", "DELETE")}>
              Remove
            </button>
            <button type="button" className="btn" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </span>
        )}
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

export function BillsSection({ me }: { me: Me }) {
  const client = useQueryClient();
  const bills = useQuery({ queryKey: ["bills"], queryFn: () => api<Bill[]>("/bills") });
  const [name, setName] = useState("");
  const [due, setDue] = useState("");
  const [cadence, setCadence] = useState<Bill["cadence"]>("monthly");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const home = me.user.home_currency;

  function refresh() {
    void client.invalidateQueries({ queryKey: ["bills"] });
    // Marking paid can log an expense, which changes the month's spending.
    void client.invalidateQueries({ queryKey: ["transactions"] });
    void client.invalidateQueries({ queryKey: ["home"] });
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/bills", { method: "POST", body: { name: name.trim(), due, cadence, amount: amount.trim() || null } });
      setName("");
      setDue("");
      setAmount("");
      setCadence("monthly");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  return (
    <section className="card" aria-labelledby="bills">
      <div className="card-head">
        <h2 id="bills">Bills</h2>
        <span className="caption">Reminders 7, 3 and 1 days before</span>
      </div>
      {bills.isLoading && <p className="state">Loading…</p>}
      {bills.isError && <p className="state error-text">Couldn't load bills.</p>}
      {bills.data?.length === 0 && <p className="state">No bills yet. Add one below.</p>}
      {notice && (
        <p className="state" role="status">
          {notice}
        </p>
      )}
      {bills.data && bills.data.length > 0 && (
        <ul className="budgets">
          {bills.data.map((b) => (
            <BillRow key={b.id} bill={b} home={home} onChanged={refresh} onPaid={setNotice} />
          ))}
        </ul>
      )}
      <form className="budget-add plan-add" onSubmit={add} aria-label="Add a bill">
        <label className="field">
          Bill
          <input className="input" placeholder="Rent" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="field">
          Next due
          <input className="input" type="date" value={due} onChange={(e) => setDue(e.target.value)} required />
        </label>
        <label className="field">
          Repeats
          <select className="input" value={cadence} onChange={(e) => setCadence(e.target.value as Bill["cadence"])}>
            {CADENCES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Amount ({home}, optional)
          <input
            className="input"
            inputMode="decimal"
            placeholder="1800"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={!name.trim() || !due}>
          Add bill
        </button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <p className="caption">Nexus only reminds you and never pays anything. Marking a bill paid logs it in your spending, unless it's already there.</p>
    </section>
  );
}
