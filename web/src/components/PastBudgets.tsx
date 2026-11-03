import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Budget } from "../api";
import { formatMoney } from "../format";
import { type MonthKey, monthRange } from "../months";
import { CategoryTransactions } from "./CategoryTransactions";

/** How full a budget is: used up (over), nearly (warn) or comfortable. */
export function level(percent: number): "ok" | "warn" | "over" {
  if (percent >= 100) return "over";
  if (percent >= 80) return "warn";
  return "ok";
}

function Row({ budget, month, timezone }: { budget: Budget; month: MonthKey; timezone?: string }) {
  const [showing, setShowing] = useState(false);
  const state = level(budget.percent);
  const left = Number(budget.remaining.amount);
  const verdict =
    left < 0
      ? `Over by ${formatMoney({ ...budget.remaining, amount: String(-left) })}`
      : `${formatMoney(budget.remaining)} under`;
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
          {budget.percent}% used · {verdict}
        </span>
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
        </span>
      </div>
      {showing && (
        <CategoryTransactions
          id={`budget-tx-${budget.id}`}
          name={budget.name}
          timezone={timezone}
          pick={{ category: budget.category_id ?? undefined, ...monthRange(month) }}
        />
      )}
      {budget.unconverted.length > 0 && (
        <p className="caption">Not counted, no exchange rate yet: {budget.unconverted.map(formatMoney).join(", ")}</p>
      )}
    </li>
  );
}

/** The budgets as they stood against one month's spending (`?month=`), at today's limits. */
export function usePastBudgets(month: MonthKey, enabled: boolean) {
  return useQuery({
    queryKey: ["budgets", "in", month],
    queryFn: () => api<Budget[]>(`/budgets?month=${month}`),
    enabled,
  });
}

/** What each budget spent in a past month against its limit, over or under. Read-only:
 * the limits are today's, and they are changed on the current month. */
export function PastBudgets({ budgets, month, timezone }: { budgets: Budget[]; month: MonthKey; timezone?: string }) {
  if (budgets.length === 0) return <p className="state">No budgets set.</p>;
  return (
    <ul className="budgets" aria-label="Budgets that month">
      {budgets.map((b) => (
        <Row key={b.id} budget={b} month={month} timezone={timezone} />
      ))}
    </ul>
  );
}
