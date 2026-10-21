import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Link } from "react-router-dom";

import {
  api,
  type Budget,
  type Iou,
  type Me,
  type Money,
  type Page,
  type Spending,
  type Summary,
  type Wallet,
} from "../api";
import { Block } from "../components/Block";
import { CategoryBars } from "../components/CategoryBars";
import { Icon } from "../components/Icon";
import { StatTile } from "../components/StatTile";
import {
  formatChange,
  formatDate,
  formatMoney,
  formatShortDate,
  moveLabel,
} from "../format";
import { AccentTitle } from "../motion";

type Total = Summary["totals"][number];

function list(amounts: Money[]): string {
  return amounts.map(formatMoney).join(", ");
}

/** What went into a converted total, in words: foreign amounts included, and any left out. */
export function conversionNote(total: Total | undefined): string | undefined {
  if (!total) return undefined;
  const parts = [];
  if (total.converted.length)
    parts.push(`Includes ${list(total.converted)}, converted`);
  if (total.unconverted.length)
    parts.push(`${list(total.unconverted)} left out: no rate`);
  return parts.length ? parts.join(". ") : undefined;
}

const MONTH = new Intl.DateTimeFormat(undefined, {
  month: "short",
  timeZone: "UTC",
});

/** A usual month: the average of the full months before this one that had any
 * spending, and how many there were. */
function usualMonth(months: Spending["months"]): { usual: number | null; count: number } {
  const past = months.filter((m) => !m.to_date && Number(m.spent.amount) > 0);
  const usual = past.length ? past.reduce((sum, m) => sum + Number(m.spent.amount), 0) / past.length : null;
  return { usual, count: past.length };
}

function monthName(m: Spending["months"][number]): string {
  const name = MONTH.format(new Date(m.month));
  return m.to_date ? `${name} so far` : name;
}

/** Money out per month: quiet bars for past months (striped rose only when over
 * the overall budget), this month so far in solid indigo over the outline of a
 * usual month (so early in the month a short bar reads as "so far"), and the
 * budget as a dashed line. */
export function SpendingChart({ data }: { data: Spending }) {
  const budget = data.budget ? Number(data.budget.amount) : null;
  const { usual } = usualMonth(data.months);
  const top = Math.max(1, budget ?? 0, usual ?? 0, ...data.months.map((m) => Number(m.spent.amount)));
  const anyOver = budget !== null && data.months.some((m) => !m.to_date && Number(m.spent.amount) > budget);
  const pct = (value: number) => `${Math.max(2, (value / top) * 100)}%`;
  return (
    <div className="month-chart">
      <div className="month-plot">
        <ul className="month-bars" aria-label="Spending by month">
          {data.months.map((m) => {
            const value = Number(m.spent.amount);
            const over = budget !== null && value > budget;
            return (
              <li key={m.month} className="month">
                {m.to_date && usual !== null && <span className="month-usual" aria-hidden="true" style={{ height: pct(usual) }} />}
                <span className={`month-bar${m.to_date ? " now" : over ? " over" : ""}`} style={{ height: pct(value) }} />
                <span className="sr-only">
                  {monthName(m)}: {formatMoney(m.spent)}
                  {over ? ", over budget" : ""}
                </span>
              </li>
            );
          })}
        </ul>
        {budget !== null && <div className="budget-line" aria-hidden="true" style={{ bottom: `${(budget / top) * 100}%` }} />}
      </div>
      <div className="month-labels" aria-hidden="true">
        {data.months.map((m) => (
          <span key={m.month} className={m.to_date ? "now" : undefined}>
            {MONTH.format(new Date(m.month))}
          </span>
        ))}
      </div>
      <div className="legend" aria-hidden="true">
        <span>
          <i className="key past" />
          {budget !== null ? "Within budget" : "Past months"}
        </span>
        {anyOver && (
          <span>
            <i className="key over" />
            Over budget
          </span>
        )}
        <span>
          <i className="key now" />
          This month so far
        </span>
        {usual !== null && (
          <span>
            <i className="key usual" />A usual month
          </span>
        )}
        {budget !== null && (
          <span>
            <i className="key line" />
            Monthly budget
          </span>
        )}
      </div>
    </div>
  );
}

/** Six months of spending, with two tiles under the chart: budget left (or money
 * received) and a usual month. The biggest category is "Where it went", beside it. */
