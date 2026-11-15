import { useQuery } from "@tanstack/react-query";

import { api, type Money } from "../api";
import { formatMoney, formatShortDate } from "../format";
import type { PanelEvent } from "./types";

type OutlookItem = { day: string; kind: string; label: string; direction: "in" | "out"; amount: Money | null };

/** `GET /api/month-outlook`: where a month ends up, in the home currency. */
export type MonthOutlook = {
  month: string;
  status: "current" | "past" | "future";
  currency: string;
  received: Money;
  spent: Money;
  moved: Money;
  net_so_far: Money;
  expected_in: Money;
  expected_out: Money;
  projected_net: Money;
  overall: Money;
  headroom: Money;
  shortfall: Money;
  items: OutlookItem[];
  no_amount: string[];
  unconverted: Money[];
};

export function useMonthOutlook(month: string) {
  return useQuery({ queryKey: ["month-outlook", month], queryFn: () => api<MonthOutlook>(`/month-outlook?month=${month}`) });
}

const positive = (m: Money) => Number(m.amount) > 0;
/** The most upcoming items a compact panel lists. */
const MAX_ITEMS = 6;

/** The one figure a collapsed card shows: where the month ends up. */
export function MonthOutlookHeadline({ event }: { event: Extract<PanelEvent, { kind: "finance.month_outlook" }> }) {
  const outlook = useMonthOutlook(event.params.month);
  if (outlook.isLoading) return <span className="caption">Loading…</span>;
  if (!outlook.data) return <span className="caption">Not loaded</span>;
  return (
    <span className="panel-figure">
      <span className="num">{formatMoney(outlook.data.status === "past" ? outlook.data.net_so_far : outlook.data.projected_net)}</span>
      <span className="caption">{outlook.data.status === "past" ? "net that month" : "left by month end"}</span>
    </span>
  );
}

function Row({ label, value, strong }: { label: string; value: Money; strong?: boolean }) {
  return (
    <div className={`panel-row${strong ? " panel-row-strong" : ""}`}>
      <dt>{label}</dt>
      <dd className="num">{formatMoney(value)}</dd>
    </div>
  );
}

/** What came in and went out, what is still expected and what that leaves. Read-only. */
export function MonthOutlookPanel({ event }: { event: Extract<PanelEvent, { kind: "finance.month_outlook" }> }) {
  const outlook = useMonthOutlook(event.params.month);
  if (outlook.isLoading) return <p className="state">Loading…</p>;
  if (outlook.isError || !outlook.data) return <p className="state error-text">Couldn't load this month's outlook.</p>;
  const o = outlook.data;
  const ahead = o.status !== "past";
  const short = positive(o.shortfall);
  return (
    <div className="panel-outlook">
      <dl className="panel-rows" aria-label="So far">
        <Row label="Came in" value={o.received} />
        <Row label="Spent" value={o.spent} />
        {positive(o.moved) && <Row label="Moved to your wallets" value={o.moved} />}
        <Row label="Net so far" value={o.net_so_far} strong={!ahead} />
      </dl>
      {ahead && (
        <dl className="panel-rows" aria-label="Still to come">
          <Row label="Still expected in" value={o.expected_in} />
          <Row label="Still expected out" value={o.expected_out} />
          <Row label="Left by month end" value={o.projected_net} strong />
        </dl>
      )}
      {ahead && (
        <p className={`panel-note${short ? " panel-note-warn" : ""}`}>
          {short
            ? `${formatMoney(o.shortfall)} short by month end.`
            : positive(o.headroom)
              ? `Room for ${formatMoney(o.headroom)} more everyday spending.`
              : "No room left for more everyday spending."}
        </p>
      )}
      {ahead && o.items.length > 0 && (
        <div>
          <h4 className="panel-sub">Coming up</h4>
          <ul className="panel-items">
            {o.items.slice(0, MAX_ITEMS).map((item, i) => (
              <li key={`${item.day}-${item.label}-${i}`}>
                <span className="caption panel-day">{formatShortDate(`${item.day}T00:00:00Z`, "UTC")}</span>
                <span className="wrap">{item.label}</span>
                <span className="num">
                  {item.amount ? `${item.direction === "in" ? "+" : "−"}${formatMoney(item.amount)}` : "no amount"}
                </span>
              </li>
            ))}
          </ul>
          {o.items.length > MAX_ITEMS && <p className="caption">and {o.items.length - MAX_ITEMS} more</p>}
        </div>
      )}
      {o.no_amount.length > 0 && <p className="caption">Left out, no amount or rate yet: {o.no_amount.join(", ")}</p>}
      {o.unconverted.length > 0 && <p className="caption">Not counted, no exchange rate yet: {o.unconverted.map(formatMoney).join(", ")}</p>}
    </div>
  );
}
