import type { Summary } from "../api";
import { formatMoney } from "../format";

type Row = Summary["by_category"][number];

// The four largest get their own swatch; the rest share the grey one. Solid and
// hatched alternate so neighbours differ in more than hue.
const SWATCHES = ["solid-orange", "hatch-orange", "solid-sky", "hatch-sky"];

/** Spending by category: one bar split by share, then every category with its
 * swatch, amount and share in text, so colour is never the only label. */
export function CategoryBars({ rows }: { rows: Row[] }) {
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
              key={`${row.category_id}-${row.total.currency}`}
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
          return (
            <li
              key={`${row.category_id}-${row.total.currency}`}
              className="split-row"
            >
              <span className={`swatch ${swatch(i)}`} aria-hidden="true" />
              <span className="wrap split-name">{name}</span>
              <span className="caption">{share}%</span>
              <span className="num">{value}</span>
              <span className="sr-only">
                {name}: {value} across {row.count}{" "}
                {row.count === 1 ? "transaction" : "transactions"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
