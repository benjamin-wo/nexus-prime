import { useQuery } from "@tanstack/react-query";

import { api, type Category, type LedgerFilters, ledgerParams, type Money, type Page, type Transaction } from "../api";
import { Amount } from "../components/Amount";
import { formatMoney, formatShortDate, txName } from "../format";
import type { PanelEvent } from "./types";

type Props = { event: Extract<PanelEvent, { kind: "finance.transactions" }>; timezone?: string };

/** The most rows the panel lists; the Ledger has the rest. */
export const MAX_ROWS = 20;
/** How many the panel fetches, to count and total them (the endpoint's largest page). */
const FETCH = 500;

/** The filters are named as GET /api/transactions names them, so they go to it as they are. */
export function useTransactionsPanel(filters: Record<string, string>) {
  return useQuery({
    queryKey: ["transactions", "panel", filters],
    queryFn: () => api<Page>(`/transactions?${ledgerParams(filters as LedgerFilters, { limit: FETCH })}`),
  });
}

/** What the fetched rows add up to per direction, each currency on its own (a foreign amount counts at its
 * home-currency equivalent when the server gave one). Moves between your own wallets are not counted. */
export function totals(items: Transaction[]): { out: Money[]; in: Money[] } {
  const sums = { out: new Map<string, number>(), in: new Map<string, number>() };
  for (const tx of items) {
    if (tx.deleted || tx.direction === "move") continue;
    const m = tx.home?.amount ?? tx.amount;
    const into = sums[tx.direction];
    into.set(m.currency, (into.get(m.currency) ?? 0) + Number(m.amount));
  }
  const list = (map: Map<string, number>): Money[] =>
    [...map].map(([currency, sum]) => ({ amount: String(Math.round(sum * 100) / 100), currency }));
  return { out: list(sums.out), in: list(sums.in) };
}

const count = (n: number) => `${n} ${n === 1 ? "transaction" : "transactions"}`;
const moneyList = (list: Money[]) => list.map(formatMoney).join(" + ");

/** The one figure a collapsed card shows: how many, and what they add up to. */
export function TransactionsHeadline({ event }: Pick<Props, "event">) {
  const page = useTransactionsPanel(event.params);
  if (page.isLoading) return <span className="caption">Loading…</span>;
  if (!page.data) return <span className="caption">Not loaded</span>;
  const sum = totals(page.data.items);
  const money = sum.out.length > 0 ? `${moneyList(sum.out)} out` : sum.in.length > 0 ? `${moneyList(sum.in)} in` : null;
  return (
    <span className="panel-figure">
      <span className="num">{count(page.data.total)}</span>
      {money && <span className="caption">{money}</span>}
    </span>
  );
}

/** A compact list of the matching transactions, newest first, read-only. */
export function TransactionsPanel({ event, timezone = "UTC" }: Props) {
  const filters = event.params;
  const page = useTransactionsPanel(filters);
  const categories = useQuery({ queryKey: ["categories", "all"], queryFn: () => api<Category[]>("/categories") });
  if (page.isLoading) return <p className="state">Loading…</p>;
  if (page.isError || !page.data) return <p className="state error-text">Couldn't load these transactions.</p>;
  const { items, total } = page.data;
  const names = new Map(categories.data?.map((c) => [c.id, c.name]));
  const sum = totals(items);
  return (
    <div className="panel-transactions">
      <p className="panel-summary">
        <strong>{count(total)}</strong>
        {sum.out.length > 0 && <span className="num"> · {moneyList(sum.out)} out</span>}
        {sum.in.length > 0 && <span className="num"> · {moneyList(sum.in)} in</span>}
        {total > items.length && <span className="caption"> (the newest {items.length})</span>}
      </p>
      {items.length === 0 ? (
        <p className="state">Nothing matches.</p>
      ) : (
        <ul className="panel-items panel-tx" aria-label="Matching transactions">
          {items.slice(0, MAX_ROWS).map((tx) => (
            <li key={tx.id}>
              <span className="caption panel-day">{formatShortDate(tx.occurred_at, timezone)}</span>
              <span className="wrap">
                {txName(tx)}
                {tx.status === "pending" && <span className="caption"> · pending</span>}
                {tx.deleted && <span className="caption"> · deleted</span>}
                {tx.category_id && names.get(tx.category_id) && <span className="caption panel-cat">{names.get(tx.category_id)}</span>}
              </span>
              <span className={`num amount-${tx.direction}`}>
                <Amount tx={tx} />
              </span>
            </li>
          ))}
        </ul>
      )}
      {total > MAX_ROWS && (
        <p className="caption">
          Showing {MAX_ROWS} of {total}.
        </p>
      )}
    </div>
  );
}

