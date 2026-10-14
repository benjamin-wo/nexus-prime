import { useState } from "react";

import type { Summary } from "../api";
import { formatMoney } from "../format";
import { CategoryTransactions } from "./CategoryTransactions";

type Row = Summary["by_category"][number];

// The four largest get their own swatch from the palette, alternating dark and
// light so neighbours differ in more than hue; the rest share the mist.
const SWATCHES = ["sw-1", "sw-2", "sw-3", "sw-4"];

const keyOf = (row: Row) => `${row.category_id ?? "none"}-${row.total.currency}`;

/** Spending by category: one bar split by share, then every category with its
 * swatch, amount and share in text, so colour is never the only label. Given the
 * period, each category opens to show the transactions behind it. */
export function CategoryBars({
  rows,
  period,
  timezone,
}: {
  rows: Row[];
  period?: { start: string; end: string };
  timezone?: string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (rows.length === 0)
    return <p className="state">No spending recorded in this period.</p>;
  const total = rows.reduce((sum, r) => sum + Number(r.total.amount), 0);
  const swatch = (i: number) => SWATCHES[i] ?? "rest";
  return (
    <div className="split">
      <div className="split-bar" aria-hidden="true">
        {rows.map((row, i) => {
          const share =
            total > 0 ? (Number(row.total.amount) / total) * 100 : 0;
          return share > 0 ? (
            <span
              key={keyOf(row)}
              className={swatch(i)}
              style={{ flexGrow: share }}
            />
          ) : null;
        })}
      </div>
      <ul className="split-list" aria-label="Spending by category">
        {rows.map((row, i) => {
          const name = row.category_name ?? "Uncategorised";
          const value = formatMoney(row.total);
          const share =
            total > 0
              ? Math.round((Number(row.total.amount) / total) * 100)
              : 0;
          const key = keyOf(row);
          const label = (
            <>
              <span className={`swatch ${swatch(i)}`} aria-hidden="true" />
              <span className="wrap split-name">{name}</span>
              <span className="caption">{share}%</span>
              <span className="num">{value}</span>
              <span className="sr-only">
                {name}: {value} across {row.count}{" "}
                {row.count === 1 ? "transaction" : "transactions"}
              </span>
            </>
          );
          if (!period) {
            return (
              <li key={key} className="split-row">
                {label}
              </li>
            );
          }
          const shown = open === key;
          return (
            <li key={key} className="split-item">
              <button
                type="button"
                className="split-row split-toggle"
                aria-expanded={shown}
                aria-label={`${name}: ${value}, ${share}% of spending, ${row.count} ${row.count === 1 ? "transaction" : "transactions"}`}
                aria-controls={`spent-${key}`}
                onClick={() => setOpen(shown ? null : key)}
              >
                {label}
                <span className="chevron" aria-hidden="true" />
              </button>
              {shown && (
                <CategoryTransactions
                  id={`spent-${key}`}
                  name={name}
                  timezone={timezone}
                  pick={{ category: row.category_id, ...period }}
                />
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
