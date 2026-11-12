import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type Budget,
  type BudgetMonth,
  type FeedAction,
  type FeedItem,
  type Me,
  type Money,
  type Portfolio,
  type Run,
  type Spending,
  type Summary,
  type Today,
  type TripDetail,
} from "../api";
import { brief, notableMove, pace, standing, suggestions } from "../brief";
import { Block } from "../components/Block";
import { GetStarted } from "../components/GetStarted";
import { Icon, departmentIcon } from "../components/Icon";
import { Toast } from "../components/Toast";
import { DEPARTMENTS } from "../departments";
import { formatMoney } from "../format";
import { livePolling } from "../prices";
import { AccentTitle, CountUp } from "../motion";
import { MoneyGlance, PortfolioGlance, TripGlance, TripMode } from "./HomeCards";

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
 * greeting, this month's spending as the one big figure with how it stands, and Nexus's
 * brief. What needs the person follows directly under it. */
function Hero({
  date,
  greeting: hello,
  spent,
  stands,
  parts,
  onLog,
}: {
  date: string;
  greeting: string;
  spent?: Money;
  stands: ReturnType<typeof standing>;
  parts: ReturnType<typeof brief>;
  onLog: () => void;
}) {
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
          {/* A quick manual entry for when there's no time to chat. */}
          <button type="button" className="round-btn" aria-label="Log expense" title="Log expense" onClick={onLog}>
            <Icon name="plus" />
          </button>
          <Link className="round-btn" to="/settings/notifications" aria-label="Notifications" title="Notifications">
            <Icon name="bell" />
          </Link>
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
    </section>
  );
}

/** The width at which the shell swaps its rail for the bottom bar (the same query as in styles.css). */
const PHONE = "(max-width: 900px)";

function usePhone(): boolean {
  return useSyncExternalStore(
    (changed) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const query = window.matchMedia(PHONE);
      query.addEventListener("change", changed);
      return () => query.removeEventListener("change", changed);
    },
    () => typeof window.matchMedia === "function" && window.matchMedia(PHONE).matches,
    () => false,
  );
}

/** The box to ask anything or log an expense in words; submitting opens the chat with it. It sits
 * in the Just ask Nexus card on a wide screen and docked above the bottom bar on a phone. */
function AskForm({ onAsk }: { onAsk: (text: string) => void }) {
  const [draft, setDraft] = useState("");
  function ask(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onAsk(text);
  }
  return (
    <form className="ask" onSubmit={ask}>
      <label className="sr-only" htmlFor="ask-input">
        Ask Nexus
      </label>
      <input
        id="ask-input"
        className="ask-input"
        value={draft}
        maxLength={2000}
        onChange={(e) => setDraft(e.target.value)}
        placeholder='Just ask Nexus… e.g. "kopi 4.20"'
      />
      <button type="submit" className="ask-send" aria-label="Ask" disabled={!draft.trim()}>
        <Icon name="send" size={18} />
      </button>
    </form>
  );
}

/** One-tap questions, and on a wide screen the box to ask anything above them; each opens the
 * chat. On a phone the box is docked at the bottom of the page instead (see Home), so the card
 * holds only the questions. */
function AskPanel({ chips, onAsk, form }: { chips: string[]; onAsk: (text: string) => void; form: ReactNode }) {
  return (
    <Block id="ask" title="Just ask Nexus" className="ask-panel">
      {form}
      <div className="chips" aria-label="Suggested questions">
        {chips.map((c) => (
          <button key={c} type="button" className="ask-chip" onClick={() => onAsk(c)}>
            {c}
          </button>
        ))}
      </div>
    </Block>
  );
}

/** What an action's response says in words (marking a bill paid says what was logged), if anything. */
function messageOf(response: unknown): string | undefined {
  if (typeof response !== "object" || response === null) return undefined;
  const { message } = response as { message?: unknown };
  return typeof message === "string" && message !== "" ? message : undefined;
}

/** One thing that needs you: a link to where it's settled, and any buttons that settle it
 * right here. Each button calls the API as given (with its body, if it has one), then
 * everything it may have changed is fetched again, and what the API said is passed on to be
 * shown. An item that needs you now says so; one about today says Today. */
