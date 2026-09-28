import type { Transaction } from "../api";
import { formatDate, formatMoney, formatShortDate } from "../format";

/**
 * A ledger amount. Foreign rows lead with the home-currency equivalent and keep
 * the original amount and the rate used (with the day it was published) below.
 */
export function Amount({ tx }: { tx: Transaction }) {
  const sign = tx.direction === "out" ? "−" : "+";
  const home = tx.home;
  if (!home) {
    return (
      <>
        {sign}
        {formatMoney(tx.amount)}
      </>
    );
  }
  if (!home.amount || !home.rate || !home.rate_date) {
    return (
      <>
        {sign}
        {formatMoney(tx.amount)}
        <span className="caption fx">No rate available to convert</span>
      </>
    );
  }
  return (
    <>
      <span className="sr-only">About </span>
      <span aria-hidden="true">≈ </span>
      {sign}
      {formatMoney(home.amount)}
      <span
        className="caption fx"
        title={`${formatMoney(tx.amount)} at ${home.rate}, rate of ${formatDate(home.rate_date, "UTC")}`}
      >
        {formatMoney(tx.amount)}
        <br />
        at {home.rate} · {formatShortDate(home.rate_date, "UTC")}
      </span>
    </>
  );
}
