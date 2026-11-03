import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Link } from "react-router-dom";

import { api, type CardNetwork, type LikelyMove, type Me, type Wallet, type WalletKind, type WalletSpend } from "../api";
import { MonthPicker } from "../components/MonthPicker";
import { formatDate, formatMoney, txName } from "../format";
import { currentMonth, type MonthKey, monthLabel } from "../months";
import { keepLast4, LAST4_NOTE, payingWallets, walletLabel } from "../wallets";

const KIND_LABEL: Record<WalletKind, string> = {
  spending: "Spending",
  cash: "Cash",
  investment: "Investment",
  savings: "Savings",
  card: "Card",
  other: "Other",
};
/** The kinds a wallet can be given; Spending and Cash are the ones that are always there. */
const KINDS: WalletKind[] = ["savings", "investment", "card", "other"];
const NETWORKS: { key: CardNetwork; label: string }[] = [
  { key: "visa", label: "Visa" },
  { key: "mastercard", label: "Mastercard" },
  { key: "amex", label: "American Express" },
  { key: "other", label: "Other" },
];

/** A card's details as the form holds them. */
type CardDetails = { issuer: string; product: string; network: CardNetwork | ""; last4: string };
const NO_DETAILS: CardDetails = { issuer: "", product: "", network: "", last4: "" };
const detailsOf = (w: Wallet): CardDetails => ({
  issuer: w.issuer ?? "",
  product: w.product ?? "",
  network: w.network ?? "",
  last4: w.last4 ?? "",
});
/** What the API is sent for a card; a blank box clears the field. */
const detailsBody = (d: CardDetails) => ({
  issuer: d.issuer.trim() || null,
  product: d.product.trim() || null,
  network: d.network || null,
  last4: d.last4 || null,
});
/** "Citi · PremierMiles · Visa", the details under a card's name. */
function detailsLine(w: Wallet): string {
  const network = NETWORKS.find((n) => n.key === w.network)?.label;
  return [w.issuer, w.product, network].filter(Boolean).join(" · ");
}

