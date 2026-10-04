import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Watchlist } from "../api";
import { formatPercent, formatShortDate } from "../format";

const usd = (amount: string) => Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Stocks the user follows without holding them: prices, levels and news are kept
 * for them as for holdings. */
export function WatchlistPage() {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["watchlist"], queryFn: () => api<Watchlist>("/investments/watchlist") });
  const [symbol, setSymbol] = useState("");
  const [error, setError] = useState<string | null>(null);
  const refresh = () => void client.invalidateQueries({ queryKey: ["watchlist"] });

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/investments/watchlist", { method: "POST", body: { symbol: symbol.trim() } });
      setSymbol("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add that");
    }
  }

  async function remove(ticker: string) {
    await api(`/investments/watchlist/${ticker}`, { method: "DELETE" }).catch(() => undefined);
    refresh();
  }

  const stocks = list.data?.stocks ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Watchlist</h1>
          <p className="muted">Stocks you follow. Open one for its levels, earnings date and news.</p>
        </div>
      </div>
      <section className="card" aria-labelledby="watching">
        <div className="card-head">
          <h2 id="watching">Watching</h2>
          {list.data && !list.data.prices && <span className="caption">Prices aren't set up</span>}
        </div>
        {list.isLoading && <p className="state">Loading…</p>}
        {list.data && stocks.length === 0 && <p className="state">Nothing on your watchlist yet. Add a ticker below.</p>}
        {stocks.length > 0 && (
          <ul className="feed" aria-label="Watched stocks">
            {stocks.map((s) => (
              <li key={s.symbol} className="run-row">
                <span className="wrap">
                  <Link to={`/investment/stocks/${s.symbol}`}>
                    <strong>{s.symbol}</strong>
                  </Link>
                  {s.price && (
                    <>
                      {" "}
                      · USD {usd(s.price)}
                      {s.day_percent !== null && (
                        <span className={Number(s.day_percent) > 0 ? "up" : Number(s.day_percent) < 0 ? "down" : undefined}>
                          {" "}
                          {formatPercent(s.day_percent)}
                        </span>
                      )}
                    </>
                  )}
                  <br />
                  <span className="caption">
                    {s.price_day ? `Close of ${formatShortDate(s.price_day, "UTC")}` : "Price coming"}
                    {s.earnings && ` · earnings ${formatShortDate(s.earnings.day, "UTC")}`}
                  </span>
                </span>
                <button type="button" className="btn btn-small" onClick={() => void remove(s.symbol)} aria-label={`Stop watching ${s.symbol}`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <form className="quick add-holding" onSubmit={add} aria-label="Watch a stock">
          <label className="field">
            Ticker
            <input className="input" value={symbol} maxLength={12} onChange={(e) => setSymbol(e.target.value)} required />
          </label>
          <button type="submit" className="btn">
            Watch
          </button>
        </form>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </section>
    </>
  );
}
