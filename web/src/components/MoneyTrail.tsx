import { api, type Transaction } from "../api";
import { formatDate, formatMoney } from "../format";

/** How money moved around a transaction: who shared a bill and who has paid back,
 * or which bill a repayment paid. Each link opens the transaction on the other side. */
export function MoneyTrail({
  tx,
  timezone,
  onOpen,
}: {
  tx: Transaction;
  timezone: string;
  onOpen: (tx: Transaction) => void;
}) {
  const links = tx.links ?? [];
  if (!tx.split && links.length === 0) return null;

  async function open(id: string) {
    onOpen(await api<Transaction>(`/transactions/${id}`));
  }

  function link(id: string, text: string, label: string) {
    return (
      <button
        type="button"
        className="btn btn-ghost trail-link"
        aria-label={label}
        onClick={(e) => {
          e.stopPropagation();
          void open(id);
        }}
      >
        {text}
      </button>
    );
  }

  if (tx.direction === "in") {
    return (
      <div className="trail caption">
        {links.map((l) => (
          <div key={l.transaction_id + l.amount.amount}>
            {link(
              l.transaction_id,
              `↩ Paid back for ${l.counterparty ?? "a bill"} · ${formatDate(l.occurred_at, timezone)}`,
              `Open the bill ${l.name} paid back: ${l.counterparty ?? "a bill"}`,
            )}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="trail caption">
      {tx.split && <div>Split · your share {formatMoney(tx.split.own_share)}</div>}
      {tx.split?.people.map((p) => {
        const owed = Number(p.share.amount) - Number(p.repaid.amount);
        const paid = links.filter((l) => l.name === p.name);
        if (owed <= 0 && paid.length > 0) {
          return (
            <div key={p.name} className="trail-settled">
              {link(
                paid[paid.length - 1].transaction_id,
                `${p.name} paid back ${formatMoney(p.share)} ✓`,
                `Open ${p.name}'s repayment`,
              )}
            </div>
          );
        }
        const left = formatMoney({ amount: String(owed), currency: p.share.currency });
        return (
          <div key={p.name} className="trail-owed">
            {p.name} owes {left}
            {paid.length > 0 && (
              <>
                {" · "}
                {link(
                  paid[paid.length - 1].transaction_id,
                  `paid ${formatMoney(p.repaid)} so far`,
                  `Open ${p.name}'s repayment`,
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
