import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, type Iou, type Me, type Money, type Summary } from "../api";
import { CategoryBars } from "../components/CategoryBars";
import { StatTile } from "../components/StatTile";
import { formatDate, formatMoney } from "../format";

type Total = Summary["totals"][number];

function list(amounts: Money[]): string {
  return amounts.map(formatMoney).join(", ");
}

/** What went into a converted total, in words: foreign amounts included, and any left out. */
export function conversionNote(total: Total | undefined): string | undefined {
  if (!total) return undefined;
  const parts = [];
  if (total.converted.length) parts.push(`Includes ${list(total.converted)}, converted`);
  if (total.unconverted.length) parts.push(`${list(total.unconverted)} left out: no rate`);
  return parts.length ? parts.join(". ") : undefined;
}

export function Dashboard({ me, onLog, onOpenChat }: { me: Me; onLog: () => void; onOpenChat: () => void }) {
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => api<Summary>("/summary") });
  const ious = useQuery({ queryKey: ["ious"], queryFn: () => api<Iou[]>("/ious") });

  const home = summary.data?.currency ?? me.user.home_currency;
  const spent = summary.data?.totals.find((t) => t.direction === "out");
  const received = summary.data?.totals.find((t) => t.direction === "in");
  const net = spent && received ? Number(received.total.amount) - Number(spent.total.amount) : null;
  const partial = Boolean(spent?.unconverted.length || received?.unconverted.length);
  const foreign = Boolean(spent?.converted.length || received?.converted.length);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>This month</h1>
          {summary.data && (
            <p className="muted">
              {formatDate(summary.data.start)} to {formatDate(summary.data.end)}
            </p>
          )}
        </div>
        <div className="quick" aria-label="Quick actions">
          <button type="button" className="btn btn-primary" onClick={onLog}>
            Log expense
          </button>
          <button type="button" className="btn" onClick={onOpenChat}>
            Open chat
          </button>
          <button type="button" className="btn" disabled title="Coming in a later update">
            Import statement
          </button>
          <Link className="btn" to="/plan">
            Add bill
          </Link>
          <Link className="btn" to="/plan">
            View budgets
          </Link>
        </div>
      </div>

      {summary.isError && <p className="error-text">Couldn't load this month's totals.</p>}
      <div className="tiles">
        <StatTile label="Spent" value={spent ? formatMoney(spent.total) : "…"} extra={conversionNote(spent)} />
        <StatTile
          label="Received"
          value={received ? formatMoney(received.total) : "…"}
          extra={conversionNote(received)}
        />
        <StatTile
          label="Net"
          value={net === null ? "…" : formatMoney({ amount: String(net), currency: home })}
          extra={partial ? "Leaves out amounts with no rate" : undefined}
        />
      </div>

      <div className="dash-grid">
        <section className="card" aria-labelledby="by-category">
          <div className="card-head">
            <h2 id="by-category">Spending by category</h2>
            <span className="caption">{home}</span>
          </div>
          {summary.isLoading ? (
            <p className="state">Loading…</p>
          ) : (
            <CategoryBars rows={summary.data?.by_category ?? []} />
          )}
          {foreign && (
            <p className="muted">
              Foreign amounts are converted to {home} at the European Central Bank reference rate for their day (or
              the last business day before it).
            </p>
          )}
        </section>
        <section className="card" aria-labelledby="owed">
          <div className="card-head">
            <h2 id="owed">Who owes you</h2>
          </div>
          {ious.isLoading && <p className="state">Loading…</p>}
          {ious.data?.length === 0 && <p className="state">Nobody owes you anything.</p>}
          {ious.data?.map((iou) => (
            <div key={iou.split_id} className="iou">
              <span className="wrap">
                {iou.participant_name}
                <br />
                <span className="caption">since {formatDate(iou.expense_occurred_at, me.user.timezone)}</span>
              </span>
              <span className="num">
                {formatMoney(iou.outstanding)}
                <span className="sr-only"> still owed</span>
              </span>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}
