import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, type LedgerFilters, ledgerParams, type Page, type Transaction } from "../api";
import { formatMoney, formatShortDate, txName } from "../format";

const SHOWN = 8;

/** A category's spending in a period: null is "Uncategorised", undefined is
 * everything (an overall budget). */
export type CategoryPick = { category: string | null | undefined; start: string; end: string };

/** The same filters the totals use: confirmed money out in the period. */
export function categoryFilters({ category, start, end }: CategoryPick): LedgerFilters {
  return {
    direction: "out",
    status: "confirmed",
    start,
    end,
    ...(category === null ? { uncategorized: true } : category ? { category_id: category } : {}),
  };
}

/** Where "See all" goes: the ledger, filtered the same way. */
export function ledgerLink({ category, start, end }: CategoryPick): string {
  const params = new URLSearchParams({ view: "out", start, end });
  if (category !== undefined) params.set("category", category ?? "none");
  return `/accounting/ledger?${params.toString()}`;
}

function HomeAmount({ tx }: { tx: Transaction }) {
  const home = tx.home?.amount;
  return (
    <span className="num">
      {formatMoney(tx.amount)}
      {home && home.currency !== tx.amount.currency && <span className="caption"> ({formatMoney(home)})</span>}
    </span>
  );
}

/** The latest transactions behind one category total, unfolded under it. */
export function CategoryTransactions({
  pick,
  name,
  id,
  timezone,
}: {
  pick: CategoryPick;
  name: string;
  id?: string;
  timezone?: string;
}) {
  const filters = categoryFilters(pick);
  const page = useQuery({
    queryKey: ["transactions", filters, "peek"],
    queryFn: () => api<Page>(`/transactions?${ledgerParams(filters, { limit: SHOWN })}`),
  });
  const items = page.data?.items ?? [];
  const total = page.data?.total ?? 0;
  return (
    <div className="peek" id={id}>
      {page.isLoading && <p className="caption">Loading…</p>}
      {page.isError && <p className="caption error-text">Couldn't load these transactions.</p>}
      {page.data && items.length === 0 && <p className="caption">No transactions here.</p>}
      {items.length > 0 && (
        <ul className="peek-list" aria-label={`${name} transactions`}>
          {items.map((tx) => (
            <li key={tx.id} className="peek-row">
              <span className="caption peek-day">{formatShortDate(tx.occurred_at, timezone)}</span>
              <span className="wrap">{txName(tx)}</span>
              <HomeAmount tx={tx} />
            </li>
          ))}
        </ul>
      )}
      {page.data && total > 0 && (
        <Link className="link-btn peek-more" to={ledgerLink(pick)}>
          {total > items.length ? `See all ${total} in the ledger` : "Open in the ledger"}
        </Link>
      )}
    </div>
  );
}
