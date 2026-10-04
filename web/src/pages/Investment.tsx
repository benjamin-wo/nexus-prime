import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, type FormEvent, useState } from "react";

import { api, type HoldingsDraft, type Portfolio, type Position } from "../api";
import { formatMoney } from "../format";

const shares = (quantity: string) => Number(quantity).toLocaleString("en-US", { maximumFractionDigits: 8 });

/** The file as base64, without the "data:...;base64," prefix. */
function base64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

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

function HoldingRow({ position, onChanged }: { position: Position; onChanged: () => void }) {
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
      <th scope="row">{position.symbol}</th>
      {editing ? (
        <td colSpan={3}>
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
          <td className="num">{shares(position.quantity)}</td>
          <td className="num">{formatMoney(position.average_cost)}</td>
          <td className="num">{formatMoney(position.cost)}</td>
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

/** The Investment department: holdings, from a broker screenshot or typed in. */
export function InvestmentPage() {
  const client = useQueryClient();
  const portfolio = useQuery({ queryKey: ["investments"], queryFn: () => api<Portfolio>("/investments") });
  const [reading, setReading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState({ symbol: "", quantity: "", cost: "" });
  const refresh = () => void client.invalidateQueries({ queryKey: ["investments"] });

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
          <p className="muted">What you hold and what it cost. Research only: Nexus never trades.</p>
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
          <span className="caption">Prices and values come next</span>
        </div>
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
                  <th scope="col" className="num">Cost</th>
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
    </>
  );
}
