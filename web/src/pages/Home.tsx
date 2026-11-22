import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  api,
  type Budget,
  type BudgetMonth,
  type FeedAction,
  type FeedItem,
  type Me,
  type NotificationEntry,
  type Portfolio,
  type Run,
  type Spending,
  type Summary,
  type Today,
  type TripDetail,
} from "../api";
import { dateLabel, forToday, headline, notableMove, pace, type TodayRow } from "../brief";
import { GetStarted } from "../components/GetStarted";
import { Icon } from "../components/Icon";
import { LoadError } from "../components/LoadError";
import { Toast } from "../components/Toast";
import { Button, ButtonLink, Row, RowList, Section } from "../components/ui";
import { formatAmount } from "../format";
import { livePolling } from "../prices";
import { CountUp } from "../motion";
import { clock, dayLines, MoneyGlance, nextToday, PortfolioGlance, TripGlance, tripDay, TripMode } from "./HomeCards";

import "./home.css";

const RUNNING = new Set<Run["status"]>(["queued", "running"]);

/** One piece of research: its title, how far it has got, a thin bar and, while it runs, Cancel. */
function RunItem({ run, onCancel }: { run: Run; onCancel: (run: Run) => void }) {
  const going = RUNNING.has(run.status);
  const share = run.steps_total ? Math.round((run.steps_done / run.steps_total) * 100) : 0;
  return (
    <li className="row-item run-item">
      <span className="row-text">
        <span className="row-title">{run.title}</span>
        <span className="row-sub">
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
            className="run-bar"
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
        <Button variant="text" size="sm" onClick={() => onCancel(run)}>
          Cancel
        </Button>
      )}
    </li>
  );
}

/** The top of Home, on the ground with no panel: the date with the ways to Log and to Settings (and the bell, when
 * there is something to read), the month's key figure, and one sentence that says what it is. */
function Headline({
  date,
  hl,
  query,
  bell,
  onLog,
}: {
  date: string;
  hl: ReturnType<typeof headline>;
  /** The query behind the figure: when it failed, the figure says so, with a Retry. */
  query: { isError: boolean; isFetching: boolean; refetch: () => unknown };
  bell: boolean;
  onLog: () => void;
}) {
  return (
    <section className="home-head" aria-label="This month">
      <h1 className="sr-only">Today</h1>
      <div className="home-label">
        <p className="home-date">{date}</p>
        <div className="home-label-actions">
          {/* A quick manual entry for when there's no time to chat. */}
          <Button variant="text" aria-label="Log expense" onClick={onLog}>
            Log
          </Button>
          <ButtonLink variant="text" to="/settings">
            Settings
          </ButtonLink>
          {bell && (
            <ButtonLink variant="text" to="/settings/notifications" aria-label="Notifications" title="Notifications">
              <Icon name="bell" />
            </ButtonLink>
          )}
        </div>
      </div>
      <p className={`home-figure${hl?.over ? " is-over" : ""}`}>
        {hl && <span className="sr-only">{hl.figure.currency} </span>}
        <CountUp value={hl ? formatAmount(hl.figure) : query.isError ? "–" : "…"} />
      </p>
      {query.isError && !hl ? (
        <LoadError message="Couldn't load this month's spending." query={query} />
      ) : (
        hl && (
          <p className="home-sentence">
            {hl.sentence.map((p, i) =>
              p.hl ? (
                <span key={i} className="home-num">
                  {p.text}
                </span>
              ) : (
                <span key={i}>{p.text}</span>
              ),
            )}
          </p>
        )
      )}
    </section>
  );
}

/** What an action's response says in words (marking a bill paid says what was logged), if anything. */
function messageOf(response: unknown): string | undefined {
  if (typeof response !== "object" || response === null) return undefined;
  const { message } = response as { message?: unknown };
  return typeof message === "string" && message !== "" ? message : undefined;
}

/** One row of For today. It links to where the thing is settled. A row that needs a decision has its first action
 * as the word at the right, a text button that settles it here, and any other action as a quieter text button
 * beside it. Each button calls the API as given (with its body, if it has one), then everything it may have
 * changed is fetched again, and what the API said is passed on to be shown. */
function TodayItem({ row, onSettled }: { row: TodayRow; onSettled: (message?: string) => void }) {
  const actions = row.item?.actions ?? [];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: FeedAction) {
    setBusy(true);
    setError(null);
    try {
      const done = await api<unknown>(action.path, {
        method: action.method,
        body: action.body ?? undefined,
      });
      onSettled(messageOf(done));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't do that");
    } finally {
      setBusy(false);
    }
  }

  if (actions.length === 0)
    return (
      <Row
        className="today-row"
        to={row.link}
        title={row.title}
        sub={row.sub}
        trailing={<span className={`today-word is-${row.when}`}>{row.word}</span>}
      />
    );
  return (
    <Row
      className={`today-row${actions.length > 1 ? " today-multi" : ""}`}
      to={row.link}
      title={row.title}
      sub={row.sub}
      actions={
        <>
          {actions.map((a, i) => (
            <Button
              key={a.key}
              variant="text"
              className={i === 0 ? `today-word is-${row.when}` : "today-quiet"}
              disabled={busy}
              onClick={() => void run(a)}
            >
              {a.label}
            </Button>
          ))}
          {error && (
            <p className="error-text today-error" role="alert">
              {error}
            </p>
          )}
        </>
      }
    />
  );
}

/** How many rows For today shows before "See all". */
export const TODAY_SHOWN = 5;

