import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type Levels, type PriceRange, type Stock } from "../api";
import { formatShortDate } from "../format";
import { verdictTone } from "./Plans";

const usd = (amount: string) => Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const TREND: Record<string, string> = {
  uptrend: "Above its 50-day average, which is above its 200-day: an uptrend",
  downtrend: "Below its 50-day average, which is below its 200-day: a downtrend",
  mixed: "Between its 50- and 200-day averages: no clear trend",
};

function rsiNote(rsi: number): string {
  if (rsi >= 70) return "stretched after a run up";
  if (rsi <= 30) return "beaten down after a fall";
  return "neither stretched nor beaten down";
}

/** Resistance above, the close, support below: nearest first either side. */
function Ladder({ levels }: { levels: Levels }) {
  const rows = [
    ...[...levels.resistance].reverse().map((v) => ({ label: "Resistance", value: v, kind: "down" })),
    { label: "Close", value: levels.close, kind: "close" },
    ...levels.support.map((v) => ({ label: "Support", value: v, kind: "up" })),
  ];
  return (
    <ul className="ladder" aria-label="Support and resistance">
      {rows.map((r) => (
        <li key={`${r.label}:${r.value}`} className={r.kind}>
          <span>{r.label}</span>
          <span className="num">{usd(r.value)}</span>
        </li>
      ))}
    </ul>
  );
}

function LevelsCard({ levels }: { levels: Levels }) {
  const low = Number(levels.year_low);
  const high = Number(levels.year_high);
  const where = high > low ? Math.round(((Number(levels.close) - low) / (high - low)) * 100) : 50;
  return (
    <section className="card" aria-labelledby="levels">
      <div className="card-head">
        <h2 id="levels">Levels</h2>
        <span className="caption">Close of {formatShortDate(levels.as_of, "UTC")} · worked out from daily prices</span>
      </div>
      <Ladder levels={levels} />
      <p className="caption">Support and resistance are recent swing lows and highs (the last 6 months).</p>
      <dl className="totals" aria-label="Indicators">
        {Object.entries(levels.averages).map(([days, value]) => (
          <div key={days}>
            <dt>{days}-day average</dt>
            <dd className="num">{usd(value)}</dd>
          </div>
        ))}
        {levels.rsi !== null && (
          <div>
            <dt>RSI (14)</dt>
            <dd className="num">{Number(levels.rsi).toFixed(0)}</dd>
          </div>
        )}
        {levels.atr !== null && (
          <div>
            <dt>Typical daily move</dt>
            <dd className="num">
              {usd(levels.atr)} ({levels.atr_percent}%)
            </dd>
          </div>
        )}
      </dl>
      {levels.trend && <p className="muted">{TREND[levels.trend]}.</p>}
      {levels.rsi !== null && <p className="muted">Momentum: {rsiNote(Number(levels.rsi))}.</p>}
      <div className="range" aria-label={`52-week range ${usd(levels.year_low)} to ${usd(levels.year_high)}, close at ${where}%`}>
        <span className="caption">52 weeks: {usd(levels.year_low)}</span>
        <span className="range-bar">
          <span style={{ left: `${Math.min(100, Math.max(0, where))}%` }} />
        </span>
        <span className="caption">{usd(levels.year_high)}</span>
      </div>
    </section>
  );
}

/** Where the close could be after a week, a month and three months, from the stock's
 * own day-to-day swings. Worked out in code with no view on direction. */
