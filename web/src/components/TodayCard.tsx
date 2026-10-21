import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError, type Mover, type Session, type Today, type Why } from "../api";
import { formatChange, formatPercent } from "../format";
import { livePolling } from "../prices";
import { Icon } from "./Icon";
import { PriceWhen } from "./PriceWhen";

const TITLES: Record<Session, string> = {
  live: "Today",
  closed_today: "Today's session",
  previous: "Last session",
};

/** What the "Why did it move?" button says when it fails: a minute's wait for the rate limit, the
 * server's own short reason when the stock isn't one the user follows or the feature isn't set up,
 * else a plain line. */
export function whyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Try again in a minute";
    if ((error.status === 404 || error.status === 422) && error.message) return error.message;
  }
  return "Couldn't read that move just now";
}

function direction(percent: string | null): string {
  const value = Number(percent);
  return value > 0 ? "up" : value < 0 ? "down" : "";
}

function MoverRow({ mover }: { mover: Mover }) {
  const [state, setState] = useState<
    { status: "idle" } | { status: "asking" } | { status: "answered"; text: string } | { status: "failed"; message: string }
  >({ status: "idle" });

  async function ask() {
    setState({ status: "asking" });
    try {
      const why = await api<Why>(`/investments/today/${encodeURIComponent(mover.symbol)}/why`, { method: "POST" });
      setState({ status: "answered", text: why.text });
    } catch (e) {
      setState({ status: "failed", message: whyError(e) });
    }
  }

  return (
    <li className="mover">
      <div className="mover-top">
        <Link className="mover-symbol" to={`/investment/stocks/${mover.symbol}`}>
          {mover.symbol}
        </Link>
        <span className={`mover-percent ${direction(mover.day_percent)}`}>{formatPercent(mover.day_percent)}</span>
        <span className="mover-price caption">USD {mover.price}</span>
      </div>
      {mover.headline && (
        <p className="mover-headline">
          {mover.headline.url ? (
            <a href={mover.headline.url} target="_blank" rel="noopener noreferrer nofollow">
              {mover.headline.headline}
            </a>
          ) : (
            mover.headline.headline
          )}
        </p>
      )}
      {state.status === "answered" ? (
        <div className="mover-why" role="status">
          <p>{state.text}</p>
          <span className="caption">From today's headlines</span>
        </div>
      ) : (
        <div className="mover-ask">
          <button
            type="button"
            className="btn btn-ghost btn-small"
            disabled={state.status === "asking"}
            onClick={() => void ask()}
          >
            {state.status === "asking" ? (
              "Reading the headlines…"
            ) : (
              <>
                <Icon name="sparkle" size={16} className="icon-inline" />
                Why did it move?<span className="sr-only"> {mover.symbol}</span>
              </>
            )}
          </button>
          {state.status === "failed" && (
            <span className="caption error-text" role="alert">
              {state.message}
            </span>
          )}
        </div>
      )}
    </li>
  );
}

/** How the portfolio did in the latest US session and its biggest movers, with a headline for
 * each and a button that reads the day's headlines for why: a card on the Portfolio page. Shown
 * only when there is something to say. */
export function TodayCard() {
  const today = useQuery({
    queryKey: ["investments", "today"],
    queryFn: () => api<Today>("/investments/today"),
    // Every minute while the session is live and the page is in view.
    refetchInterval: (query) => livePolling(query.state.data?.session === "live" ? "live" : null),
  }).data;

  if (!today || (today.movers.length === 0 && !today.change)) return null;

  const title = TITLES[today.session];
  const when = <PriceWhen kind={today.price_kind} at={today.as_of_at} day={today.day} />;
  const body: ReactNode = (
    <>
      {today.change && (
        <p className={`today-change ${direction(today.change.amount)}`}>
          <span className="figure-value">{formatChange(today.change)}</span>{" "}
          {today.percent !== null && <span className="today-percent">{formatPercent(today.percent)}</span>}
        </p>
      )}
      {today.movers.length > 0 && (
        <ul className="movers" aria-label="Biggest movers">
          {today.movers.map((m) => (
            <MoverRow key={m.symbol} mover={m} />
          ))}
        </ul>
      )}
    </>
  );

  return (
    <section className="card" aria-labelledby="today">
      <div className="card-head">
        <h2 id="today">{title}</h2>
        {when}
      </div>
      {body}
    </section>
  );
}
