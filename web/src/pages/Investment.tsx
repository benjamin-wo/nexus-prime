import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Dividends, type Holding, type HoldingsDraft, type Portfolio, type PortfolioTotals, type TradeRecord } from "../api";
import { formatChange, formatMoney, formatPercent, formatShortDate } from "../format";
import { base64 } from "../files";

const shares = (quantity: string) => Number(quantity).toLocaleString("en-US", { maximumFractionDigits: 8 });

function DraftCard({ draft, onDone }: { draft: HoldingsDraft; onDone: (message: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  async function act(action: "save" | "discard") {
    setError(null);
    try {
      await api(`/investments/drafts/${draft.id}/${action}`, { method: "POST" });
      onDone(action === "save" ? `Saved ${draft.positions.length} positions.` : "Left your holdings as they were.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't do that");
    }
  }
  const nothing = !draft.first && draft.changes.length === 0;
  return (
    <section className="card" aria-labelledby="from-screenshot">
      <div className="card-head">
        <h2 id="from-screenshot">From your screenshot</h2>
      </div>
      {draft.first ? (
        <ul className="feed" aria-label="Positions read">
          {draft.positions.map((p) => (
            <li key={p.symbol} className="run-row">
              <span>
                <strong>{p.symbol}</strong> · {shares(p.quantity)} at {formatMoney(p.average_cost)}
              </span>
              <span className="caption num">{formatMoney(p.cost)}</span>
            </li>
          ))}
        </ul>
      ) : nothing ? (
        <p className="muted">It matches the holdings you already have.</p>
      ) : (
        <ul className="feed" aria-label="Changes">
          {draft.changes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <p className="caption">Check the numbers against your broker before saving. Stocks the screenshot doesn't show are removed.</p>
      <span className="quick">
        {!nothing && (
          <button type="button" className="btn btn-primary" onClick={() => void act("save")}>
            {draft.first ? "Save holdings" : "Update holdings"}
          </button>
        )}
        <button type="button" className="btn" onClick={() => void act("discard")}>
          {nothing ? "OK" : "Discard"}
        </button>
      </span>
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  );
}

/** "+USD 120.00 (+4.2%)", coloured by direction. */
function Change({ amount, percent }: { amount: Holding["gain"]; percent: string | null }) {
  if (!amount) return <span className="muted">—</span>;
  const value = Number(amount.amount);
  return (
    <span className={value > 0 ? "up" : value < 0 ? "down" : undefined}>
      {formatChange(amount)}
      {percent !== null && ` (${formatPercent(percent)})`}
    </span>
  );
}

function Totals({ totals }: { totals: PortfolioTotals }) {
  if (!totals.value) return null;
  return (
    <dl className="totals" aria-label="Portfolio totals">
      <div>
        <dt>Value</dt>
        <dd className="num">{formatMoney(totals.value)}</dd>
      </div>
      <div>
        <dt>Gain or loss</dt>
        <dd className="num">
          <Change amount={totals.gain} percent={totals.gain_percent} />
        </dd>
      </div>
      {totals.day_change && (
        <div>
          <dt>Last day</dt>
          <dd className="num">
            <Change amount={totals.day_change} percent={totals.day_percent} />
          </dd>
        </div>
      )}
      {totals.realised && (
        <div>
          <dt>Locked in by sales</dt>
          <dd className="num">
            <Change amount={totals.realised} percent={null} />
          </dd>
        </div>
      )}
      {totals.dividends && (
        <div>
          <dt>Dividends (after tax)</dt>
          <dd className="num">{formatMoney(totals.dividends)}</dd>
        </div>
      )}
      {totals.total_return && (totals.realised || totals.dividends) && (
        <div>
          <dt>Total return</dt>
          <dd className="num">
            <Change amount={totals.total_return} percent={null} />
          </dd>
        </div>
      )}
    </dl>
  );
}

/** Trades the user recorded, with what each sale locked in, and a form to record one. */
function Trades({ onChanged }: { onChanged: () => void }) {
  const client = useQueryClient();
  const trades = useQuery({ queryKey: ["trades"], queryFn: () => api<TradeRecord[]>("/investments/trades") });
  const [form, setForm] = useState({ side: "buy", symbol: "", quantity: "", price: "", day: "" });
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function record(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/investments/trades", {
        method: "POST",
        body: { side: form.side, symbol: form.symbol.trim(), quantity: form.quantity, price: form.price.trim() || null, traded_on: form.day || null },
      });
      setForm({ side: "buy", symbol: "", quantity: "", price: "", day: "" });
      void client.invalidateQueries({ queryKey: ["trades"] });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record that");
    }
  }

  const list = trades.data ?? [];
  return (
    <section className="card" aria-labelledby="trades">
      <div className="card-head">
        <h2 id="trades">Trades</h2>
        <span className="caption">What you bought and sold at your broker. Sales show what they locked in at your average cost.</span>
      </div>
      {list.length === 0 && !trades.isLoading && <p className="state">No trades recorded yet. Record one below or tell the bot ("sold 5 AAPL at 230").</p>}
      {list.length > 0 && (
        <ul className="feed" aria-label="Trade history">
          {list.map((t) => (
            <li key={t.id} className="run-row">
              <span className="wrap">
                <strong>
                  {t.side === "buy" ? "Bought" : "Sold"} {t.quantity} {t.symbol}
                </strong>
                <br />
                <span className="caption">
                  {formatShortDate(t.traded_on, "UTC")}
                  {t.price && ` · at ${formatMoney(t.price)}`}
                </span>
              </span>
              {t.realised && (
                <span className="num">
                  <Change amount={t.realised} percent={null} />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <form className="quick add-holding" onSubmit={record} aria-label="Record a trade">
        <label className="field">
          Side
          <select className="input" value={form.side} onChange={set("side")}>
            <option value="buy">Bought</option>
            <option value="sell">Sold</option>
          </select>
        </label>
        <label className="field">
          Ticker
          <input className="input" value={form.symbol} maxLength={10} onChange={set("symbol")} required />
        </label>
        <label className="field">
          Shares
          <input className="input" inputMode="decimal" value={form.quantity} onChange={set("quantity")} required />
        </label>
        <label className="field">
          Price (USD)
          <input className="input" inputMode="decimal" value={form.price} onChange={set("price")} required={form.side === "buy"} />
        </label>
        <label className="field">
          Date
          <input className="input" type="date" value={form.day} onChange={set("day")} />
        </label>
        <button type="submit" className="btn">
          Record
        </button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** Dividends received on held shares, and what the holdings would pay in a year. */
function DividendsCard() {
  const data = useQuery({ queryKey: ["dividends"], queryFn: () => api<Dividends>("/investments/dividends") }).data;
  if (!data || (data.received.length === 0 && data.expected.length === 0)) return null;
  return (
    <section className="card" aria-labelledby="dividends">
      <div className="card-head">
        <h2 id="dividends">Dividends</h2>
        <span className="caption">After tax withheld: 30% on US dividends for Singapore residents</span>
      </div>
      <dl className="totals" aria-label="Dividend totals">
        {data.this_year_home && (
          <div>
            <dt>This year</dt>
            <dd className="num">{formatMoney(data.this_year_home)}</dd>
          </div>
        )}
        {data.received_home && (
          <div>
            <dt>Received in all</dt>
            <dd className="num">{formatMoney(data.received_home)}</dd>
          </div>
        )}
        {data.expected_home && (
          <div>
            <dt>Next 12 months (est.)</dt>
            <dd className="num">{formatMoney(data.expected_home)}</dd>
          </div>
        )}
      </dl>
      {data.expected.length > 0 && (
        <ul className="feed" aria-label="Expected dividends">
          {data.expected.map((e) => (
            <li key={e.symbol} className="run-row">
              <span className="wrap">
                <strong>{e.symbol}</strong>
                <br />
                <span className="caption">
                  {formatMoney(e.per_share)} a share over {e.payments} payment{e.payments === 1 ? "" : "s"} in the last year
                  {e.yield_on_value && ` · yield ${e.yield_on_value}%`}
                  {e.yield_on_cost && ` · ${e.yield_on_cost}% on cost`}
                </span>
              </span>
              <span className="num">≈ {formatMoney(e.net)}/yr</span>
            </li>
          ))}
        </ul>
      )}
      {data.received.length > 0 && (
        <ul className="feed" aria-label="Dividends received">
          {data.received.map((d) => (
            <li key={`${d.symbol}:${d.ex_date}`} className="run-row">
              <span className="wrap">
                <strong>{d.symbol}</strong>
                <br />
                <span className="caption">
                  Ex {formatShortDate(d.ex_date, "UTC")} · {formatMoney(d.per_share)} on {d.shares} shares · {formatMoney(d.withheld)} withheld
                </span>
              </span>
              <span className="num">{formatMoney(d.net)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function HoldingRow({ position, onChanged }: { position: Holding; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [quantity, setQuantity] = useState(position.quantity);
  const [cost, setCost] = useState(position.average_cost.amount);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api(`/investments/holdings/${position.symbol}`, {
        method: "PUT",
        body: { quantity, average_cost: cost, currency: position.average_cost.currency },
      });
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
    }
  }

  async function remove() {
    await api(`/investments/holdings/${position.symbol}`, { method: "DELETE" });
    onChanged();
  }

  return (
    <tr>
      <th scope="row">
        <Link to={`/investment/stocks/${position.symbol}`}>{position.symbol}</Link>
        {position.earnings && (
          <span className="caption"> · earnings {formatShortDate(position.earnings.day, "UTC")}</span>
        )}
      </th>
      {editing ? (
        <td colSpan={5}>
          <form className="quick" onSubmit={save} aria-label={`Edit ${position.symbol}`}>
            <label className="field">
              Shares
              <input className="input" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            </label>
            <label className="field">
              Avg cost ({position.average_cost.currency})
              <input className="input" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
            </label>
            <button type="submit" className="btn btn-primary">Save</button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>Cancel</button>
            {error && <span className="error-text" role="alert">{error}</span>}
          </form>
        </td>
      ) : (
        <>
          <td className="num" data-label="Shares">{shares(position.quantity)}</td>
          <td className="num" data-label="Avg cost">{formatMoney(position.average_cost)}</td>
          <td className="num" data-label="Last close">
            {position.price ? formatMoney(position.price) : <span className="muted">—</span>}
          </td>
          <td className="num" data-label="Value">
            {position.value ? formatMoney(position.value) : formatMoney(position.cost)}
            {!position.value && <span className="caption"> cost</span>}
          </td>
          <td className="num" data-label="Gain">
            <Change amount={position.gain} percent={position.gain_percent} />
          </td>
        </>
      )}
      <td className="quick">
        {!editing && (
          <>
            <button type="button" className="btn btn-small" onClick={() => setEditing(true)} aria-label={`Edit ${position.symbol}`}>
              Edit
            </button>
            <button type="button" className="btn btn-small" onClick={() => void remove()} aria-label={`Remove ${position.symbol}`}>
              Remove
            </button>
          </>
        )}
      </td>
    </tr>
  );
}

function priceNote(data: Portfolio | undefined): string {
  if (!data || data.holdings.length === 0) return "";
  if (!data.prices) return "Prices aren't set up";
  const t = data.totals;
  const parts = [];
  if (t.as_of) parts.push(`Closing prices of ${formatShortDate(t.as_of, "UTC")}`);
  if (t.missing.length) parts.push(`no price yet for ${t.missing.join(", ")}`);
  return parts.join("; ") || "Fetching prices…";
}

/** The Investment department: holdings, from a broker screenshot or typed in. */
export function InvestmentPage() {
  const client = useQueryClient();
  const portfolio = useQuery({ queryKey: ["investments"], queryFn: () => api<Portfolio>("/investments") });
  const [reading, setReading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState({ symbol: "", quantity: "", cost: "" });
  const refresh = () => {
    // Holdings, trades and dividends move together.
    for (const key of ["investments", "trades", "dividends"]) void client.invalidateQueries({ queryKey: [key] });
  };

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(null);
    setNotice(null);
    setReading(true);
    try {
      await api("/investments/screenshot", {
        method: "POST",
        body: { image: await base64(file), mime_type: file.type || "image/png" },
      });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't read that screenshot");
    } finally {
      setReading(false);
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api(`/investments/holdings/${adding.symbol.trim().toUpperCase()}`, {
        method: "PUT",
        body: { quantity: adding.quantity, average_cost: adding.cost, currency: "USD" },
      });
      setAdding({ symbol: "", quantity: "", cost: "" });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add that");
    }
  }

  const holdings = portfolio.data?.holdings ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Portfolio</h1>
          <p className="muted">What you hold and what it's worth at the last close. Research only: Nexus never trades.</p>
        </div>
        {portfolio.data?.screenshots && (
          <label className="btn btn-primary">
            {reading ? "Reading…" : "Upload screenshot"}
            <input className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => void upload(e)} disabled={reading} />
          </label>
        )}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {notice && <p className="muted" role="status">{notice}</p>}
      {portfolio.data?.draft && (
        <DraftCard
          draft={portfolio.data.draft}
          onDone={(message) => {
            setNotice(message);
            refresh();
          }}
        />
      )}

      <section className="card" aria-labelledby="holdings">
        <div className="card-head">
          <h2 id="holdings">Holdings</h2>
          <span className="caption">{priceNote(portfolio.data)}</span>
        </div>
        {portfolio.data && <Totals totals={portfolio.data.totals} />}
        {portfolio.isLoading && <p className="state">Loading…</p>}
        {portfolio.data && holdings.length === 0 && (
          <p className="state">
            No holdings yet. Upload a screenshot of your broker's Portfolio screen (IBKR first), send it to the bot, or
            add one below.
          </p>
        )}
        {holdings.length > 0 && (
          <div className="table-wrap">
            <table className="holdings">
              <thead>
                <tr>
                  <th scope="col">Stock</th>
                  <th scope="col" className="num">Shares</th>
                  <th scope="col" className="num">Avg cost</th>
                  <th scope="col" className="num">Last close</th>
                  <th scope="col" className="num">Value</th>
                  <th scope="col" className="num">Gain</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((p) => (
                  <HoldingRow key={`${p.symbol}:${p.updated_at}`} position={p} onChanged={refresh} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <form className="quick add-holding" onSubmit={add} aria-label="Add a holding">
          <label className="field">
            Ticker
            <input className="input" value={adding.symbol} maxLength={10} onChange={(e) => setAdding({ ...adding, symbol: e.target.value })} required />
          </label>
          <label className="field">
            Shares
            <input className="input" inputMode="decimal" value={adding.quantity} onChange={(e) => setAdding({ ...adding, quantity: e.target.value })} required />
          </label>
          <label className="field">
            Avg cost (USD)
            <input className="input" inputMode="decimal" value={adding.cost} onChange={(e) => setAdding({ ...adding, cost: e.target.value })} required />
          </label>
          <button type="submit" className="btn">Add</button>
        </form>
      </section>
      <DividendsCard />
      <Trades onChanged={refresh} />
    </>
  );
}