function RangesCard({ ranges }: { ranges: PriceRange[] }) {
  return (
    <section className="card" aria-labelledby="ranges">
      <div className="card-head">
        <h2 id="ranges">Likely range</h2>
        <span className="caption">From its own past volatility · not a forecast</span>
      </div>
      <table className="holdings" aria-label="Likely closing prices">
        <thead>
          <tr>
            <th scope="col">In</th>
            <th scope="col" className="num">
              2 times in 3
            </th>
            <th scope="col" className="num">
              9 times in 10
            </th>
          </tr>
        </thead>
        <tbody>
          {ranges.map((r) => (
            <tr key={r.days}>
              <th scope="row">{r.label}</th>
              <td className="num" data-label="2 times in 3">
                {usd(r.low_68)} – {usd(r.high_68)}
              </td>
              <td className="num" data-label="9 times in 10">
                {usd(r.low_90)} – {usd(r.high_90)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caption">
        How far the price has typically swung over the last year, centred on today&apos;s close. It says how wide the
        moves could be, not which way.
      </p>
    </section>
  );
}

/** One stock: levels from daily prices, the next earnings date and recent news.
 * Research only: nothing here is advice to buy or sell. */
export function StockPage() {
  const { symbol = "" } = useParams();
  const client = useQueryClient();
  const stock = useQuery({ queryKey: ["stock", symbol], queryFn: () => api<Stock>(`/investments/stocks/${symbol}`) });
  const data = stock.data;
  const [started, setStarted] = useState<string | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);

  async function startPlan() {
    if (!data) return;
    setPlanError(null);
    try {
      const run = await api<{ run_id: string; title: string }>(`/investments/stocks/${data.symbol}/plan`, { method: "POST" });
      setStarted(`${run.title} started. It takes a minute or two; progress shows on Home and in Telegram.`);
      void client.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : "Couldn't start a plan");
    }
  }

  async function toggleWatch() {
    if (!data) return;
    if (data.watching) await api(`/investments/watchlist/${data.symbol}`, { method: "DELETE" });
    else await api("/investments/watchlist", { method: "POST", body: { symbol: data.symbol } });
    void client.invalidateQueries({ queryKey: ["stock", symbol] });
    void client.invalidateQueries({ queryKey: ["watchlist"] });
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="caption">
            <Link to="/investment">Portfolio</Link> · <Link to="/investment/watchlist">Watchlist</Link>
          </p>
          <h1>{data?.symbol ?? symbol.toUpperCase()}</h1>
          {data?.held && (
            <p className="muted">
              You hold {Number(data.held.quantity).toLocaleString("en-US", { maximumFractionDigits: 8 })} at USD{" "}
              {usd(data.held.average_cost.amount)} average.
            </p>
          )}
        </div>
        {data && !data.held && (
          <button type="button" className="btn" onClick={() => void toggleWatch()}>
            {data.watching ? "Stop watching" : "Watch"}
          </button>
        )}
      </div>
      {stock.isLoading && <p className="state">Loading…</p>}
      {stock.isError && (
        <p className="error-text" role="alert">
          {stock.error instanceof Error ? stock.error.message : "Couldn't load that stock."}
        </p>
      )}
      {data && (data.levels ? (
        <LevelsCard levels={data.levels} />
      ) : (
        <section className="card">
          <p className="state">
            {!data.prices
              ? "Prices aren't set up."
              : data.held || data.watching
                ? "Prices are on their way; levels need about a month of them."
                : "Watch this stock to keep its prices, levels and news."}
          </p>
        </section>
      ))}
      {data && data.ranges.length > 0 && <RangesCard ranges={data.ranges} />}
      {data && data.plans_enabled && data.levels && (
        <section className="card" aria-labelledby="plan">
          <div className="card-head">
            <h2 id="plan">Research plan</h2>
          </div>
          {data.plan ? (
            <div className={`plan-brief ${verdictTone(data.plan.verdict)}`}>
              <strong>{data.plan.verdict_text}</strong>
              <p className="muted">{data.plan.reason}</p>
              <Link to={`/investment/plans/${data.plan.id}`}>See the game plan: when to buy, take profit and cut losses</Link>
              <br />
              <span className="caption">
                Made {formatShortDate(data.plan.created_at)}
                {data.plan.expired && " · expired"}
              </span>
            </div>
          ) : (
            <p className="muted">
              The research team works out when to buy, where to take profit and where to cut losses, then weighs the news and
              both sides.
            </p>
          )}
          <button type="button" className="btn btn-primary" onClick={() => void startPlan()} disabled={started !== null}>
            {data.plan ? "Make a fresh plan" : "Make a plan"}
          </button>
          {started && (
            <p className="muted" role="status">
              {started}
            </p>
          )}
          {planError && (
            <p className="error-text" role="alert">
              {planError}
            </p>
          )}
        </section>
      )}
      {data?.earnings && (
        <section className="card" aria-labelledby="earnings">
          <div className="card-head">
            <h2 id="earnings">Next earnings</h2>
          </div>
          <p>
            {formatShortDate(data.earnings.day, "UTC")}
            {data.earnings.timing && `, ${data.earnings.timing}`}
          </p>
          <p className="caption">Prices often move sharply around earnings.</p>
        </section>
      )}
      {data && (
        <section className="card" aria-labelledby="news">
          <div className="card-head">
            <h2 id="news">News</h2>
            <span className="caption">From news sources, not Nexus</span>
          </div>
          {data.news.length === 0 ? (
            <p className="state">{data.news_enabled ? "No recent news yet." : "News isn't set up."}</p>
          ) : (
            <ul className="feed news" aria-label="Recent news">
              {data.news.map((n) => (
                <li key={n.url}>
                  <a href={n.url} target="_blank" rel="noopener noreferrer nofollow">
                    {n.headline}
                  </a>
                  <br />
                  <span className="caption">
                    {n.source} · {formatShortDate(n.published_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
