import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type Budget, type Category, type Me } from "../api";
import { formatMoney } from "../format";

function level(percent: number): "ok" | "warn" | "over" {
  if (percent >= 100) return "over";
  if (percent >= 80) return "warn";
  return "ok";
}

function BudgetRow({ budget, onChanged }: { budget: Budget; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState(String(Number(budget.limit.amount)));
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const state = level(budget.percent);
  const over = Number(budget.remaining.amount) < 0;

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/budgets", { method: "PUT", body: { category_id: budget.category_id, amount: amount.trim() } });
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  async function remove() {
    await api(`/budgets/${budget.id}`, { method: "DELETE" });
    onChanged();
  }

  const remainingText = over
    ? `Over by ${formatMoney({ ...budget.remaining, amount: String(-Number(budget.remaining.amount)) })}`
    : `${formatMoney(budget.remaining)} left`;

  return (
    <li className="budget">
      <div className="budget-head">
        <h3 className="wrap">{budget.name}</h3>
        <span className="num">
          {formatMoney(budget.spent)} <span className="muted">of {formatMoney(budget.limit)}</span>
        </span>
      </div>
      <div
        className={`meter meter-${state}`}
        role="meter"
        aria-label={`${budget.name} budget used`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(budget.percent, 100)}
        aria-valuetext={`${budget.percent}% used`}
      >
        <span style={{ width: `${Math.min(budget.percent, 100)}%` }} />
      </div>
      <div className="budget-foot">
        <span className={`caption budget-state-${state}`}>
          {budget.percent}% used · {remainingText}
        </span>
        {!editing && !confirming && (
          <span className="quick">
            <button type="button" className="btn btn-ghost" onClick={() => setEditing(true)}>
              Change
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
              Remove
            </button>
          </span>
        )}
        {confirming && (
          <span className="quick">
            <span>Remove this budget?</span>
            <button type="button" className="btn btn-danger" onClick={remove}>
              Remove
            </button>
            <button type="button" className="btn" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </span>
        )}
      </div>
      {budget.unconverted.length > 0 && (
        <p className="caption">Not counted, no exchange rate yet: {budget.unconverted.map(formatMoney).join(", ")}</p>
      )}
      {editing && (
        <form className="budget-edit" onSubmit={save}>
          <label className="field">
            Monthly limit ({budget.limit.currency})
            <input
              className="input"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              autoFocus
            />
          </label>
          <span className="quick">
            <button type="submit" className="btn btn-primary">
              Save
            </button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </span>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
        </form>
      )}
    </li>
  );
}

export function Budgets({ me }: { me: Me }) {
  const client = useQueryClient();
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: () => api<Budget[]>("/budgets") });
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });
  const [target, setTarget] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const home = me.user.home_currency;

  const taken = new Set(budgets.data?.map((b) => b.category_id ?? "overall"));
  const options = [
    ...(taken.has("overall") ? [] : [{ value: "overall", label: "Overall (all spending)" }]),
    ...(categories.data ?? []).filter((c) => !taken.has(c.id)).map((c) => ({ value: c.id, label: c.name })),
  ];
  const chosen = target && options.some((o) => o.value === target) ? target : (options[0]?.value ?? "");

  function refresh() {
    void client.invalidateQueries({ queryKey: ["budgets"] });
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/budgets", {
        method: "PUT",
        body: { category_id: chosen === "overall" ? null : chosen, amount: amount.trim() },
      });
      setAmount("");
      setTarget("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Budgets</h1>
          <p className="muted">Monthly limits in {home}. They reset on the 1st; nothing rolls over.</p>
        </div>
      </div>

      <section className="card" aria-labelledby="this-month">
        <div className="card-head">
          <h2 id="this-month">This month</h2>
          <span className="caption">Alerts at 50%, 80% and 100% on Telegram</span>
        </div>
        {budgets.isLoading && <p className="state">Loading…</p>}
        {budgets.isError && <p className="state error-text">Couldn't load budgets.</p>}
        {budgets.data?.length === 0 && <p className="state">No budgets yet. Add one below.</p>}
        {budgets.data && budgets.data.length > 0 && (
          <ul className="budgets">
            {budgets.data.map((b) => (
              <BudgetRow key={b.id} budget={b} onChanged={refresh} />
            ))}
          </ul>
        )}
      </section>

      {options.length > 0 && (
        <section className="card" aria-labelledby="add-budget">
          <div className="card-head">
            <h2 id="add-budget">Add a budget</h2>
          </div>
          <form className="budget-add" onSubmit={add}>
            <label className="field">
              For
              <select className="input" value={chosen} onChange={(e) => setTarget(e.target.value)}>
                {options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Monthly limit ({home})
              <input
                className="input"
                inputMode="decimal"
                placeholder="400"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={!amount.trim()}>
              Add budget
            </button>
          </form>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
        </section>
      )}
    </>
  );
}
