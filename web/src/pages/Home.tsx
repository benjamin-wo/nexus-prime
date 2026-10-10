import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type Budget,
  type FeedItem,
  type Holding,
  type Me,
  type Portfolio,
  type Run,
  type Spending,
  type Summary,
  type TripDetail,
} from "../api";
import { brief, suggestions } from "../brief";
import { Icon, departmentIcon } from "../components/Icon";
import { DEPARTMENTS } from "../departments";
import {
  formatChange,
  formatMoney,
  formatPercent,
  formatShortDate,
} from "../format";
import { AccentTitle, CountUp } from "../motion";
import { tripWhen } from "./Trips";

function greeting(timezone: string): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", {
      hour: "numeric",
      hourCycle: "h23",
      timeZone: timezone,
    }).format(new Date()),
  );
  return hour < 12
    ? "Good morning"
    : hour < 18
      ? "Good afternoon"
      : "Good evening";
}

function today(timezone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: timezone,
  }).format(new Date());
}

const RUNNING = new Set<Run["status"]>(["queued", "running"]);

function RunRow({ run, onCancel }: { run: Run; onCancel: (run: Run) => void }) {
  const going = RUNNING.has(run.status);
  const share = run.steps_total
    ? Math.round((run.steps_done / run.steps_total) * 100)
    : 0;
  return (
    <li className="run-row">
      <span className="wrap">
        {run.title}
        <br />
        <span className="caption">
          {going
            ? `${run.steps_done}/${run.steps_total} · ${run.progress}`
            : run.status === "failed"
              ? `Couldn't finish: ${run.error ?? "something went wrong"}`
              : run.status === "done"
                ? "Done"
                : "Cancelled"}
        </span>
        {going && (
          <span
            className="progress"
            role="progressbar"
            aria-label={`${run.title} progress`}
            aria-valuenow={share}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span style={{ width: `${share}%` }} />
          </span>
        )}
      </span>
      {going && (
        <button
          type="button"
          className="btn btn-small"
          onClick={() => onCancel(run)}
        >
          Cancel
        </button>
      )}
    </li>
  );
}

/** Nexus speaks first: a short brief from the user's own figures, a few one-tap
 * questions, and a box to ask anything. Every question opens the chat. */
