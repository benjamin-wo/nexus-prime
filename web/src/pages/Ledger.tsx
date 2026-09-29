import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  type Category,
  type CategoryRule,
  type LedgerFilters,
  ledgerParams,
  type Me,
  type Page,
  type Transaction,
} from "../api";
import { DirectionBadge } from "../components/Badge";
import { Toast } from "../components/Toast";
import { Amount } from "../components/Amount";
import { formatDate, formatMoney } from "../format";

const PAGE = 50;
type View = "all" | "out" | "in" | "pending";
const VIEWS: { key: View; label: string }[] = [
  { key: "all", label: "All" },
  { key: "out", label: "Money out" },
  { key: "in", label: "Money in" },
  { key: "pending", label: "Pending" },
];

export function Ledger({ me, onAdd, onEdit }: { me: Me; onAdd: () => void; onEdit: (tx: Transaction) => void }) {
  const client = useQueryClient();
  const [view, setView] = useState<View>("all");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ message: string; undo?: () => void } | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const filters: LedgerFilters = useMemo(
    () => ({
      direction: view === "out" || view === "in" ? view : undefined,
      status: view === "pending" ? "pending" : undefined,
      search: debounced || undefined,
      start: start || undefined,
      end: end || undefined,
    }),
    [view, debounced, start, end],
  );
  useEffect(() => {
    setOffset(0);
    setSelected(new Set());
  }, [filters]);

  const page = useQuery({
    queryKey: ["transactions", filters, offset],
    queryFn: () => api<Page>(`/transactions?${ledgerParams(filters, { limit: PAGE, offset })}`),
  });
  const categories = useQuery({
    queryKey: ["categories", "all"],
    queryFn: () => api<Category[]>("/categories?include_inactive=true"),
  });
  const names = new Map(categories.data?.map((c) => [c.id, c.name]));
  const rules = useQuery({ queryKey: ["category-rules"], queryFn: () => api<CategoryRule[]>("/category-rules") });
  const patterns = new Map(rules.data?.map((r) => [r.id, r.pattern]));

  function refresh() {
    void client.invalidateQueries({ queryKey: ["transactions"] });
    void client.invalidateQueries({ queryKey: ["summary"] });
    void client.invalidateQueries({ queryKey: ["ious"] });
  }

  async function bulkDelete() {
    const ids = [...selected];
    setConfirming(false);
    try {
      const done = await api<{ ids: string[] }>("/transactions/bulk-delete", { method: "POST", body: { ids } });
      setSelected(new Set());
      refresh();
      setToast({
        message: `Deleted ${done.ids.length} ${done.ids.length === 1 ? "transaction" : "transactions"}.`,
        undo: async () => {
          await api("/transactions/bulk-restore", { method: "POST", body: { ids: done.ids } });
          setToast({ message: "Restored." });
          refresh();
        },
      });
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "Couldn't delete" });
    }
  }

  function toggle(id: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const items = page.data?.items ?? [];
  const allChecked = items.length > 0 && items.every((t) => selected.has(t.id));
  const exportHref = `/api/export.csv?${ledgerParams(filters)}`;
  const filtered = view !== "all" || Boolean(debounced || start || end);

  return (
    <>
      <div className="page-head">
        <h1>Ledger</h1>
        <div className="quick">
          <a className="btn" href={exportHref} download>
            Export CSV
          </a>
          <button type="button" className="btn btn-primary" onClick={onAdd}>
            Add transaction
          </button>
        </div>
      </div>

      <section className="card" aria-label="Transactions">
        <div className="filters">
          <div className="tabs" role="group" aria-label="Show">
            {VIEWS.map((v) => (
              <button key={v.key} type="button" className="tab" aria-pressed={view === v.key} onClick={() => setView(v.key)}>
                {v.label}
              </button>
            ))}
          </div>
          <label className="search">
            <span className="sr-only">Search merchant or notes</span>
            <input
              className="input"
              type="search"
              placeholder="Search merchant or notes"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="date-field">
            <span className="date-caption">From</span>
            <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="date-field">
            <span className="date-caption">To</span>
            <input className="input" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>

        {selected.size > 0 && (
          <div className="bulkbar" role="region" aria-label="Selection">
            <span>{selected.size} selected</span>
            {confirming ? (
              <>
                <span>Delete {selected.size}? You can undo.</span>
                <button type="button" className="btn btn-danger" onClick={bulkDelete}>
                  Delete
                </button>
                <button type="button" className="btn" onClick={() => setConfirming(false)}>
                  Keep
                </button>
              </>
            ) : (
              <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
                Delete selected
              </button>
            )}
          </div>
        )}

        {page.isLoading && <p className="state">Loading…</p>}
        {page.isError && <p className="state error-text">Couldn't load transactions.</p>}
        {page.data && items.length === 0 && (
          <p className="state">{filtered ? "Nothing matches these filters." : "No transactions yet."}</p>
        )}
        {items.length > 0 && (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th scope="col">
                    <input
                      type="checkbox"
                      aria-label="Select all on this page"
                      checked={allChecked}
                      onChange={() => setSelected(allChecked ? new Set() : new Set(items.map((t) => t.id)))}
                    />
                  </th>
                  <th scope="col">Date</th>
                  <th scope="col">Merchant or source</th>
                  <th scope="col" className="hide-mobile">
                    Category
                  </th>
                  <th scope="col" className="hide-mobile">
                    Type
                  </th>
                  <th scope="col" className="amount">
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((tx) => (
                  <tr key={tx.id} aria-selected={selected.has(tx.id)} onClick={() => onEdit(tx)}>
                    <td className="select" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${tx.counterparty ?? "transaction"} ${formatMoney(tx.amount)}`}
                        checked={selected.has(tx.id)}
                        onChange={() => toggle(tx.id)}
                      />
                    </td>
                    <td className="num date">{formatDate(tx.occurred_at, me.user.timezone)}</td>
                    <td className="wrap merchant">
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          onEdit(tx);
                        }}
                      >
                        {tx.counterparty ?? "No merchant"}
                      </button>
                      {tx.notes && <div className="caption">{tx.notes}</div>}
                    </td>
                    <td className="hide-mobile secondary">
                      {tx.category_id ? names.get(tx.category_id) : "—"}
                      {tx.category_rule_id && patterns.has(tx.category_rule_id) && (
                        <div className="caption">by rule “{patterns.get(tx.category_rule_id)}”</div>
                      )}
                    </td>
                    <td className="hide-mobile">
                      <DirectionBadge tx={tx} />
                    </td>
                    <td className={`amount num amount-${tx.direction}`}>
                      <Amount tx={tx} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page.data && page.data.total > PAGE && (
          <div className="pager">
            <span className="muted">
              {offset + 1}–{Math.min(offset + PAGE, page.data.total)} of {page.data.total}
            </span>
            <span className="quick">
              <button type="button" className="btn" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
                Previous
              </button>
              <button
                type="button"
                className="btn"
                disabled={offset + PAGE >= page.data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </button>
            </span>
          </div>
        )}
      </section>
      {toast && (
        <Toast
          message={toast.message}
          action={toast.undo ? { label: "Undo", run: toast.undo } : undefined}
          onClose={() => setToast(null)}
        />
      )}
    </>
  );
}
