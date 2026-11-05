import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type Category,
  type Direction,
  type EditedTransaction,
  type Me,
  receiptUrl,
  type Transaction,
  type TxDirection,
  type Wallet,
} from "../api";
import { isoDay, moveLabel } from "../format";
import { type CardDetails, detailsBody, NO_DETAILS, payingWallets, tracksCards, walletLabel } from "../wallets";
import { CardFields } from "./CardFields";
import { MerchantField } from "./MerchantField";
import { MoneyTrail } from "./MoneyTrail";

/** The "Paid with" option that opens the inline new-card form; never a wallet id. */
const ADD_CARD = "__add-card__";

export function EntrySheet({
  me,
  editing,
  onOpen,
  onClose,
  onSaved,
}: {
  me: Me;
  editing?: Transaction;
  /** Open another transaction, the other side of a repayment. */
  onOpen?: (tx: Transaction) => void;
  onClose: () => void;
  onSaved: (tx: EditedTransaction) => void;
}) {
  const tz = me.user.timezone;
  // Without card tracking there is no "Paid with" at all: no field, no "Add a card…", nothing sent.
  const track = tracksCards(me);
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });
  const why = useQuery({
    queryKey: ["category-explanation", editing?.id],
    queryFn: () => api<{ text: string }>(`/transactions/${editing?.id}/category-explanation`),
    enabled: Boolean(editing?.category_id),
  });
  // A move (money between the user's own wallets) keeps its direction: only its amount,
  // date and notes are edited here.
  const isMove = editing?.direction === "move";
  // New entries can also be a move, so the toggle has a third option.
  const [direction, setDirection] = useState<TxDirection>(editing?.direction ?? "out");
  const moving = !editing && direction === "move";
  const side: Direction = direction === "in" ? "in" : "out";
  const wallets = useQuery({ queryKey: ["wallets"], queryFn: () => api<Wallet[]>("/wallets") });
  const spending = wallets.data?.find((w) => w.kind === "spending");
  const elsewhere = wallets.data?.filter((w) => w.kind !== "spending") ?? [];
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const from = wallets.data?.some((w) => w.id === fromId) ? fromId : (spending?.id ?? "");
  const to = toId !== from && wallets.data?.some((w) => w.id === toId) ? toId : "";
  // "This was a transfer to…", for an entry already logged as money out or in.
  const [marking, setMarking] = useState(false);
  const [markId, setMarkId] = useState("");
  const markWallet = elsewhere.find((w) => w.id === markId) ?? elsewhere[0];
  const [amount, setAmount] = useState(editing ? String(Number(editing.amount.amount)) : "");
  const [currency, setCurrency] = useState(editing?.amount.currency ?? me.user.home_currency);
  const [counterparty, setCounterparty] = useState(editing?.counterparty ?? "");
  const [categoryId, setCategoryId] = useState(editing?.category_id ?? "");
  const [date, setDate] = useState(
    editing ? isoDay(editing.occurred_at, tz) : isoDay(new Date().toISOString(), tz),
  );
  const [notes, setNotes] = useState(editing?.notes ?? "");
  // What paid for it. Until the person picks, a new entry shows the usual card (or, with no usual card,
  // the one card there is) and an old one what it has. An untouched choice is not sent, so the server
  // applies the usual card itself; the lone card is not the usual card, so that one is sent.
  const [pickedPaidWith, setPickedPaidWith] = useState<string | null>(null);
  const paying = payingWallets(wallets.data ?? []);
  const usualCard = paying.find((w) => w.usual);
  const cards = paying.filter((w) => w.kind === "card");
  const loneCard = !editing && !usualCard && cards.length === 1 ? cards[0] : undefined;
  const paidWith = pickedPaidWith ?? (editing ? (editing.paid_with?.id ?? "") : (usualCard?.id ?? loneCard?.id ?? ""));
  // With nothing preselected on a new entry, the empty option asks which card instead of saying "Not set".
  const asking = !editing && wallets.data !== undefined && !usualCard && !loneCard;
  const noCardLabel = !asking ? "Not set" : cards.length === 0 ? "Credit card (add details later)" : "Which card?";
  // A wallet that can't pay any more (its kind changed) stays in the list while the entry names it.
  const stale = editing?.paid_with && !paying.some((w) => w.id === editing.paid_with?.id) ? editing.paid_with : null;
  // "Add a card…": the new card's details, kept apart from the entry so nothing typed there is lost.
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [card, setCard] = useState<CardDetails>(NO_DETAILS);
  const [makeUsual, setMakeUsual] = useState(false);
  const [cardError, setCardError] = useState<string | null>(null);
  const [cardSaving, setCardSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  const addingRef = useRef(false);
  addingRef.current = adding;

  useEffect(() => {
    first.current?.focus();
    // Escape closes the new-card form first, and only then the sheet.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (addingRef.current) setAdding(false);
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function openCardForm() {
    setCard(NO_DETAILS);
    setMakeUsual(false);
    setCardError(null);
    setAdding(true);
  }

  async function addCard() {
    setCardSaving(true);
    setCardError(null);
    // Named like a person would: "Citi PremierMiles", or just "Card" with nothing said.
    const name = [card.issuer, card.product].map((part) => part.trim()).filter(Boolean).join(" ") || "Card";
    let made: Wallet;
    try {
      made = await api<Wallet>("/wallets", {
        method: "POST",
        body: { name, kind: "card", match_words: [], ...detailsBody(card) },
      });
    } catch (e) {
      setCardError(e instanceof Error ? e.message : "Couldn't add it");
      setCardSaving(false);
      return;
    }
    try {
      if (makeUsual) await api("/wallets/usual-card", { method: "PUT", body: { wallet_id: made.id } });
    } catch (e) {
      setError(
        `${made.name} is added, but it couldn't be made your usual card${e instanceof Error ? `: ${e.message}` : ""}`,
      );
    }
    // The card must be in the list before it can be selected.
    await client.invalidateQueries({ queryKey: ["wallets"] });
    setPickedPaidWith(made.id);
    setAdding(false);
    setCardSaving(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const common = {
      amount: amount.trim(),
      currency: currency.trim().toUpperCase(),
      date,
      notes: notes.trim() || null,
    };
    const body = isMove
      ? common
      : {
          ...common,
          direction: side,
          counterparty: counterparty.trim() || null,
          category_id: categoryId || null,
          ...(track && side === "out" && (pickedPaidWith !== null || loneCard) ? { paid_with_wallet_id: paidWith || null } : {}),
        };
    try {
      const tx = moving
        ? await api<Transaction>("/moves", {
            method: "POST",
            body: {
              amount: common.amount,
              currency: common.currency,
              from_wallet_id: from,
              to_wallet_id: to,
              occurred_at: date,
              notes: common.notes,
            },
          })
        : editing
          ? await api<EditedTransaction>(`/transactions/${editing.id}`, { method: "PATCH", body })
          : await api<Transaction>("/transactions", { method: "POST", body });
      onSaved(tx);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  async function markAsMove() {
    if (!editing || !markWallet) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(await api<Transaction>(`/transactions/${editing.id}/move`, { method: "POST", body: { wallet_id: markWallet.id } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make it a transfer");
    } finally {
      setSaving(false);
    }
  }

  const title = isMove
    ? "Edit transfer"
    : editing
      ? "Edit transaction"
      : moving
        ? "Log a transfer"
        : direction === "out"
          ? "Log money out"
          : "Log money in";
  const cardFormOpen = track && adding && !isMove && !moving && side === "out";
  const needsWallet = moving && wallets.data !== undefined && elsewhere.length === 0;
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="entry-title"
        aria-describedby={error ? "entry-error" : undefined}
        onSubmit={submit}
      >
        <h3 id="entry-title">{title}</h3>
        {editing && isMove ? (
          <p className="caption">{moveLabel(editing)} · not counted as spending or income</p>
        ) : (
          <div className="tabs" role="group" aria-label="Direction">
            {(["out", "in", "move"] as const).filter((d) => !editing || d !== "move").map((d) => (
              <button key={d} type="button" className="tab" aria-pressed={direction === d} onClick={() => setDirection(d)}>
                {d === "out" ? "Money out" : d === "in" ? "Money in" : "Transfer"}
              </button>
            ))}
          </div>
        )}
        <div className="row">
          <label className="field">
            Amount
            <input
              ref={first}
              className="input num"
              inputMode="decimal"
              required
              pattern="[0-9]+([.,][0-9]{1,4})?"
              value={amount}
              onChange={(e) => setAmount(e.target.value.replace(",", "."))}
            />
          </label>
          <label className="field">
            Currency
            <input
              className="input"
              required
              maxLength={3}
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            />
          </label>
        </div>
        {moving && needsWallet && (
          <p className="caption">
            <Link to="/settings/wallets" onClick={onClose}>
              Add a wallet in Settings first
            </Link>{" "}
            to transfer money to.
          </p>
        )}
        {moving && !needsWallet && (
          <>
            <label className="field">
              From
              <select className="input" value={from} onChange={(e) => setFromId(e.target.value)}>
                {wallets.data?.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              To
              <select className="input" required value={to} onChange={(e) => setToId(e.target.value)}>
                <option value="">Pick a wallet</option>
                {wallets.data
                  ?.filter((w) => w.id !== from)
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
              </select>
            </label>
          </>
        )}
        {!isMove && !moving && (
          <MerchantField
            label={side === "out" ? "Paid to" : "Received from"}
            value={counterparty}
            direction={side}
            showFrequent={!editing}
            onChange={setCounterparty}
            onPick={(s) => {
              setCounterparty(s.name);
              // The usual category and amount fill what's still empty; nothing typed is replaced.
              if (!categoryId && s.category_id) setCategoryId(s.category_id);
              if (!editing && !amount.trim()) {
                setAmount(String(Number(s.amount.amount)));
                setCurrency(s.amount.currency);
              }
            }}
          />
        )}
        {!isMove && !moving && (
          <label className="field">
            Category
            <select className="input" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              <option value="">Uncategorised</option>
              {categories.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {editing && categoryId === (editing.category_id ?? "") && why.data && (
              <span className="caption">{why.data.text}</span>
            )}
          </label>
        )}
        {track && !isMove && !moving && side === "out" && (
          <label className="field">
            Paid with
            <select
              className="input"
              value={paidWith}
              onChange={(e) => (e.target.value === ADD_CARD ? openCardForm() : setPickedPaidWith(e.target.value))}
            >
              {asking && <option value="">{noCardLabel}</option>}
              {paying.map((w) => (
                <option key={w.id} value={w.id}>
                  {walletLabel(w)}
                </option>
              ))}
              {stale && <option value={stale.id}>{walletLabel(stale)}</option>}
              {!asking && <option value="">{noCardLabel}</option>}
              <option value={ADD_CARD}>+ Add a card…</option>
            </select>
          </label>
        )}
        {cardFormOpen && (
          <div
            className="card-ask"
            role="form"
            aria-label="New card"
            onKeyDown={(e) => {
              // Enter in a box adds the card; it must not save the entry underneath.
              if (e.key === "Enter" && e.target instanceof HTMLInputElement && e.target.type !== "checkbox") {
                e.preventDefault();
                if (!cardSaving) void addCard();
              }
            }}
          >
            <CardFields value={card} onChange={setCard} />
            <label className="check-row">
              <input type="checkbox" checked={makeUsual} onChange={(e) => setMakeUsual(e.target.checked)} />
              Make this my usual card
            </label>
            {cardError && (
              <p className="error-text" role="alert">
                {cardError}
              </p>
            )}
            <div className="quick">
              <button type="button" className="btn btn-primary" disabled={cardSaving} onClick={() => void addCard()}>
                {cardSaving ? "Adding…" : "Add card"}
              </button>
              <button type="button" className="btn" disabled={cardSaving} aria-label="Cancel new card" onClick={() => setAdding(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
        <label className="field">
          Date
          <input className="input" type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        {editing && onOpen && <MoneyTrail tx={editing} timezone={tz} onOpen={onOpen} />}
        {editing?.has_receipt && (
          <a className="btn" href={receiptUrl(editing.id)} target="_blank" rel="noopener noreferrer">
            View receipt
          </a>
        )}
        <label className="field">
          Notes
          <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {editing && !isMove && elsewhere.length > 0 && (
          marking ? (
            <div className="move-ask" role="group" aria-label="Turn into a transfer">
              <label className="field">
                Wallet
                <select className="input" value={markWallet?.id ?? ""} onChange={(e) => setMarkId(e.target.value)}>
                  {elsewhere.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </select>
              </label>
              <p className="caption">
                {editing.direction === "out"
                  ? `Turn this into a transfer from ${spending?.name ?? "your main account"} to ${markWallet?.name}? It will stop counting as spending and lose its category.`
                  : `Turn this into a transfer from ${markWallet?.name} to ${spending?.name ?? "your main account"}? It will stop counting as income.`}
              </p>
              <div className="quick">
                <button type="button" className="btn btn-primary" disabled={saving} onClick={markAsMove}>
                  Turn into a transfer
                </button>
                <button type="button" className="btn" onClick={() => setMarking(false)}>
                  Keep as is
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="btn btn-ghost move-ask-open" onClick={() => setMarking(true)}>
              This was a transfer to…
            </button>
          )
        )}
        {error && (
          <p id="entry-error" className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving || needsWallet || cardFormOpen}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