function NeedsItem({ item, onSettled }: { item: FeedItem; onSettled: (message?: string) => void }) {
  const dept = DEPARTMENTS.find((d) => d.name === item.department);
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

  return (
    <li>
      <Link className={`row row-link${item.when === "now" ? " urgent" : ""}`} to={item.link}>
        <span className="row-icon" aria-hidden="true">
          <Icon name={item.when === "now" ? "alert" : departmentIcon(item.department)} size={18} />
        </span>
        <span className="row-main">
          <span className="wrap">{item.text}</span>
          <span className="caption">
            {dept?.label}
            {item.when === "today" && " · Today"}
          </span>
        </span>
        {item.when === "now" && <span className="badge badge-now">Now</span>}
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

/** How many items Needs you shows before "Show all". */
export const NEEDS_SHOWN = 5;

function NeedsYou({
  feed,
  onSettled,
}: {
  feed: { data?: FeedItem[]; isLoading: boolean; isError: boolean };
  onSettled: (message?: string) => void;
}) {
  const [all, setAll] = useState(false);
  const items = feed.data ?? [];
  const shown = all ? items : items.slice(0, NEEDS_SHOWN);
  return (
    <Block id="needs-you" title="Needs you">
      {feed.isLoading && <p className="state">Loading…</p>}
      {feed.isError && (
        <p className="error-text">Couldn't load what needs you.</p>
      )}
      {feed.data?.length === 0 && (
        <p className="state">Nothing needs you right now.</p>
      )}
      {shown.length > 0 && (
        <ul className="rows">
          {shown.map((item) => (
            <NeedsItem key={`${item.kind}:${item.text}`} item={item} onSettled={onSettled} />
          ))}
        </ul>
      )}
      {items.length > NEEDS_SHOWN && (
        <button
          type="button"
          className="btn btn-ghost btn-small needs-more"
          aria-expanded={all}
          onClick={() => setAll(!all)}
        >
          {all ? "Show fewer" : `Show all (${items.length})`}
        </button>
      )}
    </Block>
  );
}

/** The front desk, as a Today page: Nexus's brief, what needs you, a box to ask anything, the
 * first-steps guide while it's unfinished, and at a glance the month's money, the portfolio and
 * the next trip. While a trip is on, its day leads. */
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
  // The latest session's movers, for the brief's one line about the market.
  const session = useQuery({
    queryKey: ["investments", "today"],
    queryFn: () => api<Today>("/investments/today"),
    refetchInterval: (query) => livePolling(query.state.data?.session === "live" ? "live" : null),
  }).data;
  const trip = useQuery({
    queryKey: ["next-trip"],
    queryFn: () => api<TripDetail | null>("/travel/next"),
  });

  const overall = budgets?.find((b) => b.category_id === null);
  const spent = summary?.totals.find((t) => t.direction === "out")?.total;
  // The big figure and how it stands lead the hero; the brief adds the rest.
  const parts = brief({ trip: trip.data, needs: feed.data, overall, plan, move: notableMove(session) });
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

  // A button on a needs-you item may have logged, skipped or merged something: refresh what
  // shows it, here and on the other pages ("transactions" also holds the ledger's possible
  // duplicates; "email" is the Email page). What the API said (what a bill's payment logged) is
  // shown for a moment, as the item it was about is gone.
  const [notice, setNotice] = useState<string | null>(null);
  function settled(message?: string) {
    for (const key of ["home", "transactions", "email", "bills", "budgets", "summary", "spending-months"])
      void client.invalidateQueries({ queryKey: [key] });
    setNotice(message ?? null);
  }

  const going = (runs.data ?? []).slice(0, 3);
  const detail = trip.data;
  const tripOn = detail && detail.trip.status === "ongoing" ? detail : null;
  // On a phone the ask box is docked above the bottom bar, sticky at the end of the page (a
  // sticky box only travels inside its parent, so the page sits in one flex column then).
  const docked = usePhone();
  return (
    <div className={docked ? "home home-docked" : "home"}>
      <Hero
        date={today(me.user.timezone)}
        greeting={greeting(me.user.timezone)}
        spent={spent}
        stands={standing({ spent, overall, lastMonthToDate: spending?.last_month_to_date })}
        parts={parts}
        onLog={onLog}
      />

      {tripOn && <TripMode detail={tripOn} timezone={me.user.timezone} />}

      <div className="today">
        <div className="stack">
          <GetStarted me={me} />
          <NeedsYou feed={feed} onSettled={settled} />
          {going.length > 0 && (
            <Block id="working-on" title="Working on" className="working">
              <ul className="feed">
                {going.map((run) => (
                  <RunRow key={run.id} run={run} onCancel={(r) => void cancel(r)} />
                ))}
              </ul>
            </Block>
          )}
          <AskPanel
            chips={suggestions({ trip: detail, holdings: held })}
            onAsk={onAsk}
            form={docked ? null : <AskForm onAsk={onAsk} />}
          />
        </div>
        <div className="stack">
          <MoneyGlance
            spent={spent}
            overall={overall}
            pace={pace({ overall, lastMonthToDate: spending?.last_month_to_date, timezone: me.user.timezone })}
          />
          <PortfolioGlance portfolio={portfolio} />
          {!tripOn && <TripGlance detail={trip.isLoading ? undefined : (detail ?? null)} />}
        </div>
      </div>
      {docked && (
        <div className="ask-dock">
          <AskForm onAsk={onAsk} />
        </div>
      )}
      {notice && <Toast message={notice} onClose={() => setNotice(null)} />}
    </div>
  );
}
