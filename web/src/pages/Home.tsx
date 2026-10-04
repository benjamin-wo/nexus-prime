import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, type FeedItem, type Me, type Run, type Summary } from "../api";
import { DEPARTMENTS } from "../departments";
import { formatMoney } from "../format";

function greeting(timezone: string): string {
  const hour = Number(new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: timezone }).format(new Date()));
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

const RUNNING = new Set<Run["status"]>(["queued", "running"]);

function RunRow({ run, onCancel }: { run: Run; onCancel: (run: Run) => void }) {
  const going = RUNNING.has(run.status);
  const share = run.steps_total ? Math.round((run.steps_done / run.steps_total) * 100) : 0;
  return (
    <li className="run-row">
      <span className="wrap">
        {run.title}
        <br />
        <span className="caption">
          {going ? `${run.steps_done}/${run.steps_total} · ${run.progress}` : run.status === "failed" ? `Couldn't finish: ${run.error ?? "something went wrong"}` : run.status === "done" ? "Done" : "Cancelled"}
        </span>
        {going && (
          <span className="progress" role="progressbar" aria-label={`${run.title} progress`} aria-valuenow={share} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${share}%` }} />
          </span>
        )}
      </span>
      {going && (
        <button type="button" className="btn btn-small" onClick={() => onCancel(run)}>
          Cancel
        </button>
      )}
    </li>
  );
}

/** The front desk: ask anything, see what each department needs from you, what's
 * being worked on, and a card per department. */
export function Home({ me, onAsk }: { me: Me; onAsk: (text: string) => void }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState("");
  const feed = useQuery({ queryKey: ["home"], queryFn: () => api<FeedItem[]>("/home") });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
    // While something is running, keep its progress fresh.
    refetchInterval: (query) => (query.state.data?.some((r) => RUNNING.has(r.status)) ? 5000 : false),
  });
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => api<Summary>("/summary") });
  const spent = summary.data?.totals.find((t) => t.direction === "out");
  const received = summary.data?.totals.find((t) => t.direction === "in");

  function ask(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onAsk(text);
  }

  async function cancel(run: Run) {
    await api(`/runs/${run.id}/cancel`, { method: "POST" }).catch(() => undefined);
    void client.invalidateQueries({ queryKey: ["runs"] });
  }

  const shown = (runs.data ?? []).slice(0, 5);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{greeting(me.user.timezone)}</h1>
          <p className="muted">Ask anything, or pick up where your departments need you.</p>
        </div>
      </div>

      <form className="ask" onSubmit={ask} aria-label="Ask Nexus">
        <label className="sr-only" htmlFor="ask-input">
          Ask Nexus
        </label>
        <input
          id="ask-input"
          className="input"
          value={draft}
          maxLength={2000}
          onChange={(e) => setDraft(e.target.value)}
          placeholder='"kopi 4.20", "how much on Grab this month?", "pay rent on the 1st"'
        />
        <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
          Ask
        </button>
      </form>

      <section className="card" aria-labelledby="needs-you">
        <div className="card-head">
          <h2 id="needs-you">Needs you</h2>
        </div>
        {feed.isLoading && <p className="state">Loading…</p>}
        {feed.isError && <p className="error-text">Couldn't load what needs you.</p>}
        {feed.data?.length === 0 && <p className="state">Nothing needs you right now. 🎉</p>}
        {feed.data && feed.data.length > 0 && (
          <ul className="feed">
            {feed.data.map((item) => {
              const dept = DEPARTMENTS.find((d) => d.name === item.department);
              return (
                <li key={`${item.kind}:${item.text}`}>
                  <Link className={`feed-item${item.urgent ? " urgent" : ""}`} to={item.link}>
                    <span className="wrap">{item.text}</span>
                    <span className="caption">
                      {dept?.icon} {dept?.label}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {shown.length > 0 && (
        <section className="card" aria-labelledby="working-on">
          <div className="card-head">
            <h2 id="working-on">Working on</h2>
          </div>
          <ul className="feed">
            {shown.map((run) => (
              <RunRow key={run.id} run={run} onCancel={(r) => void cancel(r)} />
            ))}
          </ul>
        </section>
      )}

      <div className="dept-cards">
        {DEPARTMENTS.map((d) => (
          <Link key={d.name} className="card dept-card" to={d.path} aria-label={`${d.label}: ${d.blurb}`}>
            <h2>
              <span aria-hidden="true">{d.icon}</span> {d.label}
            </h2>
            {d.name === "accounting" ? (
              <p className="muted">
                This month: {spent ? formatMoney(spent.total) : "…"} spent
                {received ? `, ${formatMoney(received.total)} received` : ""}
              </p>
            ) : (
              <p className="muted">{d.blurb}</p>
            )}
            {d.upcoming && <span className="caption">Coming next</span>}
          </Link>
        ))}
      </div>
    </>
  );
}