/** The card's own fields: bank, card, network and the last four digits. */
function CardFields({ value, onChange }: { value: CardDetails; onChange: (next: CardDetails) => void }) {
  const [trimmed, setTrimmed] = useState(false);
  return (
    <>
      <label className="field">
        Bank
        <input className="input" placeholder="Citi" value={value.issuer} onChange={(e) => onChange({ ...value, issuer: e.target.value })} />
      </label>
      <label className="field">
        Card
        <input className="input" placeholder="PremierMiles" value={value.product} onChange={(e) => onChange({ ...value, product: e.target.value })} />
      </label>
      <label className="field">
        Network
        <select className="input" value={value.network} onChange={(e) => onChange({ ...value, network: e.target.value as CardNetwork | "" })}>
          <option value="">Not set</option>
          {NETWORKS.map((n) => (
            <option key={n.key} value={n.key}>
              {n.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        Last 4 digits
        <input
          className="input num"
          inputMode="numeric"
          autoComplete="off"
          placeholder="4321"
          pattern="[0-9]{4}"
          title="The last 4 digits of the card"
          value={value.last4}
          onChange={(e) => {
            const kept = keepLast4(e.target.value);
            setTrimmed(kept.trimmed);
            onChange({ ...value, last4: kept.value });
          }}
        />
      </label>
      {trimmed && (
        <p className="caption wallet-note" role="status">
          {LAST4_NOTE}
        </p>
      )}
    </>
  );
}

/** "efund, rainy" to ["efund", "rainy"]: trimmed, no blanks, no repeats. */
function parseWords(text: string): string[] {
  const seen = new Set<string>();
  const words: string[] = [];
  for (const part of text.split(",")) {
    const word = part.trim();
    if (word && !seen.has(word.toLowerCase())) {
      seen.add(word.toLowerCase());
      words.push(word);
    }
  }
  return words;
}

function moves(n: number): string {
  return `${n} ${n === 1 ? "move" : "moves"}`;
}

type DeletePreview = { moved: number; removed: number };

function WalletRow({
  wallet,
  others,
  onChanged,
}: {
  wallet: Wallet;
  others: Wallet[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(wallet.name);
  const [kind, setKind] = useState<WalletKind>(wallet.kind);
  const [words, setWords] = useState(wallet.match_words.join(", "));
  const [details, setDetails] = useState<CardDetails>(detailsOf(wallet));
  const [confirming, setConfirming] = useState(false);
  const [moveTo, setMoveTo] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Spending and Cash are always there: they can be renamed, but not deleted or given another kind.
  const isFixed = wallet.kind === "spending" || wallet.kind === "cash";
  // Its moves go to another wallet; one that isn't Spending, unless that's all there is.
  const fallback = (others.find((w) => w.kind !== "spending") ?? others[0])?.id ?? "";
  const target = others.some((w) => w.id === moveTo) ? moveTo : fallback;
  const targetName = others.find((w) => w.id === target)?.name ?? "";

  // What deleting would do to its moves, asked of the API for the wallet picked.
  const preview = useQuery({
    queryKey: ["wallets", "delete-preview", wallet.id, target],
    queryFn: () => api<DeletePreview>(`/wallets/${wallet.id}/delete-preview?move_to=${encodeURIComponent(target)}`),
    enabled: confirming && Boolean(target),
    staleTime: 0,
  });

  function startEditing() {
    setName(wallet.name);
    setKind(wallet.kind);
    setWords(wallet.match_words.join(", "));
    setDetails(detailsOf(wallet));
    setError(null);
    setEditing(true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api(`/wallets/${wallet.id}`, {
        method: "PATCH",
        body: {
          name: name.trim(),
          match_words: parseWords(words),
          ...(isFixed ? {} : { kind }),
          ...((isFixed ? wallet.kind : kind) === "card" ? detailsBody(details) : {}),
        },
      });
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  async function remove() {
    setError(null);
    try {
      await api(`/wallets/${wallet.id}?move_to=${encodeURIComponent(target)}`, { method: "DELETE" });
      setConfirming(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete");
    }
  }

  function previewText(p: DeletePreview): string {
    if (p.moved + p.removed === 0) return "It has no moves.";
    const go = p.moved === 0 ? `No moves go to ${targetName}` : `${moves(p.moved)} ${p.moved === 1 ? "goes" : "go"} to ${targetName}`;
    return p.removed > 0
      ? `${go}; ${moves(p.removed)} between the two will be removed.`
      : `${go}.`;
  }

  return (
    <li className="budget">
      {editing ? (
        <form className="budget-edit" onSubmit={save} aria-label={`Edit ${wallet.name}`}>
          <label className="field">
            Name
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          {!isFixed && (
            <label className="field">
              Kind
              <select className="input" value={kind} onChange={(e) => setKind(e.target.value as WalletKind)}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABEL[k]}
                  </option>
                ))}
              </select>
            </label>
          )}
          {kind === "card" && <CardFields value={details} onChange={setDetails} />}
          <label className="field">
            Match words
            <input className="input" placeholder="efund, rainy day" value={words} onChange={(e) => setWords(e.target.value)} />
          </label>
          <span className="quick">
            <button type="submit" className="btn btn-primary" disabled={!name.trim()}>
              Save
            </button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </span>
        </form>
      ) : (
        <>
          <div className="budget-head">
            <div className="wallet-name">
              <h3 className="wrap">{walletLabel(wallet)}</h3>
              <span className="caption">{KIND_LABEL[wallet.kind]}</span>
              {wallet.usual && <span className="chip">Usual card</span>}
            </div>
            {!confirming && (
              <span className="quick">
                <button type="button" className="btn btn-ghost" onClick={startEditing}>
                  Edit
                </button>
                {!isFixed && (
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
                    Delete
                  </button>
                )}
              </span>
            )}
          </div>
          {detailsLine(wallet) && <p className="caption">{detailsLine(wallet)}</p>}
          {wallet.match_words.length > 0 && (
            <ul className="chips category-chips" aria-label={`Match words for ${wallet.name}`}>
              {wallet.match_words.map((w) => (
                <li key={w} className="chip">
                  {w}
                </li>
              ))}
            </ul>
          )}
          {confirming && (
            <>
              <span className="quick">
                <span>Delete {wallet.name}? Its moves go to</span>
                <select
                  className="input"
                  aria-label={`Move ${wallet.name} moves to`}
                  value={target}
                  onChange={(e) => setMoveTo(e.target.value)}
                >
                  {others.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </select>
              </span>
              {preview.data && <p className="caption">{previewText(preview.data)}</p>}
              {preview.isError && <p className="caption error-text">Couldn't check its moves.</p>}
              <span className="quick">
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={!target || preview.isLoading}
                  onClick={() => void remove()}
                >
                  Delete
                </button>
                <button type="button" className="btn" onClick={() => setConfirming(false)}>
                  Keep
                </button>
              </span>
            </>
          )}
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** Entries that look like moves, one at a time. Nothing changes until "Make it a move";
 * "Not a move" only skips it for now (it comes back next time). */
function LikelyMoves({ found, wallets, onChanged }: { found: LikelyMove[]; wallets: Wallet[]; onChanged: () => void }) {
  const [reviewing, setReviewing] = useState(false);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const left = found.filter((f) => !skipped.has(f.transaction.id));
  if (found.length === 0) return null;
  const current = left[0];
  const elsewhere = wallets.filter((w) => w.kind !== "spending");

  if (!reviewing || !current)
    return (
      <div className="likely-moves">
        <p className="caption">
          {left.length === 0 && reviewing
            ? "That's all of them."
            : `${left.length} ${left.length === 1 ? "entry looks" : "entries look"} like ${left.length === 1 ? "a move" : "moves"}`}
        </p>
        {left.length > 0 && (
          <button type="button" className="btn btn-small" onClick={() => setReviewing(true)}>
            Review
          </button>
        )}
      </div>
    );

  const tx = current.transaction;
  const wallet = picked[tx.id] ?? current.wallet?.id ?? "";

  async function convert() {
    setBusy(true);
    setError(null);
    try {
      await api(`/transactions/${tx.id}/move`, { method: "POST", body: { wallet_id: wallet } });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make it a move");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="likely-moves" role="group" aria-label="Review likely moves">
      <p className="caption">
        {found.length - left.length + 1} of {found.length}
      </p>
      <div className="budget-head">
        <h3 className="wrap">{txName(tx)}</h3>
        <span className={tx.direction === "in" ? "num amount-in" : "num"}>
          {tx.direction === "in" ? "+" : ""}
          {formatMoney(tx.amount)}
        </span>
      </div>
      <p className="caption">
        {formatDate(tx.occurred_at)} · {current.reason}
      </p>
      <label className="field">
        {tx.direction === "in" ? "Moved from" : "Moved to"}
        <select className="input" value={wallet} onChange={(e) => setPicked({ ...picked, [tx.id]: e.target.value })}>
          {!wallet && <option value="">Choose a wallet</option>}
          {elsewhere.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </label>
      <span className="quick">
        <button type="button" className="btn btn-primary btn-small" disabled={!wallet || busy} onClick={() => void convert()}>
          Make it a move
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={busy}
          onClick={() => setSkipped(new Set(skipped).add(tx.id))}
        >
          Not a move
        </button>
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setReviewing(false)}>
          Close
        </button>
      </span>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function purchases(n: number): string {
  return `${n} ${n === 1 ? "purchase" : "purchases"}`;
}

/** One card (or Spending, Cash) with what it paid for in the month: "SGD 1,240.00 this month · 38 purchases",
 * and a link to the ledger filtered to it. */
function SpendLine({ wallet, month, current }: { wallet: Wallet; month: MonthKey; current: MonthKey }) {
  const spend = useQuery({
    queryKey: ["wallets", "spend", wallet.id, month],
    queryFn: () => api<WalletSpend>(`/wallets/${wallet.id}/spend?month=${month}`),
  });
  const when = month === current ? "this month" : `in ${monthLabel(month)}`;
  return (
    <li className="wallet-spend-row">
      <span className="wrap wallet-spend-name">{walletLabel(wallet)}</span>
      <span className="caption wallet-spend-figure">
        {spend.data
          ? `${formatMoney(spend.data.total)} ${when} · ${purchases(spend.data.count)}`
          : spend.isError
            ? "Couldn't load"
            : "Loading…"}
      </span>
      <Link
        className="caption"
        to={`/accounting/ledger?paid_with=${encodeURIComponent(wallet.id)}`}
        aria-label={`See in ledger for ${walletLabel(wallet)}`}
      >
        See in ledger
      </Link>
    </li>
  );
}

/** The user's wallets: places money is moved between. Spending and Cash are always two of them. */
export function WalletsSection({ me }: { me: Me }) {
  const client = useQueryClient();
  const current = currentMonth(me.user.timezone);
  const [month, setMonth] = useState<MonthKey>(current);
  const all = useQuery({ queryKey: ["wallets"], queryFn: () => api<Wallet[]>("/wallets") });
  const likely = useQuery({
    queryKey: ["wallets", "likely-moves"],
    queryFn: () => api<LikelyMove[]>("/wallets/likely-moves"),
  });
  const [name, setName] = useState("");
  const [kind, setKind] = useState<WalletKind>("savings");
  const [words, setWords] = useState("");
  const [details, setDetails] = useState<CardDetails>(NO_DETAILS);
  const [error, setError] = useState<string | null>(null);
  const [usualError, setUsualError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  function refresh() {
    for (const key of ["wallets", "transactions", "summary", "budgets", "home"])
      void client.invalidateQueries({ queryKey: [key] });
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/wallets", {
        method: "POST",
        body: { name: name.trim(), kind, match_words: parseWords(words), ...(kind === "card" ? detailsBody(details) : {}) },
      });
      setName("");
      setWords("");
      setDetails(NO_DETAILS);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add it");
    }
  }

  // The usual card is what an expense is paid with when none is said; one at a time, or none.
  async function setUsual(id: string) {
    setUsualError(null);
    try {
      await api("/wallets/usual-card", { method: "PUT", body: { wallet_id: id || null } });
      refresh();
    } catch (e) {
      setUsualError(e instanceof Error ? e.message : "Couldn't save that");
    }
  }

  const wallets = all.data ?? [];
  const paying = payingWallets(wallets);
  const usual = paying.find((w) => w.usual);
  return (
    <section className="card" aria-labelledby="wallets">
      <div className="card-head">
        <h2 id="wallets">Wallets</h2>
        <span className="caption">Where you move money</span>
      </div>
      {all.isLoading && <p className="state">Loading…</p>}
      {all.isError && <p className="state error-text">Couldn't load wallets.</p>}
      {!open && wallets.length > 0 && (
        <>
          <p className="caption">
            {wallets.length} {wallets.length === 1 ? "wallet" : "wallets"}
          </p>
          <ul className="chips category-chips" aria-label="Wallet names">
            {wallets.map((w) => (
              <li key={w.id} className="chip">
                {w.name}
              </li>
            ))}
          </ul>
        </>
      )}
      {paying.length > 0 && (
        <div className="wallet-usual">
          <label className="field">
            Usual card
            <select className="input" value={usual?.id ?? ""} onChange={(e) => void setUsual(e.target.value)}>
              <option value="">None</option>
              {paying.map((w) => (
                <option key={w.id} value={w.id}>
                  {walletLabel(w)}
                </option>
              ))}
            </select>
            <span className="caption">Used when you don't say which card</span>
          </label>
          {usualError && (
            <p className="error-text" role="alert">
              {usualError}
            </p>
          )}
        </div>
      )}
      {paying.length > 0 && (
        <div className="wallet-spend" role="group" aria-label="Spend by card">
          <div className="wallet-spend-head">
            <h3>Paid with</h3>
            <MonthPicker month={month} current={current} onChange={setMonth} />
          </div>
          <ul className="wallet-spend-list" aria-label="What each card paid for">
            {paying.map((w) => (
              <SpendLine key={w.id} wallet={w} month={month} current={current} />
            ))}
          </ul>
        </div>
      )}
      <LikelyMoves found={likely.data ?? []} wallets={wallets} onChanged={refresh} />
      <details className="category-fold" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary className="btn">{open ? "Done" : "Manage"}</summary>
        {wallets.length > 0 && (
          <ul className="budgets" aria-label="Your wallets">
            {wallets.map((w) => (
              <WalletRow key={w.id} wallet={w} others={wallets.filter((o) => o.id !== w.id)} onChanged={refresh} />
            ))}
          </ul>
        )}
        <form className="budget-add plan-add" onSubmit={add} aria-label="Add a wallet">
          <label className="field">
            New wallet
            <input className="input" placeholder="Emergency fund" value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label className="field">
            Kind
            <select className="input" value={kind} onChange={(e) => setKind(e.target.value as WalletKind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
          {kind === "card" && <CardFields value={details} onChange={setDetails} />}
          <label className="field">
            Match words (optional)
            <input className="input" placeholder="efund, rainy day" value={words} onChange={(e) => setWords(e.target.value)} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={!name.trim()}>
            Add
          </button>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
        </form>
      </details>
    </section>
  );
}
