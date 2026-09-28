import { useQuery } from "@tanstack/react-query";

import { api, type Iou, type Me, type Summary } from "../api";
import { CategoryBars } from "../components/CategoryBars";
import { StatTile } from "../components/StatTile";
import { formatDate, formatMoney } from "../format";

function totalsIn(summary: Summary, direction: "in" | "out", home: string) {
  const rows = summary.totals.filter((t) => t.direction === direction);
  const main = rows.find((t) => t.total.currency === home);
  const others = rows.filter((t) => t.total.currency !== home).map((t) => formatMoney(t.total));
  return { main: main?.total.amount ?? "0", others };
}

export function Dashboard({ me, onLog, onOpenChat }: { me: Me; onLog: () => void; onOpenChat: () => void }) {
  const home = me.user.home_currency;
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => api<Summary>("/summary") });
  const ious = useQuery({ queryKey: ["ious"], queryFn: () => api<Iou[]>("/ious") });

  const spent = summary.data ? totalsIn(summary.data, "out", home) : null;
  const received = summary.data ? totalsIn(summary.data, "in", home) : null;
  const net = spent && received ? Number(received.main) - Number(spent.main) : null;
  const inHome = summary.data?.by_category.filter((c) => c.total.currency === home) ?? [];
  const otherCurrencies = (summary.data?.by_category.length ?? 0) - inHome.length;

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
          <button type="button" className="btn" disabled title="Coming in a later update">
            Add bill
          </button>
          <button type="button" className="btn" disabled title="Coming in a later update">
            View budgets
          </button>
        </div>
      </div>

      {summary.isError && <p className="error-text">Couldn't load this month's totals.</p>}
      <div className="tiles">
        <StatTile
          label="Spent"
          value={spent ? formatMoney({ amount: spent.main, currency: home }) : "…"}
          extra={spent?.others.length ? `Also ${spent.others.join(", ")}, not converted` : undefined}
        />
        <StatTile
          label="Received"
          value={received ? formatMoney({ amount: received.main, currency: home }) : "…"}
          extra={received?.others.length ? `Also ${received.others.join(", ")}, not converted` : undefined}
        />
        <StatTile
          label="Net"
          value={net === null ? "…" : formatMoney({ amount: String(net), currency: home })}
          extra={`${home} only`}
        />
      </div>

      <div className="dash-grid">
        <section className="card" aria-labelledby="by-category">
          <div className="card-head">
            <h2 id="by-category">Spending by category</h2>
            <span className="caption">{home}</span>
          </div>
          {summary.isLoading ? <p className="state">Loading…</p> : <CategoryBars rows={inHome} />}
          {otherCurrencies > 0 && (
            <p className="muted">
              Spending in other currencies isn't shown here; see the ledger. Conversion arrives in a later update.
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