function SpendingByMonth({
  spending,
  summary,
  overall,
}: {
  spending?: Spending;
  summary?: Summary;
  overall?: Budget;
}) {
  const now = spending?.months.at(-1);
  const { usual, count } = usualMonth(spending?.months ?? []);
  const received = summary?.totals.find((t) => t.direction === "in");
  return (
    <Block id="spending-months" title="Spending by month" className="spend-card">
      {spending ? <SpendingChart data={spending} /> : <p className="state">Loading…</p>}
      <div className="mini-tiles">
        {overall ? (
          <div className="mini-tile">
            <span className="caption">Budget left</span>
            <span className="mini-value">{formatMoney(overall.remaining)}</span>
            <span className="caption">{overall.percent}% used</span>
          </div>
        ) : (
          <div className="mini-tile">
            <span className="caption">Received</span>
            <span className="mini-value">{received ? formatMoney(received.total) : "…"}</span>
            <span className="caption">This month</span>
          </div>
        )}
        <div className="mini-tile">
          <span className="caption">A usual month</span>
          <span className="mini-value">
            {!now
              ? "…"
              : usual === null
                ? "Not yet"
                : formatMoney({ amount: usual.toFixed(2), currency: now.spent.currency })}
          </span>
          <span className="caption">
            {usual === null ? "Needs a full month" : `Average of the last ${count === 1 ? "month" : `${count} months`}`}
          </span>
        </div>
      </div>
    </Block>
  );
}

/** Days left in this month after today, in the user's timezone. */
function daysLeft(timezone: string): number {
  const [y, m, d] = new Intl.DateTimeFormat("en-CA", { timeZone: timezone })
    .format(new Date())
    .split("-")
    .map(Number);
  return new Date(Date.UTC(y, m, 0)).getUTCDate() - d;
}

/** One line from Nexus about the budget closest to running out, with questions
 * worth one tap; without budgets, an offer to set one. */
function Nudge({
  budgets,
  timezone,
  onAsk,
}: {
  budgets?: Budget[];
  timezone: string;
  onAsk: (text: string) => void;
}) {
  if (!budgets) return null;
  const tightest = [...budgets].sort((a, b) => b.percent - a.percent)[0];
  const left = daysLeft(timezone);
  const what = tightest
    ? tightest.category_id === null
      ? "your overall budget"
      : tightest.name
    : "";
  return (
    <section className="nudge" aria-label="From Nexus">
      <span className="assistant-mark" aria-hidden="true">
        <Icon name="sparkle" size={18} />
      </span>
      {tightest ? (
        <p>
          You've used <span className="hl">{tightest.percent}%</span> of {what}{" "}
          with {left} {left === 1 ? "day" : "days"} to go. Want me to look at
          where it went?
        </p>
      ) : (
        <p>Set a monthly budget and I'll tell you when it's getting tight.</p>
      )}
      <div className="chips">
        {tightest ? (
          <>
            <button
              type="button"
              className="ask-chip"
              onClick={() =>
                onAsk(
                  tightest.category_id === null
                    ? "Where did my money go this month?"
                    : `Where did my ${tightest.name} money go this month?`,
                )
              }
            >
              Show me
            </button>
            <Link className="ask-chip" to="/accounting/budgets">
              Change budgets
            </Link>
          </>
        ) : (
          <Link className="ask-chip" to="/accounting/budgets">
            Set a budget
          </Link>
        )}
      </div>
    </section>
  );
}

