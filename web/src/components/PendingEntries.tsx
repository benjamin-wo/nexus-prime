import { useQueryClient } from "@tanstack/react-query";

import { formatDate, formatMoney } from "../format";
import { discard, type OutboxEntry, retryEntry } from "../outbox";
import { Button, Row, RowList } from "./ui";

/** The text of an entry's own fields, as the entry sheet sent them. */
function field(entry: OutboxEntry, name: string): string | null {
  const value = entry.body[name];
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * Expenses saved on this phone and not recorded yet, for the top of the Ledger: each with a "Will sync" word.
 * One the server refused shows its reason with "Try again" and "Discard".
 */
export function PendingEntries({ user, entries }: { user: string; entries: readonly OutboxEntry[] }) {
  const client = useQueryClient();
  if (entries.length === 0) return null;
  return (
    <RowList className="outbox" aria-label="Saved on this phone, waiting to sync">
      {entries.map((entry) => {
        const money = field(entry, "amount") && { amount: field(entry, "amount") ?? "", currency: field(entry, "currency") ?? "" };
        const out = entry.body.direction !== "in";
        const date = field(entry, "date");
        const name = field(entry, "counterparty") ?? (out ? "No merchant" : "Income");
        return (
          <Row
            key={entry.key}
            title={
              <>
                {name} <span className="badge badge-pending">{entry.failed === undefined ? "Will sync" : "Couldn't sync"}</span>
              </>
            }
            sub={
              <>
                Saved on this phone{date ? ` · ${formatDate(`${date}T12:00:00`)}` : ""}
                {entry.failed !== undefined && <span className="outbox-failed">{entry.failed}</span>}
              </>
            }
            trailing={
              money && (
                <>
                  {out ? "−" : "+"}
                  {formatMoney(money)}
                </>
              )
            }
            actions={
              <>
                {entry.failed !== undefined && (
                  <Button variant="text" size="sm" onClick={() => void retryEntry(user, entry.key, client)}>
                    Try again
                  </Button>
                )}
                <Button variant="text" size="sm" onClick={() => discard(user, entry.key)}>
                  Discard
                </Button>
              </>
            }
          />
        );
      })}
    </RowList>
  );
}
