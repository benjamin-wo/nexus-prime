import { useQueryClient } from "@tanstack/react-query";

import { formatDate, formatMoney } from "../format";
import { discard, type OutboxEntry, retryEntry } from "../outbox";

/** The text of an entry's own fields, as the entry sheet sent them. */
function field(entry: OutboxEntry, name: string): string | null {
  const value = entry.body[name];
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * Expenses saved on this phone and not recorded yet, for the top of the Ledger: each with a "Will sync" chip.
 * One the server refused shows its reason with "Try again" and "Discard".
 */
export function PendingEntries({ user, entries }: { user: string; entries: readonly OutboxEntry[] }) {
  const client = useQueryClient();
  if (entries.length === 0) return null;
  return (
    <ul className="outbox" aria-label="Saved on this phone, waiting to sync">
      {entries.map((entry) => {
        const money = field(entry, "amount") && { amount: field(entry, "amount") ?? "", currency: field(entry, "currency") ?? "" };
        const out = entry.body.direction !== "in";
        const date = field(entry, "date");
        const name = field(entry, "counterparty") ?? (out ? "No merchant" : "Income");
        return (
          <li key={entry.key} className="outbox-row">
            <div className="outbox-main">
              <span className="outbox-name">
                {name}
                <span className="badge badge-pending">{entry.failed === undefined ? "Will sync" : "Couldn't sync"}</span>
              </span>
              {money && (
                <span className="outbox-amount">
                  {out ? "−" : "+"}
                  {formatMoney(money)}
                </span>
              )}
            </div>
            <p className="caption">
              Saved on this phone{date ? ` · ${formatDate(`${date}T12:00:00`)}` : ""}
            </p>
            {entry.failed !== undefined && <p className="outbox-failed">{entry.failed}</p>}
            <div className="outbox-actions">
              {entry.failed !== undefined && (
                <button type="button" className="btn btn-small" onClick={() => void retryEntry(user, entry.key, client)}>
                  Try again
                </button>
              )}
              <button type="button" className="btn btn-small" onClick={() => discard(user, entry.key)}>
                Discard
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