function Latest({ page, timezone }: { page?: Page; timezone: string }) {
  return (
    <Block
      id="latest"
      title="Latest"
      action={
        <Link className="btn btn-small" to="/accounting/ledger">
          See all
        </Link>
      }
    >
      {!page ? (
        <p className="state">Loading…</p>
      ) : page.items.length === 0 ? (
        <p className="state">Nothing logged yet.</p>
      ) : (
        <ul className="rows">
          {page.items.map((t) => {
            const move = t.direction === "move";
            const name =
              t.counterparty ??
              (move ? moveLabel(t) : t.direction === "in" ? "Money in" : "Money out");
            // A move is neither spent nor received: shown without a sign or a colour.
            const signed = {
              ...t.amount,
              amount:
                t.direction === "out" ? `-${t.amount.amount}` : t.amount.amount,
            };
            return (
              <li key={t.id} className="row">
                <span
                  className={`row-icon${t.direction === "in" ? " in" : ""}`}
                  aria-hidden="true"
                >
                  {name.slice(0, 1).toUpperCase()}
                </span>
                <span className="row-main">
                  <span className="wrap">{name}</span>
                  <span className="caption">
                    {formatShortDate(t.occurred_at, timezone)}
                    {t.status === "pending" ? " · pending" : ""}
                  </span>
                </span>
                <span className={`num${t.direction === "in" ? " up" : ""}`}>
                  {move ? formatMoney(t.amount) : formatChange(signed)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Block>
  );
}

export function Dashboard({
  me,
  onLog,
  onAsk,
}: {
  me: Me;
  onLog: () => void;
  onAsk: (text: string) => void;
}) {
  const summary = useQuery({
    queryKey: ["summary"],
    queryFn: () => api<Summary>("/summary"),
  });
  const budgets = useQuery({
    queryKey: ["budgets"],
    queryFn: () => api<Budget[]>("/budgets"),
  }).data;
  const spending = useQuery({
    queryKey: ["spending-months"],
    queryFn: () => api<Spending>("/spending/months"),
  }).data;
  const latest = useQuery({
    queryKey: ["transactions", "latest"],
    queryFn: () => api<Page>("/transactions?limit=5"),
  }).data;
  const ious = useQuery({
    queryKey: ["ious"],
    queryFn: () => api<Iou[]>("/ious"),
  });
  const wallets = useQuery({
    queryKey: ["wallets"],
    queryFn: () => api<Wallet[]>("/wallets"),
  }).data;
  const client = useQueryClient();
  const [repayError, setRepayError] = useState<string | null>(null);

  async function paidBack(iou: Iou) {
    setRepayError(null);
    try {
      await api(`/ious/${iou.split_id}/repaid`, { method: "POST", body: {} });
      void client.invalidateQueries({ queryKey: ["ious"] });
      void client.invalidateQueries({ queryKey: ["summary"] });
      void client.invalidateQueries({ queryKey: ["transactions"] });
    } catch (e) {
      setRepayError(
        e instanceof Error ? e.message : "Couldn't mark that paid back",
      );
    }
  }

  const overall = budgets?.find((b) => b.category_id === null);
  const home = summary.data?.currency ?? me.user.home_currency;
  const spent = summary.data?.totals.find((t) => t.direction === "out");
  const received = summary.data?.totals.find((t) => t.direction === "in");
  const net =
    spent && received
      ? Number(received.total.amount) - Number(spent.total.amount)
      : null;
  const partial = Boolean(
    spent?.unconverted.length || received?.unconverted.length,
  );
  // Money put away only means something once there is a wallet to put it in.
  const putAway =
    summary.data?.put_away && wallets?.some((w) => w.kind !== "spending")
      ? summary.data.put_away
      : null;
  const savingRate = summary.data?.saving_rate;
  const foreign = Boolean(
    spent?.converted.length || received?.converted.length,
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>
            <AccentTitle text="This month" />
          </h1>
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
        </div>
      </div>

      {summary.isError && (
        <p className="error-text">Couldn't load this month's totals.</p>
      )}
      <Nudge budgets={budgets} timezone={me.user.timezone} onAsk={onAsk} />
      <div className="tiles">
        <StatTile
          label="Spent"
          value={spent ? formatMoney(spent.total) : "…"}
          extra={conversionNote(spent)}
        />
        <StatTile
          label="Received"
          value={received ? formatMoney(received.total) : "…"}
          extra={conversionNote(received)}
        />
        <StatTile
          label="Net"
          value={
            net === null
              ? "…"
              : formatMoney({ amount: String(net), currency: home })
          }
          extra={partial ? "Leaves out amounts with no rate" : undefined}
        />
        {putAway && (
          <StatTile
            label="Put away"
            value={formatMoney(putAway)}
            extra={
              savingRate == null
                ? undefined
                : `${Math.round(savingRate * 100)}% of income`
            }
          />
        )}
      </div>

      <div className="pair">
        <div className="stack">
          <Block id="by-category" title="Where it went" action={<span className="caption">In {home}</span>}>
            {summary.isLoading ? (
              <p className="state">Loading…</p>
            ) : (
              <CategoryBars
                rows={summary.data?.by_category ?? []}
                period={summary.data && { start: summary.data.start, end: summary.data.end }}
                timezone={me.user.timezone}
              />
            )}
            {foreign && (
              <p className="muted">
                Foreign amounts are converted to {home} at the European Central
                Bank reference rate for their day (or the last business day before
                it).
              </p>
            )}
          </Block>
          <SpendingByMonth spending={spending} summary={summary.data} overall={overall} />
        </div>
        <div className="stack">
          <Latest page={latest} timezone={me.user.timezone} />
          <Block id="owed" title="Who owes you">
            {ious.isLoading && <p className="state">Loading…</p>}
            {ious.data?.length === 0 && (
              <p className="state">Nobody owes you anything.</p>
            )}
            {ious.data?.map((iou) => (
              <div key={iou.split_id} className="iou">
                <span className="wrap">
                  {iou.participant_name}
                  <br />
                  <span className="caption">
                    since{" "}
                    {formatDate(iou.expense_occurred_at, me.user.timezone)}
                  </span>
                </span>
                <span className="iou-end">
                  <span className="num">
                    {formatMoney(iou.outstanding)}
                    <span className="sr-only"> still owed</span>
                  </span>
                  <button
                    type="button"
                    className="btn btn-small"
                    aria-label={`${iou.participant_name} paid back ${formatMoney(iou.outstanding)}`}
                    onClick={() => void paidBack(iou)}
                  >
                    Paid back
                  </button>
                </span>
              </div>
            ))}
            {repayError && <p className="error-text">{repayError}</p>}
          </Block>
        </div>
      </div>
    </>
  );
}
