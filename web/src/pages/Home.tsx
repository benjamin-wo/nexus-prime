import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type Budget,
  type BudgetMonth,
  type FeedAction,
  type FeedItem,
  type Holding,
  type Me,
  type Money,
  type Portfolio,
  type Run,
  type Spending,
  type Summary,
  type TripDetail,
} from "../api";
import { brief, standing, suggestions } from "../brief";
import { Block } from "../components/Block";
import { Icon, departmentIcon } from "../components/Icon";
import { DEPARTMENTS } from "../departments";
import {
  formatChange,
  formatMoney,
  formatPercent,
  formatShortDate,
} from "../format";
import { livePolling } from "../prices";
import { PriceWhen } from "../components/PriceWhen";
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

/** The top of Home, on an indigo gradient rather than in a card: the day and a
 * greeting, this month's spending as the one big figure with how it stands, Nexus's
 * brief, a few one-tap questions, and a box to ask anything (each opens the chat). */
function Hero({
  date,
  greeting: hello,
  spent,
  stands,
  parts,
  chips,
  onAsk,
  onLog,
}: {
  date: string;
  greeting: string;
  spent?: Money;
  stands: ReturnType<typeof standing>;
  parts: ReturnType<typeof brief>;
  chips: string[];
  onAsk: (text: string) => void;
  onLog: () => void;
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
    <section className="hero" aria-label="Nexus">
      <div className="hero-top">
        <div>
          <p className="hero-date">{date}</p>
          <h1>
            <AccentTitle text={hello} />
          </h1>
        </div>
        <div className="hero-actions">
          <button type="button" className="round-btn" aria-label="Log expense" title="Log expense" onClick={onLog}>
            <Icon name="plus" />
          </button>
          <Link className="round-btn" to="/settings" aria-label="Settings" title="Settings">
            <Icon name="settings" />
          </Link>
        </div>
      </div>
      <div className="hero-figure">
        <span className="hero-value">
          <CountUp value={spent ? formatMoney(spent) : "…"} />
          {stands && (
            <span className="hero-arrow" aria-hidden="true">
              <Icon name={stands.good ? "down" : "up"} size={28} />
            </span>
          )}
        </span>
        <span className="hero-label">spent this month</span>
      </div>
      {stands && <p className="hero-note">{stands.text}.</p>}
      <p className="hero-brief">
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
          <button key={c} type="button" className="ask-chip" onClick={() => onAsk(c)}>
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

/** A usual month: the average of the full months before this one that had any
 * spending, and how many there were. */
function usualMonth(months: Spending["months"]): { usual: number | null; count: number } {
  const past = months.filter((m) => !m.to_date && Number(m.spent.amount) > 0);
  const usual = past.length ? past.reduce((sum, m) => sum + Number(m.spent.amount), 0) / past.length : null;
  return { usual, count: past.length };
}

/** Money out per month: quiet bars for past months (striped rose only when over
 * the overall budget), this month so far in solid indigo over the outline of a
 * usual month (so early in the month a short bar reads as "so far"), and the
 * budget as a dashed line. */
function SpendingChart({ data }: { data: Spending }) {
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
  // A usual month (the brief already says how this month compares with the last).
  const { usual, count } = usualMonth(spending?.months ?? []);
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
    <Block
      id="spending-months"
      title="Spending"
      className="spend-card"
      action={
        <Link className="btn btn-small" to="/accounting">
          Details
        </Link>
      }
    >
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
          <span className="caption">A usual month</span>
          <span className="mini-value">
            {!now
              ? "…"
              : usual === null
                ? "Not yet"
                : formatMoney({ amount: usual.toFixed(2), currency: now.spent.currency })}
          </span>
          <span className="caption">
            {usual === null
              ? "Needs a full month"
              : `Average of the last ${count === 1 ? "month" : `${count} months`}`}
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
    </Block>
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
    <Block
      id="portfolio"
      title="Portfolio"
      action={
        <Link className="btn btn-small" to="/investment">
          Open
        </Link>
      }
    >
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
          {totals && (totals.as_of || totals.as_of_at) && (
            <PriceWhen kind={totals.price_kind} at={totals.as_of_at} day={totals.as_of} />
          )}
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
    </Block>
  );
}

/** One thing that needs you: a link to where it's settled, and any buttons that settle it
 * right here. Each button calls the API as given, then everything it may have changed
 * is fetched again. */
function NeedsItem({ item, onSettled }: { item: FeedItem; onSettled: () => void }) {
  const dept = DEPARTMENTS.find((d) => d.name === item.department);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: FeedAction) {
    setBusy(true);
    setError(null);
    try {
      await api(action.path, { method: action.method });
      onSettled();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't do that");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li>
      <Link className={`row row-link${item.urgent ? " urgent" : ""}`} to={item.link}>
        <span className="row-icon" aria-hidden="true">
          <Icon name={item.urgent ? "alert" : departmentIcon(item.department)} size={18} />
        </span>
        <span className="row-main">
          <span className="wrap">{item.text}</span>
          <span className="caption">{dept?.label}</span>
        </span>
      </Link>
      {item.actions.length > 0 && (
        <div className="row-actions needs-actions">
          {item.actions.map((a, i) => (
            <button
              key={a.key}
              type="button"
              className={i === 0 ? "btn btn-small btn-primary" : "btn btn-small"}
              disabled={busy}
              onClick={() => void run(a)}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
      {error && (
        <p className="error-text needs-error" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

function NeedsYou({
  feed,
  onSettled,
}: {
  feed: { data?: FeedItem[]; isLoading: boolean; isError: boolean };
  onSettled: () => void;
}) {
  return (
    <Block id="needs-you" title="Needs you">
      {feed.isLoading && <p className="state">Loading…</p>}
      {feed.isError && (
        <p className="error-text">Couldn't load what needs you.</p>
      )}
      {feed.data?.length === 0 && (
        <p className="state">Nothing needs you right now.</p>
      )}
      {feed.data && feed.data.length > 0 && (
        <ul className="rows">
          {feed.data.map((item) => (
            <NeedsItem key={`${item.kind}:${item.text}`} item={item} onSettled={onSettled} />
          ))}
        </ul>
      )}
    </Block>
  );
}

function BudgetsCard({ budgets }: { budgets?: Budget[] }) {
  const shown = [...(budgets ?? [])]
    .sort((a, b) => b.percent - a.percent)
    .slice(0, 4);
  return (
    <Block
      id="budgets-home"
      title="Budgets this month"
      action={
        <Link className="btn btn-small" to="/accounting/plan">
          Edit
        </Link>
      }
    >
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
    </Block>
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
    <Block id="trip-home" title={t.destination} action={<span className="pill">{tripWhen(t)}</span>}>
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
      ) : detail.trip.budget && detail.spending ? (
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
    </Block>
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
  const plan = useQuery({
    queryKey: ["budgets", "month"],
    queryFn: () => api<BudgetMonth>("/budgets/month"),
  }).data;
  const portfolio = useQuery({
    queryKey: ["investments"],
    queryFn: () => api<Portfolio>("/investments"),
    // Every minute while the portfolio's prices are live and the page is in view.
    refetchInterval: (query) => livePolling(query.state.data?.totals.price_kind),
  }).data;
  const trip = useQuery({
    queryKey: ["next-trip"],
    queryFn: () => api<TripDetail | null>("/travel/next"),
  }).data;

  const overall = budgets?.find((b) => b.category_id === null);
  const spent = summary?.totals.find((t) => t.direction === "out")?.total;
  // The big figure and how it stands lead the hero; the brief adds the rest.
  const parts = brief({ trip, needs: feed.data, overall, plan });
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

  // A button on a needs-you item may have logged or skipped something: refresh what shows it.
  function settled() {
    for (const key of ["home", "transactions", "bills", "budgets", "summary", "spending-months"])
      void client.invalidateQueries({ queryKey: [key] });
  }

  const shown = (runs.data ?? []).slice(0, 5);
  return (
    <>
      <Hero
        date={today(me.user.timezone)}
        greeting={greeting(me.user.timezone)}
        spent={spent}
        stands={standing({ spent, overall, lastMonthToDate: spending?.last_month_to_date })}
        parts={parts}
        chips={suggestions({ trip, holdings: held })}
        onAsk={onAsk}
        onLog={onLog}
      />

      <div className="pair">
        <SpendingCard spending={spending} summary={summary} overall={overall} />
        <PortfolioCard portfolio={portfolio} />
      </div>

      <div className="pair">
        <div className="stack">
          <NeedsYou feed={feed} onSettled={settled} />
          {shown.length > 0 && (
            <Block id="working-on" title="Working on">
              <ul className="feed">
                {shown.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    onCancel={(r) => void cancel(r)}
                  />
                ))}
              </ul>
            </Block>
          )}
        </div>
        <div className="stack">
          <BudgetsCard budgets={budgets} />
          {trip && trip.trip.status !== "finished" ? (
            <TripCard detail={trip} onAsk={onAsk} />
          ) : (
            <Block id="trip-home" title="Next trip">
              <p className="muted">
                No trip coming up. <Link to="/travel">Plan one</Link>, or ask
                Nexus to research a destination.
              </p>
            </Block>
          )}
        </div>
      </div>
    </>
  );
}
