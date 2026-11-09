import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  api,
  type Category,
  type CategoryRule,
  type LedgerFilters,
  ledgerParams,
  type Me,
  type Page,
  receiptUrl,
  type Transaction,
  type Wallet,
} from "../api";
import { Icon } from "../components/Icon";
import { Kaya } from "../components/Kaya";
import { Menu } from "../components/Menu";
import { MoneyTrail } from "../components/MoneyTrail";
import { Sheet } from "../components/Sheet";
import { DirectionBadge } from "../components/Badge";
import { Toast } from "../components/Toast";
import { Amount } from "../components/Amount";
import { formatDate, formatMoney, formatShortDate, moveLabel, txName } from "../format";
import { payingWallets, tracksCards, walletLabel } from "../wallets";

const PAGE = 50;
type View = "all" | "out" | "in" | "move" | "pending";
const VIEWS: { key: View; label: string }[] = [
  { key: "all", label: "All" },
  { key: "out", label: "Money out" },
  { key: "in", label: "Money in" },
  { key: "move", label: "Transfers" },
  { key: "pending", label: "Pending" },
];

type Range = { key: "any" | "this" | "last"; label: string; start: string; end: string };

/** The usual date ranges, as the user's own calendar has them. */
function ranges(timezone: string): Range[] {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
  const [y, m] = today.split("-").map(Number);
  const iso = (year: number, month: number, day: number) =>
    `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const [ly, lm] = m === 1 ? [y - 1, 12] : [y, m - 1];
  const lastDay = new Date(Date.UTC(ly, lm, 0)).getUTCDate();
  return [
    { key: "any", label: "All dates", start: "", end: "" },
    { key: "this", label: "This month", start: iso(y, m, 1), end: "" },
    { key: "last", label: "Last month", start: iso(ly, lm, 1), end: iso(ly, lm, lastDay) },
  ];
}

/** What a date filter is called on its chip: a usual range by name, anything else by its dates. */
function dateLabel(preset: Range | undefined, start: string, end: string): string {
  if (preset) return preset.label;
  if (start && end) return `${start} to ${end}`;
  return start ? `From ${start}` : `Until ${end}`;
}

export function Ledger({ me, onAdd, onEdit }: { me: Me; onAdd: () => void; onEdit: (tx: Transaction) => void }) {
  const client = useQueryClient();
  // Once the header's Add has scrolled away, a floating one stands in for it.
  const headerAdd = useRef<HTMLButtonElement>(null);
  const [addAway, setAddAway] = useState(false);
  useEffect(() => {
    const button = headerAdd.current;
    if (!button || typeof IntersectionObserver === "undefined") return;
    const watch = new IntersectionObserver(([entry]) => setAddAway(!entry.isIntersecting));
    watch.observe(button);
    return () => watch.disconnect();
  }, []);
  // A link from a spending category opens the ledger filtered to it.
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<View>(() => VIEWS.find((v) => v.key === params.get("view"))?.key ?? "all");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [start, setStart] = useState(() => params.get("start") ?? "");
  const [end, setEnd] = useState(() => params.get("end") ?? "");
  const [category, setCategory] = useState(() => params.get("category") ?? "");
  // The card that paid, kept in the address as ?paid_with=<wallet id> ("none" for entries with no card set).
  // Without card tracking there is no card filter, so a ?paid_with= left in an old link is ignored.
  const track = tracksCards(me);
  const paidWith = track ? (params.get("paid_with") ?? "") : "";
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const presets = useMemo(() => ranges(me.user.timezone), [me.user.timezone]);
  const preset = presets.find((r) => r.start === start && r.end === end);
  // Dates of their own (or from a link) show the two date boxes.
  const [custom, setCustom] = useState(() => !presets.some((r) => r.start === start && r.end === end));
  // On a phone the tick boxes wait for "Select"; on a wider screen they're always there.
  const [selecting, setSelecting] = useState(false);
  const [toast, setToast] = useState<{ message: string; undo?: () => void } | null>(null);
  const [confirming, setConfirming] = useState(false);
  // The filter sheet: the type, the dates and (with card tracking) the card.
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const filters: LedgerFilters = useMemo(
    () => ({
      direction: view === "out" || view === "in" || view === "move" ? view : undefined,
      status: view === "pending" ? "pending" : undefined,
      search: debounced || undefined,
      start: start || undefined,
      end: end || undefined,
      category_id: category && category !== "none" ? category : undefined,
      uncategorized: category === "none" || undefined,
      paid_with: paidWith || undefined,
    }),
    [view, debounced, start, end, category, paidWith],
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
    queryFn: () => api<Category[]>("/categories"),
  });
  const names = new Map(categories.data?.map((c) => [c.id, c.name]));
  const wallets = useQuery({ queryKey: ["wallets"], queryFn: () => api<Wallet[]>("/wallets") });
  const paying = payingWallets(wallets.data ?? []);
  const paidWithWallet = wallets.data?.find((w) => w.id === paidWith);
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

  async function mergeTwins(tx: Transaction) {
    const twin = tx.duplicate;
    if (!twin) return;
    try {
      const done = await api<{ kept: Transaction; removed: Transaction }>(`/transactions/${tx.id}/merge`, {
        method: "POST",
        body: { other_id: twin.transaction_id },
      });
      const before = done.kept.id === tx.id ? tx.counterparty : twin.counterparty;
      refresh();
      setToast({
        message: `Merged into one: ${done.kept.counterparty ?? "no merchant"} ${formatMoney(done.kept.amount)}.`,
        undo: async () => {
          await api(`/transactions/${done.removed.id}/restore`, { method: "POST" });
          if (before !== done.kept.counterparty) {
            await api(`/transactions/${done.kept.id}`, { method: "PATCH", body: { counterparty: before } });
          }
          setToast({ message: "Restored both." });
          refresh();
        },
      });
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "Couldn't merge" });
    }
  }

  async function notDuplicate(tx: Transaction) {
    if (!tx.duplicate) return;
    try {
      await api(`/transactions/${tx.id}/not-duplicate`, {
        method: "POST",
        body: { other_id: tx.duplicate.transaction_id },
      });
      refresh();
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "Couldn't save that" });
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
  const filtered = view !== "all" || Boolean(debounced || start || end || category || paidWith);
  const categoryName = category === "none" ? "Uncategorised" : names.get(category);

  // One control for the usual ranges; "Custom dates" keeps what is set and shows the two date boxes.
  function pickDates(value: string) {
    const range = presets.find((r) => r.key === value);
    if (!range) {
      setCustom(true);
      return;
    }
    setCustom(false);
    setStart(range.start);
    setEnd(range.end);
  }

  function pickPaidWith(value: string) {
    setParams(
      (p) => {
        if (value) p.set("paid_with", value);
        else p.delete("paid_with");
        return p;
      },
      { replace: true },
    );
  }

  function clearCategory() {
    setCategory("");
    setParams(
      (p) => {
        p.delete("category");
        return p;
      },
      { replace: true },
    );
  }

  // The filters set, as the count on the Filter button and the chips under it (the search has its own box).
  const dated = Boolean(start || end);
  const activeCount = (view !== "all" ? 1 : 0) + (dated ? 1 : 0) + (paidWith ? 1 : 0) + (category ? 1 : 0);
  const viewLabel = VIEWS.find((v) => v.key === view)?.label ?? "";
  const cardName = paidWith === "none" ? "No card set" : paidWithWallet ? walletLabel(paidWithWallet) : "…";
  const total = page.data?.total;
  // The date on a phone's second line is short ("27 Sep"), with the year only for another year.
  const yearOf = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: me.user.timezone, year: "numeric" }).format(d);
  const thisYear = yearOf(new Date());
  const rowDate = (iso: string) =>
    yearOf(new Date(iso)) === thisYear ? formatShortDate(iso, me.user.timezone) : formatDate(iso, me.user.timezone);

  function clearAll() {
    setView("all");
    setStart("");
    setEnd("");
    setCustom(false);
    setParams(
      (p) => {
        p.delete("paid_with");
        p.delete("category");
        return p;
      },
      { replace: true },
    );
    setCategory("");
  }

  return (
    <>
      <div className="page-head page-head-row">
        <h1>Ledger</h1>
        <div className="quick">
          <button type="button" className="btn btn-primary" aria-label="Add transaction" ref={headerAdd} onClick={onAdd}>
            <Icon name="plus" size={18} />
            Add
          </button>
          <Menu
            label="More"
            items={[
              { key: "import", label: "Import statement", to: "/settings/import" },
              { key: "export", label: "Export CSV", href: exportHref, download: true },
            ]}
          />
        </div>
      </div>

      <section className="card fab-clearance" aria-label="Transactions">
        <div className="filters">
          <div className="filter-row">
            <label className="search">
              <span className="sr-only">Search merchant or notes</span>
              <input
                className="input"
                type="search"
                placeholder="Search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn filter-btn"
              aria-haspopup="dialog"
              aria-label={activeCount > 0 ? `Filter, ${activeCount} active` : undefined}
              onClick={() => setSheetOpen(true)}
            >
              <Icon name="sliders" size={18} />
              Filter
              {activeCount > 0 && (
                <span className="filter-count" aria-hidden="true">
                  {activeCount}
                </span>
              )}
            </button>
          </div>
          {activeCount > 0 && (
            <div className="filter-chips" role="group" aria-label="Active filters">
              {view !== "all" && (
                <span className="filter-chip">
                  <span>{viewLabel}</span>
                  <button type="button" className="chip-x" onClick={() => setView("all")} aria-label={`Show all types, not just ${viewLabel}`}>
                    ×
                  </button>
                </span>
              )}
              {dated && (
                <span className="filter-chip">
                  <span>{dateLabel(preset, start, end)}</span>
                  <button type="button" className="chip-x" onClick={() => pickDates("any")} aria-label="Show all dates">
                    ×
                  </button>
                </span>
              )}
              {paidWith && (
                <span className="filter-chip">
                  <span>{cardName}</span>
                  <button
                    type="button"
                    className="chip-x"
                    onClick={() => pickPaidWith("")}
                    aria-label={`Show every card, not just ${paidWith === "none" ? "entries with no card set" : paidWithWallet ? walletLabel(paidWithWallet) : "this one"}`}
                  >
                    ×
                  </button>
                </span>
              )}
              {category && (
                <span className="filter-chip">
                  <span>
                    <span className="caption">Category</span> {categoryName ?? "…"}
                  </span>
                  <button type="button" className="chip-x" onClick={clearCategory} aria-label={`Show every category, not just ${categoryName ?? "this one"}`}>
                    ×
                  </button>
                </span>
              )}
            </div>
          )}
        </div>

        {items.length > 0 && (
          <div className="list-head">
            <span className="caption">
              {page.data?.total} {page.data?.total === 1 ? "transaction" : "transactions"}
            </span>
            <button
              type="button"
              className="btn btn-small select-toggle"
              aria-pressed={selecting}
              onClick={() => {
                if (selecting) setSelected(new Set());
                setSelecting(!selecting);
              }}
            >
              {selecting ? "Done" : "Select"}
            </button>
          </div>
        )}

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
          filtered ? (
            <p className="state">Nothing matches these filters.</p>
          ) : (
            <p className="state state-kaya">
              <Kaya size={44} lazy />
              <span>No transactions yet. Just ask Kaya to log one, e.g. "kopi 4.20".</span>
            </p>
          )
        )}
        {items.length > 0 && (
          <div className="table-wrap">
            <table className={`ledger ledger-list${selecting ? " selecting" : ""}`}>
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
                        className="btn btn-ghost tx-name"
                        onClick={(e) => {
                          e.stopPropagation();
                          onEdit(tx);
                        }}
                      >
                        {txName(tx)}
                      </button>
                      {/* One line under the merchant. On a phone it holds the category and the date, whose own
                          columns are gone; wider screens keep those in their columns. */}
                      <div className="tx-meta">
                        {tx.category_id && names.get(tx.category_id) && (
                          <span className="category-line">{names.get(tx.category_id)}</span>
                        )}
                        <span className="date-line">{rowDate(tx.occurred_at)}</span>
                        {track && tx.paid_with && <span className="caption paid-with-line">{walletLabel(tx.paid_with)}</span>}
                        {tx.has_receipt && (
                          <a
                            className="receipt-link"
                            href={receiptUrl(tx.id)}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <span>Receipt</span>
                          </a>
                        )}
                      </div>
                      {tx.direction === "move" && tx.counterparty && (
                        <div className="caption">{moveLabel(tx)}</div>
                      )}
                      {tx.notes && <div className="caption">{tx.notes}</div>}
                      <MoneyTrail tx={tx} timezone={me.user.timezone} onOpen={onEdit} />
                      {tx.duplicate && (
                        <div className="duplicate" onClick={(e) => e.stopPropagation()}>
                          <span className="caption">
                            Possible duplicate of {tx.duplicate.counterparty ?? "an entry"},{" "}
                            {formatDate(tx.duplicate.occurred_at, me.user.timezone)}
                          </span>
                          <span className="quick">
                            <button type="button" className="btn btn-small" onClick={() => void mergeTwins(tx)}>
                              Merge
                            </button>
                            <button type="button" className="btn btn-small" onClick={() => void notDuplicate(tx)}>
                              Not a duplicate
                            </button>
                          </span>
                        </div>
                      )}
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
      {sheetOpen && (
        <Sheet
          title="Filter transactions"
          className="filter-sheet"
          onClose={() => setSheetOpen(false)}
          footer={
            <div className="filter-sheet-foot">
              <button type="button" className="btn" disabled={activeCount === 0} onClick={clearAll}>
                Clear
              </button>
              <button type="button" className="btn btn-primary" onClick={() => setSheetOpen(false)}>
                {total === undefined ? "Done" : `Show ${total} ${total === 1 ? "transaction" : "transactions"}`}
              </button>
            </div>
          }
        >
          <div className="filter-group">
            <span className="filter-label" id="filter-type-label">
              Show
            </span>
            <div className="tabs" role="group" aria-labelledby="filter-type-label">
              {VIEWS.map((v) => (
                <button key={v.key} type="button" className="tab" aria-pressed={view === v.key} onClick={() => setView(v.key)}>
                  {v.label}
                </button>
              ))}
            </div>
          </div>
          <div className="filter-group">
            <label className="field">
              Dates
              <select className="input" value={custom || !preset ? "custom" : preset.key} onChange={(e) => pickDates(e.target.value)}>
                {presets.map((r) => (
                  <option key={r.key} value={r.key}>
                    {r.label}
                  </option>
                ))}
                <option value="custom">Custom</option>
              </select>
            </label>
            {custom && (
              <div className="date-range">
                <label className="date-field">
                  <span className="date-caption">From</span>
                  <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
                </label>
                <label className="date-field">
                  <span className="date-caption">To</span>
                  <input className="input" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
                </label>
              </div>
            )}
          </div>
          {track && (
            <div className="filter-group">
              <label className="field">
                Paid with
                <select className="input" value={paidWith} onChange={(e) => pickPaidWith(e.target.value)}>
                  <option value="">Any</option>
                  {paying.map((w) => (
                    <option key={w.id} value={w.id}>
                      {walletLabel(w)}
                    </option>
                  ))}
                  {paidWith && paidWith !== "none" && !paying.some((w) => w.id === paidWith) && paidWithWallet && (
                    <option value={paidWith}>{walletLabel(paidWithWallet)}</option>
                  )}
                  <option value="none">Not set</option>
                </select>
              </label>
            </div>
          )}
        </Sheet>
      )}
      {addAway && (
        <button type="button" className="fab fab-steady" aria-label="Add a transaction" onClick={onAdd}>
          <Icon name="plus" size={20} />
          Add
        </button>
      )}
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
