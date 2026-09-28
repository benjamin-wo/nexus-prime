import type { Summary } from "../api";
import { formatMoney } from "../format";

type Row = Summary["by_category"][number];

/** Spending by category: one series, ember bars from a shared baseline, value at each tip. */
export function CategoryBars({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return <p className="state">No spending recorded in this period.</p>;
  const max = Math.max(...rows.map((r) => Number(r.total.amount)));
  return (
    <ul className="bars" aria-label="Spending by category">
      {rows.map((row) => {
        const name = row.category_name ?? "Uncategorised";
        const share = max > 0 ? (Number(row.total.amount) / max) * 100 : 0;
        const value = formatMoney(row.total);
        return (
          <li key={`${row.category_id}-${row.total.currency}`} className="bar-row" tabIndex={0}>
            <span className="wrap">{name}</span>
            <span className="bar-track" aria-hidden="true">
              <span className="bar" style={{ width: `${Math.max(share, 1)}%`, display: "block" }} />
            </span>
            <span className="num">{value}</span>
            <span className="bar-tip" role="tooltip">
              {name}: {value} across {row.count} {row.count === 1 ? "transaction" : "transactions"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