function ForToday({
  rows,
  feed,
  onSettled,
}: {
  rows: TodayRow[];
  feed: { data?: FeedItem[]; isLoading: boolean; isError: boolean; isFetching: boolean; refetch: () => unknown };
  onSettled: (message?: string) => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, TODAY_SHOWN);
  return (
    <Section
      id="for-today"
      title="For today"
      action={
        rows.length > TODAY_SHOWN ? (
          <Button variant="text" size="sm" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `See all ${rows.length}`}
          </Button>
        ) : undefined
      }
    >
      {shown.length > 0 && (
        <RowList>
          {shown.map((row) => (
            <TodayItem key={row.key} row={row} onSettled={onSettled} />
          ))}
        </RowList>
      )}
      {feed.isLoading && <p className="state">Loading…</p>}
      {feed.isError && <LoadError message="Couldn't load what's for today." query={feed} />}
      {feed.data && rows.length === 0 && <p className="state">Nothing for today.</p>}
    </Section>
  );
}

/** The front desk, as a Today page: the month's headline, what is for today, the first-steps guide while it's
 * unfinished, and at a glance the month's money, the portfolio and the next trip. While a trip is on, its day leads. */
export function Home({ me, onLog }: { me: Me; onLog: () => void }) {
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
  const summaryQuery = useQuery({
    queryKey: ["summary"],
    queryFn: () => api<Summary>("/summary"),
  });
  const summary = summaryQuery.data;
  const spendingQuery = useQuery({
    queryKey: ["spending-months"],
    queryFn: () => api<Spending>("/spending/months"),
  });
  const spending = spendingQuery.data;
  const budgetsQuery = useQuery({
    queryKey: ["budgets"],
    queryFn: () => api<Budget[]>("/budgets"),
  });
  const budgets = budgetsQuery.data;
  const plan = useQuery({
    queryKey: ["budgets", "month"],
    queryFn: () => api<BudgetMonth>("/budgets/month"),
  }).data;
  const portfolioQuery = useQuery({
    queryKey: ["investments"],
    queryFn: () => api<Portfolio>("/investments"),
    // Every minute while the portfolio's prices are live and the page is in view.
    refetchInterval: (query) => livePolling(query.state.data?.totals.price_kind),
  });
  const portfolio = portfolioQuery.data;
  // The latest session's movers, for For today's one row about the market.
  const session = useQuery({
    queryKey: ["investments", "today"],
    queryFn: () => api<Today>("/investments/today"),
    refetchInterval: (query) => livePolling(query.state.data?.session === "live" ? "live" : null),
  }).data;
  const trip = useQuery({
    queryKey: ["next-trip"],
    queryFn: () => api<TripDetail | null>("/travel/next"),
  });
  // The bell is there only when Nexus has sent something to read (the last 30 days).
  const history = useQuery({
    queryKey: ["notification-history"],
    queryFn: () => api<NotificationEntry[]>("/notifications/history"),
  }).data;

  const overall = budgets?.find((b) => b.category_id === null);
  const spent = summary?.totals.find((t) => t.direction === "out")?.total;
  const timezone = me.user.timezone;
  const detail = trip.data;
  const tripOn = detail && detail.trip.status === "ongoing" ? detail : null;
  const tripNext = tripOn ? nextToday(dayLines(tripOn, tripDay(tripOn.trip)), clock(timezone)) : null;
  const rows = forToday({ trip: detail, tripNext, needs: feed.data, overall, plan, move: notableMove(session) });

  async function cancel(run: Run) {
    await api(`/runs/${run.id}/cancel`, { method: "POST" }).catch(
      () => undefined,
    );
    void client.invalidateQueries({ queryKey: ["runs"] });
  }

  // A button on a For today row may have logged, skipped or merged something: refresh what
  // shows it, here and on the other pages ("transactions" also holds the ledger's possible
  // duplicates; "email" is the Email page). What the API said (what a bill's payment logged) is
  // shown for a moment, as the row it was about is gone.
  const [notice, setNotice] = useState<string | null>(null);
  function settled(message?: string) {
    for (const key of ["home", "transactions", "email", "bills", "budgets", "summary", "spending-months"])
      void client.invalidateQueries({ queryKey: [key] });
    setNotice(message ?? null);
  }

  const going = (runs.data ?? []).slice(0, 3);
  // The order on a phone is the order here; from 1024px home.css puts them in two columns.
  return (
    <div className="home">
      <Headline
        date={dateLabel(timezone)}
        hl={headline({ spent, overall, lastMonthToDate: spending?.last_month_to_date, timezone })}
        query={summaryQuery}
        bell={(history?.length ?? 0) > 0}
        onLog={onLog}
      />
      {tripOn && <TripMode detail={tripOn} timezone={timezone} />}
      <ForToday rows={rows} feed={feed} onSettled={settled} />
      {going.length > 0 && (
        <Section id="working-on" title="Working on">
          <RowList>
            {going.map((run) => (
              <RunItem key={run.id} run={run} onCancel={(r) => void cancel(r)} />
            ))}
          </RowList>
        </Section>
      )}
      <GetStarted me={me} onLog={onLog} />
      <div className="home-glance">
        <MoneyGlance
          spent={spent}
          query={summaryQuery}
          // Without the budget or last month's figure there is nothing to compare with: not "set a budget".
          partial={budgetsQuery.isError || spendingQuery.isError}
          overall={overall}
          pace={pace({ overall, lastMonthToDate: spending?.last_month_to_date, timezone })}
        />
        <PortfolioGlance portfolio={portfolio} query={portfolioQuery} />
        {!tripOn && <TripGlance detail={trip.isLoading ? undefined : (detail ?? null)} query={trip} />}
      </div>
      {notice && <Toast message={notice} onClose={() => setNotice(null)} />}
    </div>
  );
}
