import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type Bill, type Me, type Wallet } from "../api";
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

type Paid = { message: string; logged: boolean; moved: boolean; needs_amount: boolean };

function BillRow({ bill, home, wallets, onChanged, onPaid }: {
  bill: Bill;
  home: string;
  /** The wallets a scheduled move can go to (not Spending). */
  wallets: Wallet[];
  onChanged: () => void;
  onPaid: (message: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [paying, setPaying] = useState(false);
  const [paidAmount, setPaidAmount] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkTo, setLinkTo] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function link(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api(`/bills/${bill.id}`, { method: "PATCH", body: { wallet_id: linkTo || wallets[0]?.id } });
      setLinking(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

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

  const spending = bill.spending;

  function startPaid() {
    // Without a set amount, ask what it cost so it can count in the month's
    // spending. Money moved rather than spent (investing, saving) is just marked done.
    if (bill.amount || !spending) void markPaid(null);
    else setPaying(true);
  }

  const repeats = CADENCES.find((c) => c.value === bill.cadence)?.label ?? bill.cadence;
  return (
    <li className="budget">
      <div className="budget-head">
        <h3 className="wrap">
          {bill.name}
          {!spending && <span className="chip kind-chip">Not spending</span>}
          {bill.wallet && <span className="chip kind-chip">→ {bill.wallet.name}</span>}
        </h3>
        <span className="num">{bill.amount ? formatMoney(bill.amount) : <span className="muted">No amount</span>}</span>
      </div>
      {!spending && !bill.wallet && wallets.length > 0 &&
        (linking ? (
          <form className="quick" onSubmit={link} aria-label={`Link ${bill.name} to a wallet`}>
            <select
              className="input"
              aria-label={`Wallet for ${bill.name}`}
              value={linkTo || wallets[0].id}
              onChange={(e) => setLinkTo(e.target.value)}
            >
              {wallets.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
            <button type="submit" className="btn btn-primary btn-small">
              Save
            </button>
            <button type="button" className="btn btn-small" onClick={() => setLinking(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <span className="quick">
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setLinking(true)}>
              Link to a wallet
            </button>
          </span>
        ))}
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
              {spending ? "Mark paid" : "Mark done"}
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
            <span>Stop tracking {bill.name}?</span>
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
  const [spending, setSpending] = useState(true);
  const [amount, setAmount] = useState("");
  const [walletId, setWalletId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const home = me.user.home_currency;
  const wallets = useQuery({ queryKey: ["wallets"], queryFn: () => api<Wallet[]>("/wallets") });
  const elsewhere = (wallets.data ?? []).filter((w) => w.kind !== "spending");

  function refresh() {
    void client.invalidateQueries({ queryKey: ["bills"] });
    // Marking paid can log an expense, which changes the month's spending.
    void client.invalidateQueries({ queryKey: ["transactions"] });
    void client.invalidateQueries({ queryKey: ["home"] });
    // A done scheduled move logs a move, which changes what's left to spend.
    void client.invalidateQueries({ queryKey: ["budgets"] });
    void client.invalidateQueries({ queryKey: ["summary"] });
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/bills", { method: "POST", body: {
          name: name.trim(),
          due,
          cadence,
          spending,
          wallet_id: !spending && walletId ? walletId : null,
          amount: amount.trim() || null,
        },
      });
      setName("");
      setDue("");
      setAmount("");
      setCadence("monthly");
      setSpending(true);
      setWalletId("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  return (
    <section className="card" aria-labelledby="bills">
      <div className="card-head">
        <h2 id="bills">Scheduled payments</h2>
        <span className="caption">Reminders 7, 3 and 1 days before</span>
      </div>
      {bills.isLoading && <p className="state">Loading…</p>}
      {bills.isError && <p className="state error-text">Couldn't load bills.</p>}
      {bills.data?.length === 0 && (
        <p className="state">Nothing scheduled yet. Add rent, a bill, a regular investment or a transfer below.</p>
      )}
      {notice && (
        <p className="state" role="status">
          {notice}
        </p>
      )}
      {bills.data && bills.data.length > 0 && (
        <ul className="budgets">
          {bills.data.map((b) => (
            <BillRow key={b.id} bill={b} home={home} wallets={elsewhere} onChanged={refresh} onPaid={setNotice} />
          ))}
        </ul>
      )}
      <form className="budget-add plan-add" onSubmit={add} aria-label="Add a scheduled payment">
        <label className="field">
          Name
          <input
            className="input"
            placeholder="Rent, ETF, savings…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
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
        <div className="spending-toggle">
          <label className="toggle">
            <input
              type="checkbox"
              checked={spending}
              onChange={(e) => setSpending(e.target.checked)}
              aria-describedby="spending-hint"
            />{" "}
            Counts as spending
          </label>
          <span id="spending-hint" className="caption">
            Untick for money you move rather than spend, like investing or saving.
          </span>
        </div>
        {!spending && elsewhere.length > 0 && (
          <label className="field">
            Moves money to (optional)
            <select className="input" value={walletId} onChange={(e) => setWalletId(e.target.value)}>
              <option value="">No wallet</option>
              {elsewhere.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <button type="submit" className="btn btn-primary" disabled={!name.trim() || !due}>
          Add
        </button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <p className="caption">
        Nexus only reminds you; it never pays, invests or moves money. Marking a payment paid logs it as spending, unless it's
        already there. One that doesn't count as spending is marked done; if it moves money to a wallet, the move is logged too.
      </p>
    </section>
  );
}