function Assistant({
  parts,
  chips,
  onAsk,
}: {
  parts: ReturnType<typeof brief>;
  chips: string[];
  onAsk: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  function ask(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onAsk(text);
  }
  return (
    <section className="assistant" aria-label="Nexus">
      <div className="assistant-head">
        <span className="assistant-mark" aria-hidden="true">
          <Icon name="sparkle" />
        </span>
        <strong>Nexus</strong>
        <span className="pill">Your brief</span>
      </div>
      <p className="assistant-brief">
        {parts.map((p, i) =>
          p.hl ? (
            <span key={i} className="hl">
              {p.text}
            </span>
          ) : (
            <span key={i}>{p.text}</span>
          ),
        )}
      </p>
      <div className="chips" aria-label="Suggested questions">
        {chips.map((c) => (
          <button
            key={c}
            type="button"
            className="ask-chip"
            onClick={() => onAsk(c)}
          >
            {c}
          </button>
        ))}
      </div>
      <form className="ask" onSubmit={ask} aria-label="Ask Nexus">
        <label className="sr-only" htmlFor="ask-input">
          Ask Nexus
        </label>
        <input
          id="ask-input"
          className="ask-input"
          value={draft}
          maxLength={2000}
          onChange={(e) => setDraft(e.target.value)}
          placeholder='Ask, or tell me what you spent: "kopi 4.20"'
        />
        <button
          type="submit"
          className="ask-send"
          aria-label="Ask"
          disabled={!draft.trim()}
        >
          <Icon name="send" size={18} />
        </button>
      </form>
    </section>
  );
}

const MONTH = new Intl.DateTimeFormat(undefined, {
  month: "short",
  timeZone: "UTC",
});

/** Money out per month: hatched bars for past months (orange when over the overall
 * budget), a solid bar for this month so far, and the budget as a dashed line. */
function SpendingChart({ data }: { data: Spending }) {
  const budget = data.budget ? Number(data.budget.amount) : null;
  const top = Math.max(
    1,
    budget ?? 0,
    ...data.months.map((m) => Number(m.spent.amount)),
  );
  return (
    <div className="month-chart">
      <div className="month-plot">
        <ul className="month-bars" aria-label="Spending by month">
          {data.months.map((m) => {
            const value = Number(m.spent.amount);
            const over = budget !== null && value > budget;
            return (
              <li key={m.month} className="month">
                <span
                  className={`month-bar${m.to_date ? " now" : over ? " over" : ""}`}
                  style={{ height: `${Math.max(2, (value / top) * 100)}%` }}
                />
                <span className="sr-only">
                  {monthName(m)}: {formatMoney(m.spent)}
                  {over ? ", over budget" : ""}
                </span>
              </li>
            );
          })}
        </ul>
        {budget !== null && (
          <div
            className="budget-line"
            aria-hidden="true"
            style={{ bottom: `${(budget / top) * 100}%` }}
          />
        )}
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
          <i className="key within" />
          Within budget
        </span>
        <span>
          <i className="key over" />
          Over budget
        </span>
        <span>
          <i className="key now" />
          This month
        </span>
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

function monthName(m: Spending["months"][number]): string {
  const name = MONTH.format(new Date(m.month));
  return m.to_date ? `${name} so far` : name;
}

function SpendingCard({
  spending,
  summary,
  overall,
}: {
  spending?: Spending;
  summary?: Summary;
  overall?: Budget;
}) {
  const now = spending?.months.at(-1);
  const diff =
    now && spending
      ? Number(now.spent.amount) - Number(spending.last_month_to_date.amount)
      : null;
  const top = summary?.by_category[0];
  const spentTotal = summary?.totals.find((t) => t.direction === "out");
  const share =
    top && spentTotal && Number(spentTotal.total.amount) > 0
      ? Math.round(
          (Number(top.total.amount) / Number(spentTotal.total.amount)) * 100,
        )
      : null;
  const received = summary?.totals.find((t) => t.direction === "in");
  return (
    <section className="card spend-card" aria-labelledby="spent-month">
      <div className="card-head">
        <div className="figure">
          <h2 id="spent-month" className="figure-label">
            Spent this month
          </h2>
          <span className="figure-value">
            <CountUp value={now ? formatMoney(now.spent) : "…"} />
          </span>
        </div>
        <Link className="btn btn-small" to="/accounting">
          Details
        </Link>
      </div>
      {spending ? (
        <SpendingChart data={spending} />
      ) : (
        <p className="state">Loading…</p>
      )}
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
            <span className="mini-value">
              {received ? formatMoney(received.total) : "…"}
            </span>
            <span className="caption">This month</span>
          </div>
        )}
        <div className="mini-tile">
          <span className="caption">Against last month</span>
          <span
            className={`mini-value${diff !== null && diff < 0 ? " good" : ""}`}
          >
            {diff === null || !now
              ? "…"
              : formatChange({
                  amount: String(diff),
                  currency: now.spent.currency,
                })}
          </span>
          <span className="caption">
            {diff !== null && diff <= 0
              ? "Less by this date"
              : "More by this date"}
          </span>
        </div>
        <div className="mini-tile">
          <span className="caption">Biggest category</span>
          <span className="mini-value">
            {top ? (top.category_name ?? "Uncategorised") : "None yet"}
          </span>
          <span className="caption">
            {top
              ? `${formatMoney(top.total)}${share !== null ? `, ${share}%` : ""}`
              : "No spending yet"}
          </span>
        </div>
      </div>
    </section>
  );
}

function PortfolioCard({ portfolio }: { portfolio?: Portfolio }) {
  const totals = portfolio?.totals;
  const held = [...(portfolio?.holdings ?? [])]
    .sort(
      (a, b) =>
        Number(b.value_home?.amount ?? 0) - Number(a.value_home?.amount ?? 0),
    )
    .slice(0, 4);
  return (
    <section className="card" aria-labelledby="portfolio">
      <div className="card-head">
        <h2 id="portfolio" className="figure-label">
          Portfolio
        </h2>
        <Link className="btn btn-small" to="/investment">
          Open
        </Link>
      </div>
      {!portfolio ? (
        <p className="state">Loading…</p>
      ) : held.length === 0 ? (
        <p className="muted">
          No holdings yet.{" "}
          <Link to="/investment">Add them from a broker screenshot</Link>.
        </p>
      ) : (
        <>
          <span className="figure-value">
            <CountUp value={totals?.value ? formatMoney(totals.value) : "…"} />
          </span>
          {totals?.day_change && (
            <p
              className={Number(totals.day_change.amount) >= 0 ? "up" : "down"}
            >
              {formatChange(totals.day_change)}
              {totals.day_percent !== null &&
                ` (${formatPercent(totals.day_percent)})`}{" "}
              today
            </p>
          )}
          <ul className="rows" aria-label="Largest holdings">
            {held.map((h: Holding) => (
              <li key={h.symbol} className="row">
                <span className="row-icon">{h.symbol.slice(0, 2)}</span>
                <span className="row-main">
                  <Link to={`/investment/stocks/${h.symbol}`}>{h.symbol}</Link>
                  <span className="caption">
                    {h.value ? formatMoney(h.value) : "No price yet"}
                  </span>
                </span>
                {h.day_percent !== null && (
                  <span
                    className={`num ${Number(h.day_percent) >= 0 ? "up" : "down"}`}
                  >
                    {formatPercent(h.day_percent)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function NeedsYou({
  feed,
}: {
  feed: { data?: FeedItem[]; isLoading: boolean; isError: boolean };
}) {
  return (
    <section className="card" aria-labelledby="needs-you">
      <div className="card-head">
        <h2 id="needs-you">Needs you</h2>
      </div>
      {feed.isLoading && <p className="state">Loading…</p>}
      {feed.isError && (
        <p className="error-text">Couldn't load what needs you.</p>
      )}
      {feed.data?.length === 0 && (
        <p className="state">Nothing needs you right now.</p>
      )}
      {feed.data && feed.data.length > 0 && (
        <ul className="rows">
          {feed.data.map((item) => {
            const dept = DEPARTMENTS.find((d) => d.name === item.department);
            return (
              <li key={`${item.kind}:${item.text}`}>
                <Link
                  className={`row row-link${item.urgent ? " urgent" : ""}`}
                  to={item.link}
                >
                  <span className="row-icon" aria-hidden="true">
                    <Icon
                      name={
                        item.urgent ? "alert" : departmentIcon(item.department)
                      }
                      size={18}
                    />
                  </span>
                  <span className="row-main">
                    <span className="wrap">{item.text}</span>
                    <span className="caption">{dept?.label}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function BudgetsCard({ budgets }: { budgets?: Budget[] }) {
  const shown = [...(budgets ?? [])]
    .sort((a, b) => b.percent - a.percent)
    .slice(0, 4);
  return (
    <section className="card" aria-labelledby="budgets-home">
      <div className="card-head">
        <h2 id="budgets-home">Budgets this month</h2>
        <Link to="/accounting/plan">Edit</Link>
      </div>
      {!budgets ? (
        <p className="state">Loading…</p>
      ) : shown.length === 0 ? (
        <p className="muted">
          No budgets yet. <Link to="/accounting/plan">Set one</Link> and Nexus
          keeps count as you spend.
        </p>
      ) : (
        <ul className="budget-list">
          {shown.map((b) => (
            <li key={b.id}>
              <div className="budget-line-head">
                <span>{b.name}</span>
                <span className="secondary">
                  <span className="num">{formatMoney(b.spent)}</span> of{" "}
                  {formatMoney(b.limit)}
                </span>
              </div>
              <div
                className={`meter${b.percent >= 100 ? " meter-over" : b.percent >= 80 ? " meter-warn" : ""}`}
                role="meter"
                aria-label={`${b.name} budget used`}
                aria-valuenow={Math.min(b.percent, 100)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span style={{ width: `${Math.min(100, b.percent)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function days(start: string, end: string): string[] {
  const found: string[] = [];
  for (
    let d = new Date(`${start}T00:00:00Z`);
    d <= new Date(`${end}T00:00:00Z`) && found.length < 14;
    d.setUTCDate(d.getUTCDate() + 1)
  ) {
    found.push(d.toISOString().slice(0, 10));
  }
  return found;
}

const WEEKDAY = new Intl.DateTimeFormat(undefined, {
  weekday: "narrow",
  timeZone: "UTC",
});

function TripCard({
  detail,
  onAsk,
}: {
  detail: TripDetail;
  onAsk: (text: string) => void;
}) {
  const t = detail.trip;
  const gaps = new Set(detail.ready.nights_without_stay);
  return (
    <section className="card" aria-labelledby="trip-home">
      <div className="card-head">
        <h2 id="trip-home">{t.destination}</h2>
        <span className="pill">{tripWhen(t)}</span>
      </div>
      <p className="muted">
        {formatShortDate(t.start, "UTC")} to {formatShortDate(t.end, "UTC")}
      </p>
      <ul className="day-tiles" aria-label="Trip days">
        {days(t.start, t.end).map((d, i, all) => {
          const edge = i === 0 || i === all.length - 1;
          return (
            <li
              key={d}
              className={`day-tile${edge ? " edge" : ""}${gaps.has(d) ? " gap" : ""}`}
            >
              <span className="caption" aria-hidden="true">
                {WEEKDAY.format(new Date(`${d}T00:00:00Z`))}
              </span>
              <span>{Number(d.slice(8))}</span>
              {gaps.has(d) && (
                <span className="sr-only"> no place to stay</span>
              )}
            </li>
          );
        })}
      </ul>
      {gaps.size > 0 ? (
        <p>
          <span className="hl">
            {gaps.size} {gaps.size === 1 ? "night" : "nights"}
          </span>{" "}
          with no place to stay yet.
        </p>
      ) : detail.trip.budget ? (
        <p className="muted">
          {formatMoney(detail.spending.spent)} of{" "}
          {formatMoney(detail.trip.budget)} spent
        </p>
      ) : null}
      <div className="quick">
        {gaps.size > 0 && t.status === "upcoming" && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onAsk(`Find a place to stay in ${t.destination}`)}
          >
            Ask Nexus to find a stay
          </button>
        )}
        <Link className="btn" to={`/travel/trips/${t.id}`}>
          Open trip
        </Link>
      </div>
    </section>
  );
}

/** The front desk: Nexus's brief and a box to ask anything, this month's spending,
 * the portfolio, what needs you, what's running, budgets and the next trip. */
export function Home({
  me,
  onAsk,
  onLog,
}: {
  me: Me;
  onAsk: (text: string) => void;
  onLog: () => void;
}) {
  const client = useQueryClient();
  const feed = useQuery({
    queryKey: ["home"],
    queryFn: () => api<FeedItem[]>("/home"),
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
    // While something is running, keep its progress fresh.
    refetchInterval: (query) =>
      query.state.data?.some((r) => RUNNING.has(r.status)) ? 5000 : false,
  });
  const summary = useQuery({
    queryKey: ["summary"],
    queryFn: () => api<Summary>("/summary"),
  }).data;
  const spending = useQuery({
    queryKey: ["spending-months"],
    queryFn: () => api<Spending>("/spending/months"),
  }).data;
  const budgets = useQuery({
    queryKey: ["budgets"],
    queryFn: () => api<Budget[]>("/budgets"),
  }).data;
  const portfolio = useQuery({
    queryKey: ["investments"],
    queryFn: () => api<Portfolio>("/investments"),
  }).data;
  const trip = useQuery({
    queryKey: ["next-trip"],
    queryFn: () => api<TripDetail | null>("/travel/next"),
  }).data;

  const overall = budgets?.find((b) => b.category_id === null);
  const spent = summary?.totals.find((t) => t.direction === "out")?.total;
  const parts = brief({
    spent,
    overall,
    lastMonthToDate: spending?.last_month_to_date,
    trip,
    needs: feed.data,
  });
  const held = [...(portfolio?.holdings ?? [])]
    .sort(
      (a, b) =>
        Number(b.value_home?.amount ?? 0) - Number(a.value_home?.amount ?? 0),
    )
    .map((h) => h.symbol);

  async function cancel(run: Run) {
    await api(`/runs/${run.id}/cancel`, { method: "POST" }).catch(
      () => undefined,
    );
    void client.invalidateQueries({ queryKey: ["runs"] });
  }

  const shown = (runs.data ?? []).slice(0, 5);
  return (
    <>
      <div className="page-head">
        <div>
          <p className="muted">{today(me.user.timezone)}</p>
          <h1>
            <AccentTitle text={greeting(me.user.timezone)} />
          </h1>
        </div>
        <div className="quick">
          <button type="button" className="btn btn-primary" onClick={onLog}>
            Log expense
          </button>
        </div>
      </div>

      <Assistant
        parts={parts}
        chips={suggestions({ trip, holdings: held })}
        onAsk={onAsk}
      />

      <div className="pair">
        <SpendingCard spending={spending} summary={summary} overall={overall} />
        <PortfolioCard portfolio={portfolio} />
      </div>

      <div className="pair">
        <div className="stack">
          <NeedsYou feed={feed} />
          {shown.length > 0 && (
            <section className="card" aria-labelledby="working-on">
              <div className="card-head">
                <h2 id="working-on">Working on</h2>
              </div>
              <ul className="feed">
                {shown.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    onCancel={(r) => void cancel(r)}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>
        <div className="stack">
          <BudgetsCard budgets={budgets} />
          {trip && trip.trip.status !== "finished" ? (
            <TripCard detail={trip} onAsk={onAsk} />
          ) : (
            <section className="card" aria-labelledby="trip-home">
              <div className="card-head">
                <h2 id="trip-home">Next trip</h2>
              </div>
              <p className="muted">
                No trip coming up. <Link to="/travel">Plan one</Link>, or ask
                Nexus to research a destination.
              </p>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
