import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, goHomeTimezone, type Me, setTimezone, type TripAlerts } from "../api";
import { describeZone, filterZones, friendlyZone, sourceNote, zoneChoices } from "../timezone";
import { CategoriesSection } from "./Categories";
import { EmailCard } from "./Email";
import { ImportCard } from "./Import";
import { MemorySection } from "./Memory";
import { NotificationsCard } from "./Notifications";
import { RulesSection } from "./Rules";
import { UpdatesSection } from "./Updates";
import { WalletsSection } from "./Wallets";
import { YourDataSection } from "./YourData";

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

/** The zone Nexus counts "today" in. It follows the phone; this is where to see why, pick another or go back home. */
export function TimeZoneSection({ me }: { me: Me }) {
  const client = useQueryClient();
  const user = me.user;
  const home = user.home_timezone || user.timezone;
  const [picking, setPicking] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const zones = useMemo(() => zoneChoices([user.timezone, home]), [user.timezone, home]);
  const shown = filterZones(zones, query);
  const choice = shown.includes(picked) ? picked : (shown[0] ?? "");

  async function run(send: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await send();
      // Everything keyed on today follows the zone.
      await client.invalidateQueries({ queryKey: ["me"] });
      for (const key of ["home", "investments", "summary", "transactions"]) void client.invalidateQueries({ queryKey: [key] });
      setPicking(false);
      setQuery("");
      setDone(message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="time-zone">
      <div className="card-head">
        <h2 id="time-zone">Time zone</h2>
        <span className="caption">Where Nexus counts your day</span>
      </div>
      <div className="setting tz-now">
        <p>
          <strong data-testid="time-zone-now">{describeZone(user.timezone)}</strong>
        </p>
        <p className="caption">{sourceNote(user.timezone_source)}</p>
        {user.timezone !== home && <p className="caption">Home: {friendlyZone(home)}</p>}
      </div>
      {!picking && (
        <div className="actions tz-actions">
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setPicking(true)}>
            Change
          </button>
          {user.timezone !== home && (
            <button
              type="button"
              className="btn btn-small btn-soft"
              disabled={busy}
              onClick={() => void run(goHomeTimezone, `Back on home time, ${friendlyZone(home)}.`)}
            >
              Use home time
            </button>
          )}
        </div>
      )}
      {picking && (
        <div className="tz-picker">
          <label className="field">
            Find a time zone
            <input
              className="input"
              type="search"
              value={query}
              placeholder="City or region"
              autoComplete="off"
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label className="field">
            Time zone
            <select className="input" size={6} value={choice} onChange={(e) => setPicked(e.target.value)}>
              {shown.map((zone) => (
                <option key={zone} value={zone}>
                  {describeZone(zone)} ({zone})
                </option>
              ))}
            </select>
          </label>
          {shown.length === 0 && <p className="caption">No time zone matches “{query.trim()}”.</p>}
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary btn-small"
              disabled={busy || !choice}
              onClick={() => void run(() => setTimezone(choice, "manual"), `Saved. Nexus now uses ${friendlyZone(choice)} time.`)}
            >
              Save
            </button>
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => setPicking(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {done && (
        <p className="caption" role="status">
          {done}
        </p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** Settings in three groups: how Nexus reaches you, what it connects to, and your data. */
export function Settings({ me }: { me: Me }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">How Nexus reaches you, what it connects to, and the data it keeps for you.</p>
        </div>
      </div>
      <h2 className="section-title">Notifications</h2>
      <div className="plan-grid">
        <UpdatesSection />
        <TimeZoneSection me={me} />
        <TripAlertsSection />
        <NotificationsCard />
      </div>
      <h2 className="section-title">Connections</h2>
      <div className="plan-grid">
        <EmailCard />
        <ImportCard />
      </div>
      <h2 className="section-title">Your data</h2>
      <div className="plan-grid">
        <CategoriesSection />
        <WalletsSection />
        <RulesSection />
        <MemorySection />
        <YourDataSection />
      </div>
    </>
  );
}
