import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, type FormEvent, useCallback, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Dividends, type Holding, type HoldingsDraft, type Portfolio, type PortfolioTotals, type PriceKind, type TradeRecord } from "../api";
import { formatChange, formatMoney, formatPercent, formatShortDate } from "../format";
import { livePolling } from "../prices";
import { base64 } from "../files";
import { ConfirmBox } from "../components/ConfirmBox";
import { Foldaway } from "../components/Foldaway";
import { PriceWhen } from "../components/PriceWhen";
import { TodayCard } from "../components/TodayCard";
import { Toast } from "../components/Toast";
import { Button, buttonClass, Row, RowList, Section } from "../components/ui";

import "./invest.css";

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
    <Section id="from-screenshot" title="From your screenshot">
      {draft.first ? (
        <RowList aria-label="Positions read">
          {draft.positions.map((p) => (
            <Row
              key={p.symbol}
              title={
                <>
                  <strong>{p.symbol}</strong> · {shares(p.quantity)} at {formatMoney(p.average_cost)}
                </>
              }
              trailing={formatMoney(p.cost)}
            />
          ))}
        </RowList>
      ) : nothing ? (
        <p className="muted">It matches the holdings you already have.</p>
      ) : (
        <RowList aria-label="Changes">
          {draft.changes.map((line) => (
            <Row key={line} title={line} />
          ))}
        </RowList>
      )}
      <p className="caption">Check the numbers against your broker before saving. Stocks the screenshot doesn't show are removed.</p>
      <span className="quick">
        {!nothing && (
          <Button variant="primary" onClick={() => void act("save")}>
            {draft.first ? "Save holdings" : "Update holdings"}
          </Button>
        )}
        <Button onClick={() => void act("discard")}>{nothing ? "OK" : "Discard"}</Button>
      </span>
      {error && <p className="error-text" role="alert">{error}</p>}
    </Section>
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
function Trades({ onChanged }: { onChanged: (message: string) => void }) {
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
      onChanged(`Recorded: ${form.side === "buy" ? "bought" : "sold"} ${form.quantity.trim()} ${form.symbol.trim().toUpperCase()}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record that");
    }
  }

  const list = trades.data ?? [];
  return (
    <Section id="trades" title="Trades">
      <p className="caption">What you bought and sold at your broker. Sales show what they locked in at your average cost.</p>
      {list.length === 0 && !trades.isLoading && <p className="empty-line">No trades recorded yet.</p>}
      {list.length > 0 && (
        <RowList aria-label="Trade history">
          {list.map((t) => (
            <Row
              key={t.id}
              title={
                <strong>
                  {t.side === "buy" ? "Bought" : "Sold"} {t.quantity} {t.symbol}
                </strong>
              }
              sub={
                <>
                  {formatShortDate(t.traded_on, "UTC")}
                  {t.price && ` · at ${formatMoney(t.price)}`}
                </>
              }
              trailing={t.realised && <Change amount={t.realised} percent={null} />}
            />
          ))}
        </RowList>
      )}
      <Foldaway label="Record a trade">
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
          <Button type="submit" variant="secondary">
            Record
          </Button>
        </form>
      </Foldaway>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Section>
  );
}

/** Dividends received on held shares, and what the holdings would pay in a year. */
function DividendsCard() {
  const data = useQuery({ queryKey: ["dividends"], queryFn: () => api<Dividends>("/investments/dividends") }).data;
  if (!data || (data.received.length === 0 && data.expected.length === 0)) return null;
  return (
    <Section id="dividends" title="Dividends">
      <p className="caption">After tax withheld: 30% on US dividends for Singapore residents</p>
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
        <RowList aria-label="Expected dividends">
          {data.expected.map((e) => (
            <Row
              key={e.symbol}
              title={<strong>{e.symbol}</strong>}
              sub={
                <>
                  {formatMoney(e.per_share)} a share over {e.payments} payment{e.payments === 1 ? "" : "s"} in the last year
                  {e.yield_on_value && ` · yield ${e.yield_on_value}%`}
                  {e.yield_on_cost && ` · ${e.yield_on_cost}% on cost`}
                </>
              }
              trailing={`≈ ${formatMoney(e.net)}/yr`}
            />
          ))}
        </RowList>
      )}
      {data.received.length > 0 && (
        <RowList aria-label="Dividends received">
          {data.received.map((d) => (
            <Row
              key={`${d.symbol}:${d.ex_date}`}
              title={<strong>{d.symbol}</strong>}
              sub={`Ex ${formatShortDate(d.ex_date, "UTC")} · ${formatMoney(d.per_share)} on ${d.shares} shares · ${formatMoney(d.withheld)} withheld`}
              trailing={formatMoney(d.net)}
            />
          ))}
        </RowList>
      )}
    </Section>
  );
}

/** `kind` is the kind of the card's own label: a row whose price is of another kind says so. */
export function HoldingRow({ position, kind, onChanged }: { position: Holding; kind: PriceKind; onChanged: (message?: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
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
      onChanged(`Updated ${position.symbol}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
    }
  }

  // Removing a holding can't be undone from here, so it asks first, in the page.
  async function remove() {
    setError(null);
    setBusy(true);
    try {
      await api(`/investments/holdings/${position.symbol}`, { method: "DELETE" });
      onChanged(`Removed ${position.symbol}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove that");
      setConfirming(false);
      setBusy(false);
    }
  }

  return (
    <>
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
            <Button type="submit" variant="primary">Save</Button>
            <Button onClick={() => setEditing(false)}>Cancel</Button>
            {error && <span className="error-text" role="alert">{error}</span>}
          </form>
        </td>
      ) : (
        <>
          <td className="num" data-label="Shares">{shares(position.quantity)}</td>
          <td className="num" data-label="Avg cost">{formatMoney(position.average_cost)}</td>
          <td className="num" data-label="Price">
            <span className="price-cell">
              {position.price ? formatMoney(position.price) : <span className="muted">—</span>}
              {position.price && (
                <span className={position.price_kind === kind ? "when-common" : undefined}>
                  <PriceWhen kind={position.price_kind} at={position.price_at} day={position.price_day} />
                </span>
              )}
            </span>
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
        {!editing && !confirming && (
          <>
            <Button size="sm" onClick={() => setEditing(true)} aria-label={`Edit ${position.symbol}`}>
              Edit
            </Button>
            <Button variant="danger" size="sm" className="holding-remove" onClick={() => setConfirming(true)} aria-label={`Remove ${position.symbol}`}>
              Remove
            </Button>
          </>
        )}
      </td>
    </tr>
    {confirming && (
      <tr>
        <td colSpan={7}>
          <ConfirmBox
            label={`Remove ${position.symbol}`}
            question={`Remove ${position.symbol} from your holdings? Your trades stay in the list.`}
            confirm="Remove"
            busy={busy}
            onConfirm={() => void remove()}
            onKeep={() => setConfirming(false)}
          />
        </td>
      </tr>
    )}
    {!editing && error && (
      <tr>
        <td colSpan={7}>
          <span className="error-text" role="alert">{error}</span>
        </td>
      </tr>
    )}
    </>
  );
}

/** When the prices in the table are from, and which stocks have none. */
function PriceNote({ data }: { data: Portfolio | undefined }) {
  if (!data || data.holdings.length === 0) return null;
  if (!data.prices) return <span className="caption">Prices aren't set up</span>;
  const t = data.totals;
  const missing = t.missing.length ? `no price yet for ${t.missing.join(", ")}` : null;
  if (!t.as_of && !t.as_of_at) return <span className="caption">{missing ?? "Fetching prices…"}</span>;
  return (
    <PriceWhen kind={t.price_kind} at={t.as_of_at} day={t.as_of}>
      {missing}
    </PriceWhen>
  );
}

/** The Investment department: holdings, from a broker screenshot or typed in. */
export function InvestmentPage() {
  const client = useQueryClient();
  const portfolio = useQuery({
    queryKey: ["investments"],
    queryFn: () => api<Portfolio>("/investments"),
    // Every minute while the prices are live and the page is in view.
    refetchInterval: (query) => livePolling(query.state.data?.totals.price_kind),
  });
  const [reading, setReading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState({ symbol: "", quantity: "", cost: "" });
  // A line at the bottom for what was just added, recorded or removed.
  const [done, setDone] = useState<string | null>(null);
  const closeDone = useCallback(() => setDone(null), []);
  const refresh = () => {
    // Holdings, trades and dividends move together.
    for (const key of ["investments", "trades", "dividends"]) void client.invalidateQueries({ queryKey: [key] });
  };
  const changed = (message?: string) => {
    refresh();
    if (message) setDone(message);
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
      const symbol = adding.symbol.trim().toUpperCase();
      await api(`/investments/holdings/${symbol}`, {
        method: "PUT",
        body: { quantity: adding.quantity, average_cost: adding.cost, currency: "USD" },
      });
      setAdding({ symbol: "", quantity: "", cost: "" });
      changed(`Added ${symbol}`);
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
          <p className="muted">What you hold, at the latest price. Nexus never trades.</p>
        </div>
        {portfolio.data?.screenshots && (
          <label className={buttonClass({ variant: "primary" })}>
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

      <TodayCard />

      <Section id="holdings" title="Holdings" action={<PriceNote data={portfolio.data} />}>
        {portfolio.data && <Totals totals={portfolio.data.totals} />}
        {portfolio.isLoading && <p className="state">Loading…</p>}
        {portfolio.data && holdings.length === 0 && (
          <p className="empty-line">
            No holdings yet. Upload a screenshot of your broker's Portfolio screen, or send it to the bot.
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
                  <th scope="col" className="num">Price</th>
                  <th scope="col" className="num">Value</th>
                  <th scope="col" className="num">Gain</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((p) => (
                  <HoldingRow key={`${p.symbol}:${p.updated_at}`} position={p} kind={portfolio.data?.totals.price_kind ?? "close"} onChanged={changed} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Foldaway label="Add one by hand">
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
            <Button type="submit" variant="secondary">Add</Button>
          </form>
        </Foldaway>
      </Section>
      <DividendsCard />
      <Trades onChanged={changed} />
      {done && <Toast message={done} onClose={closeDone} />}
    </>
  );
}
