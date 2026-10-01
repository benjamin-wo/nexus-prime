import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  api,
  type Category,
  type Direction,
  type EditedTransaction,
  type Me,
  receiptUrl,
  type Transaction,
} from "../api";
import { isoDay } from "../format";
import { MoneyTrail } from "./MoneyTrail";

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
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });
  const why = useQuery({
    queryKey: ["category-explanation", editing?.id],
    queryFn: () => api<{ text: string }>(`/transactions/${editing?.id}/category-explanation`),
    enabled: Boolean(editing?.category_id),
  });
  const [direction, setDirection] = useState<Direction>(editing?.direction ?? "out");
  const [amount, setAmount] = useState(editing ? String(Number(editing.amount.amount)) : "");
  const [currency, setCurrency] = useState(editing?.amount.currency ?? me.user.home_currency);
  const [counterparty, setCounterparty] = useState(editing?.counterparty ?? "");
  const [categoryId, setCategoryId] = useState(editing?.category_id ?? "");
  const [date, setDate] = useState(
    editing ? isoDay(editing.occurred_at, tz) : isoDay(new Date().toISOString(), tz),
  );
  const [notes, setNotes] = useState(editing?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const body = {
      direction,
      amount: amount.trim(),
      currency: currency.trim().toUpperCase(),
      date,
      counterparty: counterparty.trim() || null,
      category_id: categoryId || null,
      notes: notes.trim() || null,
    };
    try {
      const tx = editing
        ? await api<EditedTransaction>(`/transactions/${editing.id}`, { method: "PATCH", body })
        : await api<Transaction>("/transactions", { method: "POST", body });
      onSaved(tx);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  const title = editing ? "Edit transaction" : direction === "out" ? "Log money out" : "Log money in";
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
        <div className="tabs" role="group" aria-label="Direction">
          {(["out", "in"] as const).map((d) => (
            <button key={d} type="button" className="tab" aria-pressed={direction === d} onClick={() => setDirection(d)}>
              {d === "out" ? "Money out" : "Money in"}
            </button>
          ))}
        </div>
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
        <label className="field">
          {direction === "out" ? "Paid to" : "Received from"}
          <input className="input" value={counterparty} onChange={(e) => setCounterparty(e.target.value)} />
        </label>
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
        {error && (
          <p id="entry-error" className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
