import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type Me, type Salary } from "../api";
import { formatMoney } from "../format";

const RULES = [
  { value: "monthly_day", label: "A day of the month" },
  { value: "last_weekday", label: "Last weekday of the month" },
  { value: "biweekly", label: "Every two weeks" },
] as const;

function nextPayday(pay: Salary): string {
  const day = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(pay.next_payday));
  if (pay.days_until === 0) return `Today! ${day}`;
  if (pay.days_until === 1) return `Tomorrow, ${day}`;
  return `In ${pay.days_until} days, ${day}`;
}

export function PaydaySection({ me }: { me: Me }) {
  const client = useQueryClient();
  const pay = useQuery({ queryKey: ["salary"], queryFn: () => api<Salary | null>("/salary") });
  const [editing, setEditing] = useState(false);
  const [rule, setRule] = useState<Salary["rule"]>("monthly_day");
  const [day, setDay] = useState("25");
  const [anchor, setAnchor] = useState("");
  const [usual, setUsual] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const home = me.user.home_currency;
  const current = pay.data ?? null;
  const showForm = editing || (pay.isSuccess && current === null);

  function refresh() {
    void client.invalidateQueries({ queryKey: ["salary"] });
  }

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      refresh();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
      return false;
    }
  }

  async function saveSchedule(event: FormEvent) {
    event.preventDefault();
    const body = {
      rule,
      day: rule === "monthly_day" ? Number(day) : null,
      anchor: rule === "biweekly" ? anchor : null,
    };
    if (await run(() => api("/salary", { method: "PUT", body }))) setEditing(false);
  }

  async function saveUsual(event: FormEvent) {
    event.preventDefault();
    if (await run(() => api("/salary/usual", { method: "PUT", body: { amount: usual.trim() } }))) setUsual("");
  }

  function startEditing() {
    if (current) {
      setRule(current.rule);
      setDay(String(current.day ?? 25));
      setAnchor(current.anchor ?? "");
    }
    setEditing(true);
  }

  return (
    <section className="card" aria-labelledby="payday">
      <div className="card-head">
        <h2 id="payday">Payday</h2>
        <span className="caption">A check-in on payday; weekends move to Friday</span>
      </div>
      {pay.isLoading && <p className="state">Loading…</p>}
      {pay.isError && <p className="state error-text">Couldn't load your pay schedule.</p>}

      {current && !editing && (
        <div className="budget solo">
          <div className="budget-head">
            <h3 className="wrap">Paid on {current.description}</h3>
            <span className="num">
              {current.usual ? formatMoney(current.usual) : <span className="muted">No usual amount</span>}
            </span>
          </div>
          <div className="budget-foot">
            <span className={`caption ${current.days_until === 0 ? "budget-state-ok-strong" : ""}`}>
              Next payday: {nextPayday(current)}
            </span>
            {!confirming ? (
              <span className="quick">
                <button type="button" className="btn btn-ghost" onClick={startEditing}>
                  Change
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
                  Remove
                </button>
              </span>
            ) : (
              <span className="quick">
                <span>Stop payday check-ins?</span>
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => run(() => api("/salary", { method: "DELETE" })).then(() => setConfirming(false))}
                >
                  Remove
                </button>
                <button type="button" className="btn" onClick={() => setConfirming(false)}>
                  Keep
                </button>
              </span>
            )}
          </div>
        </div>
      )}

      {showForm && (
        <form className="budget-add" onSubmit={saveSchedule} aria-label="When you're paid">
          <label className="field">
            I'm paid on
            <select className="input" value={rule} onChange={(e) => setRule(e.target.value as Salary["rule"])}>
              {RULES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          {rule === "monthly_day" && (
            <label className="field">
              Day
              <input
                className="input"
                type="number"
                min={1}
                max={31}
                value={day}
                onChange={(e) => setDay(e.target.value)}
                required
              />
            </label>
          )}
          {rule === "biweekly" && (
            <label className="field">
              Next payday
              <input
                className="input"
                type="date"
                value={anchor}
                onChange={(e) => setAnchor(e.target.value)}
                required
              />
            </label>
          )}
          <button type="submit" className="btn btn-primary">
            Save
          </button>
          {editing && (
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          )}
        </form>
      )}

      {current && !editing && (
        <form className="budget-add plan-add" onSubmit={saveUsual} aria-label="Usual salary">
          <label className="field">
            {current.usual ? "Change usual salary" : "Usual salary"} ({home})
            <input
              className="input"
              inputMode="decimal"
              placeholder={current.usual ? String(Number(current.usual.amount)) : "5000"}
              value={usual}
              onChange={(e) => setUsual(e.target.value)}
              required
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={!usual.trim()}>
            Save
          </button>
        </form>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <p className="caption">Your salary is only what you tell Nexus; it's never guessed from your transactions.</p>
    </section>
  );
}
