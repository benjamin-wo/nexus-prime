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
import { MonthPicker } from "../components/MonthPicker";
import { PastBudgets, usePastBudgets } from "../components/PastBudgets";
import { StatTile } from "../components/StatTile";
import {
  formatChange,
  formatDate,
  formatMoney,
  formatShortDate,
  moveLabel,
} from "../format";
import { type MonthKey, monthLabel, monthName, monthRange, shiftMonth } from "../months";
import { AccentTitle } from "../motion";
import { useMonthParam } from "../useMonthParam";

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

function shortName(m: Spending["months"][number]): string {
  const name = MONTH.format(new Date(m.month));
  return m.to_date ? `${name} so far` : name;
}

/** Money out per month: quiet bars for past months (striped rose only when over
 * the overall budget), this month so far in solid indigo over the outline of a
 * usual month (so early in the month a short bar reads as "so far"), and the
 * budget as a dashed line. Given `onPick`, each bar is a button that opens its
 * month ("October 2026: SGD 2,140.00"), and the `picked` month is outlined. */
export function SpendingChart({
  data,
  picked,
  onPick,
}: {
  data: Spending;
  picked?: MonthKey;
  onPick?: (month: MonthKey) => void;
}) {
  const budget = data.budget ? Number(data.budget.amount) : null;
  const { usual } = usualMonth(data.months);
  const top = Math.max(1, budget ?? 0, usual ?? 0, ...data.months.map((m) => Number(m.spent.amount)));
  const anyOver = budget !== null && data.months.some((m) => !m.to_date && Number(m.spent.amount) > budget);
  const pct = (value: number) => `${Math.max(2, (value / top) * 100)}%`;
  const isPicked = (m: Spending["months"][number]) => picked !== undefined && m.month.slice(0, 7) === picked;
  const pickedPast = data.months.some((m) => !m.to_date && isPicked(m));
  return (
    <div className="month-chart">
      <div className="month-plot">
        <ul className="month-bars" aria-label="Spending by month">
          {data.months.map((m) => {
            const value = Number(m.spent.amount);
            const over = budget !== null && value > budget;
            const key = m.month.slice(0, 7);
            const picks = onPick !== undefined;
            const marks = (
              <>
                {m.to_date && usual !== null && <span className="month-usual" aria-hidden="true" style={{ height: pct(usual) }} />}
                <span className={`month-bar${m.to_date ? " now" : over ? " over" : ""}`} style={{ height: pct(value) }} />
              </>
            );
            return (
              <li key={m.month} className={`month${picks && isPicked(m) ? " picked" : ""}`}>
                {picks ? (
                  <button
                    type="button"
                    className="month-hit"
                    aria-pressed={isPicked(m)}
                    aria-label={`${monthLabel(key)}${m.to_date ? ", so far" : ""}: ${formatMoney(m.spent)}${over ? ", over budget" : ""}`}
                    onClick={() => onPick(key)}
                  >
                    {marks}
                  </button>
                ) : (
                  <>
                    {marks}
                    <span className="sr-only">
                      {shortName(m)}: {formatMoney(m.spent)}
                      {over ? ", over budget" : ""}
                    </span>
                  </>
                )}
              </li>
            );
          })}
        </ul>
        {budget !== null && <div className="budget-line" aria-hidden="true" style={{ bottom: `${(budget / top) * 100}%` }} />}
      </div>
      <div className="month-labels" aria-hidden="true">
        {data.months.map((m) => (
          <span key={m.month} className={[m.to_date ? "now" : "", onPick && isPicked(m) ? "picked" : ""].filter(Boolean).join(" ") || undefined}>
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
        {onPick && pickedPast && (
          <span>
            <i className="key picked" />
            Month shown
          </span>
        )}
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
  picked,
  past,
  onPick,
}: {
  spending?: Spending;
  summary?: Summary;
  overall?: Budget;
  picked: MonthKey;
  /** The picked month is over: budget left and money received are about this month, so they go. */
  past: boolean;
  onPick: (month: MonthKey) => void;
}) {
  const now = spending?.months.at(-1);
  const { usual, count } = usualMonth(spending?.months ?? []);
  const received = summary?.totals.find((t) => t.direction === "in");
  return (
    <Block id="spending-months" title="Spending by month" className="spend-card">
      {spending ? <SpendingChart data={spending} picked={picked} onPick={onPick} /> : <p className="state">Loading…</p>}
      <div className={`mini-tiles${past ? " single" : ""}`}>
        {past ? null : overall ? (
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
 * worth one tap. Without budgets there is nothing to say: the headline offers to set one. */
function Nudge({
  budgets,
  timezone,
  onAsk,
}: {
  budgets?: Budget[];
  timezone: string;
  onAsk: (text: string) => void;
}) {
  const tightest = [...(budgets ?? [])].sort((a, b) => b.percent - a.percent)[0];
  if (!tightest) return null;
  const left = daysLeft(timezone);
  const what = tightest.category_id === null ? "your overall budget" : tightest.name;
  return (
    <section className="nudge" aria-label="From Nexus">
      <span className="assistant-mark" aria-hidden="true">
        <Icon name="sparkle" size={18} />
      </span>
      <p>
        You've used <span className="hl">{tightest.percent}%</span> of {what}{" "}
        with {left} {left === 1 ? "day" : "days"} to go. Want me to look at
        where it went?
      </p>
      <div className="chips">
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
      </div>
    </section>
  );
}

/** The answer to "am I OK this month?", above the tiles: what is spent and, given an overall
 * budget, how much of it is left ("SGD 87.60 left of SGD 125.00", or how far over). Without a
 * budget it says what is spent and offers to set one; a past month just says what was spent. */
function Headline({
  spent,
  past,
  month,
  budgetsLoaded,
  overall,
}: {
  spent?: Money;
  past: boolean;
  month: MonthKey;
  budgetsLoaded: boolean;
  overall?: Budget;
}) {
  if (!spent) return null;
  const when = past ? `in ${monthName(month)}` : "this month";
  const budget = past ? undefined : overall;
  const over = budget !== undefined && Number(budget.remaining.amount) < 0;
  return (
    <p className="overview-headline">
      {/* Against a budget, its own spent figure, so spent and left add up to the limit. */}
      <span className="overview-figure">{formatMoney(budget ? budget.spent : spent)}</span> spent
      {budget === undefined ? (
        ` ${when}`
      ) : (
        <>
          {" · "}
          <span className="overview-figure">
            {formatMoney(over ? { ...budget.remaining, amount: String(-Number(budget.remaining.amount)) } : budget.remaining)}
          </span>{" "}
          <span className="overview-tail">
            {over ? `over your ${formatMoney(budget.limit)} budget` : `left of ${formatMoney(budget.limit)}`}
          </span>
        </>
      )}
      {!past && budgetsLoaded && !overall && (
        <Link className="overview-set" to="/accounting/budgets">
          Set a budget
        </Link>
      )}
    </p>
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

/** `start=…&end=…` for a whole month, the way `/summary` takes a period (the end is included). */
function rangeParams(month: MonthKey): string {
  const { start, end } = monthRange(month);
  return `start=${start}&end=${end}`;
}

/** "SGD 180.00 less than September": a month's spending against the month before. */
function compare(spent: Money, before: Money, from: MonthKey): string {
  const name = monthName(from);
  if (Number(before.amount) === 0) return `Nothing spent in ${name}`;
  const gap = Number(spent.amount) - Number(before.amount);
  if (Math.abs(gap) < 0.005) return `Same as ${name}`;
  const shown = formatMoney({ amount: Math.abs(gap).toFixed(2), currency: spent.currency });
  return `${shown} ${gap < 0 ? "less" : "more"} than ${name}`;
}

export function Dashboard({
  me,
  onAsk,
}: {
  me: Me;
  onAsk: (text: string) => void;
}) {
  const { month, current, past, setMonth } = useMonthParam(me.user.timezone);
  const summary = useQuery({
    queryKey: ["summary", month],
    queryFn: () => api<Summary>(past ? `/summary?${rangeParams(month)}` : "/summary"),
  });
  const budgets = useQuery({
    queryKey: ["budgets"],
    queryFn: () => api<Budget[]>("/budgets"),
  }).data;
  const spendingQuery = useQuery({
    queryKey: ["spending-months"],
    queryFn: () => api<Spending>("/spending/months"),
  });
  const spending = spendingQuery.data;
  // The month before the one shown, for the comparison: from the chart's months when
  // it holds that month, else the month's own summary.
  const before = shiftMonth(month, -1);
  const beforeRow = spending?.months.find((m) => !m.to_date && m.month.slice(0, 7) === before);
  const beforeSummary = useQuery({
    queryKey: ["summary", before],
    queryFn: () => api<Summary>(`/summary?${rangeParams(before)}`),
    enabled: past && !beforeRow && (spendingQuery.isSuccess || spendingQuery.isError),
  });
  const beforeSpent = beforeRow?.spent ?? beforeSummary.data?.totals.find((t) => t.direction === "out")?.total;
  const pastBudgets = usePastBudgets(month, past);
  // What only makes sense now (the latest entries, who owes you) isn't fetched for a past month.
  const latest = useQuery({
    queryKey: ["transactions", "latest"],
    queryFn: () => api<Page>("/transactions?limit=5"),
    enabled: !past,
  }).data;
  const ious = useQuery({
    queryKey: ["ious"],
    queryFn: () => api<Iou[]>("/ious"),
    enabled: !past,
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
    summary.data?.put_away && wallets?.some((w) => w.kind !== "spending" && w.kind !== "cash")
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
            <AccentTitle text={past ? "Looking back" : "This month"} />
          </h1>
          {past ? (
            spent &&
            beforeSpent && <p className="muted">{compare(spent.total, beforeSpent, before)}</p>
          ) : (
            summary.data && (
              <p className="muted">
                {formatDate(summary.data.start)} to {formatDate(summary.data.end)}
              </p>
            )
          )}
        </div>
        <div className="quick">
          <MonthPicker month={month} current={current} onChange={setMonth} />
        </div>
      </div>
      <Headline
        spent={spent?.total}
        past={past}
        month={month}
        budgetsLoaded={budgets !== undefined}
        overall={overall}
      />

      {summary.isError && (
        <p className="error-text">Couldn't load {past ? `${monthLabel(month)}'s` : "this month's"} totals.</p>
      )}
      {!past && <Nudge budgets={budgets} timezone={me.user.timezone} onAsk={onAsk} />}
      <div className="tiles tiles-quiet">
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
            label="Saved"
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
                key={month}
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
          <SpendingByMonth
            spending={spending}
            summary={summary.data}
            overall={overall}
            picked={month}
            past={past}
            onPick={setMonth}
          />
        </div>
        <div className="stack">
          {past ? (
            <Block
              id="past-budgets"
              title="Budgets"
              action={<span className="caption">Against today's limits</span>}
            >
              {pastBudgets.isLoading && <p className="state">Loading…</p>}
              {pastBudgets.isError && <p className="state error-text">Couldn't load that month's budgets.</p>}
              {pastBudgets.data && (
                <PastBudgets budgets={pastBudgets.data} month={month} timezone={me.user.timezone} />
              )}
            </Block>
          ) : (
            <>
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
            </>
          )}
        </div>
      </div>
    </>
  );
}
