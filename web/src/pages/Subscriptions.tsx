import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Subscription, type Subscriptions } from "../api";
import { formatMoney } from "../format";

const PER = { weekly: "week", monthly: "month", yearly: "year" } as const;

function day(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(iso),
  );
}

function SubscriptionRow({
  sub,
  proposed,
  onChanged,
}: {
  sub: Subscription;
  proposed: boolean;
  onChanged: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "track" | "dismiss") {
    setError(null);
    try {
      await api(`/subscriptions/${sub.id}/${action}`, { method: "POST", body: {} });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't do that");
    }
  }

  return (
    <li className="budget">
      <div className="budget-head">
        <h3 className="wrap">{sub.name}</h3>
        <span className="num">
          {formatMoney(sub.amount)} / {PER[sub.cadence]}
        </span>
      </div>
      {sub.previous_amount && sub.price_changed_on && (
        <p className="caption">
          Was {formatMoney(sub.previous_amount)} until {day(sub.price_changed_on)}
        </p>
      )}
      <div className="budget-foot">
        <span className="caption">
          {proposed ? `Last charged ${day(sub.last_charged_on)}` : `Next about ${day(sub.next_charge)}`}
        </span>
        {proposed ? (
          <span className="quick">
            <button type="button" className="btn btn-primary" onClick={() => act("track")}>
              Track it
            </button>
            <button type="button" className="btn" onClick={() => act("dismiss")}>
              No
            </button>
          </span>
        ) : confirming ? (
          <span className="quick">
            <span>Stop tracking?</span>
            <button type="button" className="btn btn-danger" onClick={() => act("dismiss")}>
              Stop
            </button>
            <button type="button" className="btn" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </span>
        ) : (
          <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
            Stop tracking
          </button>
        )}
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** Recurring payments Nexus spotted in the ledger; tracked only once the user agrees. */
export function SubscriptionsSection() {
  const client = useQueryClient();
  const subs = useQuery({ queryKey: ["subscriptions"], queryFn: () => api<Subscriptions>("/subscriptions") });

  function refresh() {
    void client.invalidateQueries({ queryKey: ["subscriptions"] });
  }

  const data = subs.data;
  const total = data?.monthly_totals.map(formatMoney).join(" + ");
  return (
    <section className="card" aria-labelledby="subscriptions">
      <div className="card-head">
        <h2 id="subscriptions">Subscriptions</h2>
        {total && <span className="caption">About {total} a month</span>}
      </div>
      {subs.isLoading && <p className="state">Loading…</p>}
      {subs.isError && <p className="state error-text">Couldn't load subscriptions.</p>}
      {data && data.proposed.length > 0 && (
        <>
          <h3 className="caption">Looks recurring. Track it?</h3>
          <ul className="budgets" aria-label="Proposed subscriptions">
            {data.proposed.map((s) => (
              <SubscriptionRow key={s.id} sub={s} proposed onChanged={refresh} />
            ))}
          </ul>
        </>
      )}
      {data && data.tracked.length > 0 && (
        <ul className="budgets" aria-label="Tracked subscriptions">
          {data.tracked.map((s) => (
            <SubscriptionRow key={s.id} sub={s} proposed={false} onChanged={refresh} />
          ))}
        </ul>
      )}
      {data && data.tracked.length === 0 && data.proposed.length === 0 && (
        <p className="state">
          None yet. When the same merchant charges a similar amount on a regular schedule three times in a row,
          I'll offer to track it.
        </p>
      )}
    </section>
  );
}
