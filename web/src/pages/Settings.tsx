import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type TripAlerts } from "../api";
import { CategoriesSection } from "./Categories";
import { EmailCard } from "./Email";
import { MemorySection } from "./Memory";
import { RulesSection } from "./Rules";
import { UpdatesSection } from "./Updates";
import { WalletsSection } from "./Wallets";

/** Whether Nexus messages the user on Telegram when someone else changes a trip they
 * share (at most one message per trip every 30 minutes). */
function TripAlertsSection() {
  const client = useQueryClient();
  const alerts = useQuery({ queryKey: ["trip-alerts"], queryFn: () => api<TripAlerts>("/trip-alerts") });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change(enabled: boolean) {
    setBusy(true);
    setError(null);
    try {
      client.setQueryData(["trip-alerts"], await api<TripAlerts>("/trip-alerts", { method: "PUT", body: { enabled } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="trip-alerts">
      <div className="card-head">
        <h2 id="trip-alerts">Shared trips</h2>
        <span className="caption">Telegram</span>
      </div>
      {alerts.isLoading && <p className="state">Loading…</p>}
      {alerts.isError && <p className="state error-text">Couldn't load your shared trips setting.</p>}
      {alerts.data && (
        <>
          <label className="share-switch">
            <input
              type="checkbox"
              role="switch"
              checked={alerts.data.enabled}
              disabled={busy}
              onChange={(e) => void change(e.target.checked)}
              aria-describedby="trip-alerts-hint"
            />
            <span>Tell me when someone changes a trip I share</span>
          </label>
          <p id="trip-alerts-hint" className="caption">
            One message per trip, at most every 30 minutes, listing what changed. Your own changes never send one.
          </p>
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** Account-wide settings, then each department's own. */
export function Settings() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">How Nexus works for you, then each department's own settings.</p>
        </div>
      </div>
      <h2 className="section-title">Account</h2>
      <div className="plan-grid">
        <UpdatesSection />
        <MemorySection />
      </div>
      <h2 className="section-title">Travel</h2>
      <div className="plan-grid">
        <TripAlertsSection />
      </div>
      <h2 className="section-title">Accounting</h2>
      <div className="plan-grid">
        <EmailCard />
        <CategoriesSection />
        <WalletsSection />
        <RulesSection />
      </div>
    </>
  );
}
