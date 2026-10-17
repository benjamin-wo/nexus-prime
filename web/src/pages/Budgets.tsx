import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, type FormEvent, useState } from "react";

import { api, type Budget, type BudgetMonth, type Category, type Me } from "../api";
import { CategoryTransactions } from "../components/CategoryTransactions";
import { formatMoney, isoDay } from "../format";

function level(percent: number): "ok" | "warn" | "over" {
  if (percent >= 100) return "over";
  if (percent >= 80) return "warn";
  return "ok";
}

/** This month so far, as budgets count it, in the user's timezone. */
function thisMonth(timezone: string): { start: string; end: string } {
  const end = isoDay(new Date().toISOString(), timezone);
  return { start: `${end.slice(0, 8)}01`, end };
}

function BudgetRow({ budget, timezone, onChanged }: { budget: Budget; timezone: string; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [showing, setShowing] = useState(false);
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
            <button
              type="button"
              className="btn btn-ghost"
              aria-expanded={showing}
              aria-controls={`budget-tx-${budget.id}`}
              onClick={() => setShowing(!showing)}
            >
              {showing ? "Hide transactions" : "Transactions"}
            </button>
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
      {showing && (
        <CategoryTransactions
          id={`budget-tx-${budget.id}`}
          name={budget.name}
          timezone={timezone}
          pick={{ category: budget.category_id ?? undefined, ...thisMonth(timezone) }}
        />
      )}
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

/** This month so far, and what's still to come: spending plus moves to your wallets,
 * then what's left to spend after the month's bills, next to what's left of the overall
 * budget (the lower of the two is marked). */
function MonthPlan({ plan }: { plan: BudgetMonth }) {
  const tighter = plan.budget_left ? plan.tighter : null;
  const watch = (which: "budget" | "left_to_spend") =>
    tighter === which ? <span className="badge badge-watch">Watch this</span> : null;
  return (
    <div className="month-plan">
      <div className="month-figures" role="group" aria-label="This month">
        <div className="month-figure" role="group" aria-label="Total out of Spending">
          <span className="caption">Total out of Spending</span>
          <span className="num month-value">{formatMoney(plan.total_out)}</span>
          <span className="caption">spending plus moves to your wallets</span>
        </div>
        <div
          className={`month-figure${tighter === "left_to_spend" ? " month-watch" : ""}`}
          role="group"
          aria-label="Left to spend"
        >
          <span className="caption">Left to spend {watch("left_to_spend")}</span>
          <span className="num month-value">{formatMoney(plan.left_to_spend)}</span>
          <span className="caption">after what's still due this month ({formatMoney(plan.still_due_out)})</span>
        </div>
        {plan.budget_left && (
          <div
            className={`month-figure${tighter === "budget" ? " month-watch" : ""}`}
            role="group"
            aria-label="Budget left"
          >
            <span className="caption">Budget left {watch("budget")}</span>
            <span className="num month-value">{formatMoney(plan.budget_left)}</span>
            <span className="caption">of your overall budget</span>
          </div>
        )}
      </div>
      {plan.plan_warning && (
        <p className="callout" role="note">
          {plan.plan_warning}
        </p>
      )}
      {plan.skipped.length > 0 && (
        <p className="caption">Left out, no amount or rate yet: {plan.skipped.join(", ")}</p>
      )}
    </div>
  );
}

export function BudgetsSection({ me }: { me: Me }) {
  const client = useQueryClient();
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: () => api<Budget[]>("/budgets") });
  // Under "budgets" so every change to a budget refreshes it too. It never holds the list back.
  const month = useQuery({ queryKey: ["budgets", "month"], queryFn: () => api<BudgetMonth>("/budgets/month") });
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });
  const [target, setTarget] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const home = me.user.home_currency;

  const hasOverall = Boolean(budgets.data?.some((b) => b.category_id === null));
  const taken = new Set(budgets.data?.map((b) => b.category_id ?? "overall"));
  const options = [
    ...(taken.has("overall") ? [] : [{ value: "overall", label: "All spending" }]),
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
    <section className="card" aria-labelledby="budgets">
      <div className="card-head">
        <h2 id="budgets">Budgets</h2>
        <span className="caption">Monthly in {home} · alerts at 50/80/100%</span>
      </div>
      {budgets.isLoading && <p className="state">Loading…</p>}
      {budgets.isError && <p className="state error-text">Couldn't load budgets.</p>}
      {budgets.data?.length === 0 && <p className="state">No budgets yet. Add one below.</p>}
      {!hasOverall && month.data && <MonthPlan plan={month.data} />}
      {budgets.data && budgets.data.length > 0 && (
        <ul className="budgets">
          {budgets.data.map((b) => (
            <Fragment key={b.id}>
              <BudgetRow budget={b} timezone={me.user.timezone} onChanged={refresh} />
              {b.category_id === null && month.data && (
                <li className="budget-month">
                  <MonthPlan plan={month.data} />
                </li>
              )}
            </Fragment>
          ))}
        </ul>
      )}
      {options.length > 0 && (
        <form className="budget-add plan-add" onSubmit={add} aria-label="Add a budget">
          <label className="field">
            Budget for
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
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
