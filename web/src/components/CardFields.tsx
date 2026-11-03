import { useState } from "react";

import type { CardNetwork } from "../api";
import { type CardDetails, keepLast4, LAST4_NOTE, NETWORKS } from "../wallets";

/** The card's own fields: bank, card, network and the last four digits. Shared by the
 * Wallets page and the entry sheet's "Add a card". */
export function CardFields({ value, onChange }: { value: CardDetails; onChange: (next: CardDetails) => void }) {
  const [trimmed, setTrimmed] = useState(false);
  return (
    <>
      <label className="field">
        Bank
        <input className="input" placeholder="Citi" value={value.issuer} onChange={(e) => onChange({ ...value, issuer: e.target.value })} />
      </label>
      <label className="field">
        Card
        <input className="input" placeholder="PremierMiles" value={value.product} onChange={(e) => onChange({ ...value, product: e.target.value })} />
      </label>
      <label className="field">
        Network
        <select className="input" value={value.network} onChange={(e) => onChange({ ...value, network: e.target.value as CardNetwork | "" })}>
          <option value="">Not set</option>
          {NETWORKS.map((n) => (
            <option key={n.key} value={n.key}>
              {n.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        Last 4 digits
        <input
          className="input num"
          inputMode="numeric"
          autoComplete="off"
          placeholder="4321"
          pattern="[0-9]{4}"
          title="The last 4 digits of the card"
          value={value.last4}
          onChange={(e) => {
            const kept = keepLast4(e.target.value);
            setTrimmed(kept.trimmed);
            onChange({ ...value, last4: kept.value });
          }}
        />
      </label>
      {trimmed && (
        <p className="caption wallet-note" role="status">
          {LAST4_NOTE}
        </p>
      )}
    </>
  );
}
