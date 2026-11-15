import { useQuery } from "@tanstack/react-query";

import { api, type Budget } from "../api";
import { PastBudgets } from "../components/PastBudgets";
import { formatMoney } from "../format";
import type { PanelEvent } from "./types";

type Props = { event: Extract<PanelEvent, { kind: "finance.budgets" }>; timezone?: string };

/** Each budget against the month's spending (`GET /api/budgets?month=`), the same call the Budgets tab
 * makes for a past month. */
export function useBudgetsIn(month: string) {
  return useQuery({ queryKey: ["budgets", "in", month], queryFn: () => api<Budget[]>(`/budgets?month=${month}`) });
}

/** The one figure a collapsed card shows: the budget closest to its limit, or how many are set. */
export function BudgetsHeadline({ event }: Pick<Props, "event">) {
  const budgets = useBudgetsIn(event.params.month);
  if (budgets.isLoading) return <span className="caption">Loading…</span>;
  if (!budgets.data) return <span className="caption">Not loaded</span>;
  if (budgets.data.length === 0) return <span className="caption">No budgets set</span>;
  const tightest = budgets.data.reduce((a, b) => (b.percent > a.percent ? b : a));
  return (
    <span className="panel-figure">
      <span className="num">{tightest.percent}% used</span>
      <span className="caption">
        {tightest.name}, {formatMoney(tightest.spent)} of {formatMoney(tightest.limit)}
      </span>
    </span>
  );
}

/** The month's budgets with their bars, as the Budgets tab draws a month: read-only, at today's limits. */
export function BudgetsPanel({ event, timezone }: Props) {
  const budgets = useBudgetsIn(event.params.month);
  if (budgets.isLoading) return <p className="state">Loading…</p>;
  if (budgets.isError || !budgets.data) return <p className="state error-text">Couldn't load the budgets.</p>;
  return <PastBudgets budgets={budgets.data} month={event.params.month} timezone={timezone} />;
}
