import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api, type EmailOverview, goHomeTimezone, type Me, setTimezone, type TripAlerts, type Updates, type Wallet } from "../api";
import { BackLink } from "../components/BackLink";
import { Icon } from "../components/Icon";
import { describeZone, filterZones, friendlyZone, sourceNote, zoneChoices } from "../timezone";
import { CategoriesSection } from "./Categories";
import { MemorySection } from "./Memory";
import { RulesSection } from "./Rules";
import { UpdatesSection } from "./Updates";
import { VoiceCard } from "./Voice";
import { WalletsSection } from "./Wallets";
import { YourDataSection } from "./YourData";

/** Whether Kaya messages the user on Telegram when someone else changes a trip they
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

/** The zone Kaya counts "today" in. It follows the phone; this is where to see why, pick another or go back home. */
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
        <span className="caption">Where Kaya counts your day</span>
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
              onClick={() => void run(() => setTimezone(choice, "manual"), `Saved. Kaya now uses ${friendlyZone(choice)} time.`)}
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

/** One page of Settings: its address, its name on the list, and what it shows. */
type Section = {
  slug: string;
  title: string;
  group: "Notifications" | "Connections" | "Your data";
  /** Not for a demo account. */
  notDemo?: boolean;
  ownerOnly?: boolean;
  /** What the page shows. Receipts by email, Import, Notifications and Model costs were pages already,
   * with routes of their own, so they have none here. */
  render?: (me: Me) => ReactNode;
};

const SECTIONS: Section[] = [
  { slug: "updates", title: "Telegram updates", group: "Notifications", render: () => <UpdatesSection /> },
  { slug: "time-zone", title: "Time zone", group: "Notifications", render: (me) => <TimeZoneSection me={me} /> },
  { slug: "shared-trips", title: "Shared trips", group: "Notifications", notDemo: true, render: () => <TripAlertsSection /> },
  { slug: "notifications", title: "Notifications", group: "Notifications" },
  { slug: "voice", title: "How Kaya talks", group: "Notifications", render: () => <VoiceCard /> },
  { slug: "email", title: "Receipts by email", group: "Connections", notDemo: true },
  { slug: "import", title: "Import a statement", group: "Connections" },
  { slug: "categories", title: "Categories", group: "Your data", render: () => <CategoriesSection /> },
  { slug: "wallets", title: "Wallets", group: "Your data", render: (me) => <WalletsSection me={me} /> },
  { slug: "rules", title: "Category rules", group: "Your data", render: () => <RulesSection /> },
  { slug: "memory", title: "What Kaya remembers", group: "Your data", render: () => <MemorySection /> },
  { slug: "data", title: "Download or delete", group: "Your data", render: () => <YourDataSection /> },
  { slug: "costs", title: "Model costs", group: "Your data", ownerOnly: true },
];
const GROUPS = ["Notifications", "Connections", "Your data"] as const;

/** What this person gets: no email or shared trips on the demo, no costs but for the owner. */
function sectionsFor(me: Me): Section[] {
  return SECTIONS.filter((s) => !(s.notDemo && me.demo) && !(s.ownerOnly && me.user.role !== "owner"));
}

/** "9pm" or "9:30am" from "21:00". */
function clock(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  return `${h % 12 || 12}${m ? `:${String(m).padStart(2, "0")}` : ""}${h < 12 ? "am" : "pm"}`;
}

function updatesSummary(updates: Updates): string {
  if (updates.frequency === "daily") return `Daily at ${clock(updates.daily_at)}`;
  const words = updates.options[updates.frequency];
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

function emailSummary(overview: EmailOverview): string {
  if (overview.connections.length === 0) return "Not connected";
  const waiting = overview.emails.filter((e) => e.status === "pending").length;
  const more = overview.connections.length > 1 ? ` +${overview.connections.length - 1}` : "";
  return `${overview.connections[0].address}${more}${waiting > 0 ? ` · ${waiting} waiting` : ""}`;
}

/** A one-line current value for the rows that can show one cheaply. These read the same queries the
 * pages use, so opening a page afterwards is already warm; a row with nothing cheap to say stays bare. */
function useSummaries(me: Me): Record<string, string | undefined> {
  const updates = useQuery({ queryKey: ["notifications"], queryFn: () => api<Updates>("/notifications") });
  const wallets = useQuery({ queryKey: ["wallets"], queryFn: () => api<Wallet[]>("/wallets") });
  const alerts = useQuery({ queryKey: ["trip-alerts"], queryFn: () => api<TripAlerts>("/trip-alerts"), enabled: !me.demo });
  const email = useQuery({ queryKey: ["email"], queryFn: () => api<EmailOverview>("/email"), enabled: !me.demo });
  const count = wallets.data?.length;
  return {
    updates: updates.data ? updatesSummary(updates.data) : undefined,
    "time-zone": describeZone(me.user.timezone),
    "shared-trips": alerts.data ? (alerts.data.enabled ? "On" : "Off") : undefined,
    email: email.data ? emailSummary(email.data) : undefined,
    wallets: count === undefined ? undefined : `${count} ${count === 1 ? "wallet" : "wallets"}`,
  };
}

type Preferences = NonNullable<Me["preferences"]>;
type PreferenceKey = keyof Preferences;

/** A switch for one preference that saves when flipped: the screen follows at once, and goes back with
 * the reason if the save fails. Not decided (null or absent) reads as off. The answer is the full
 * preferences, kept in the cached /me so the rest of the app (the menu, Home) follows. */
function PreferenceSwitch({ me, field, title, hint }: { me: Me; field: PreferenceKey; title: string; hint: string }) {
  const client = useQueryClient();
  const saved = me.preferences?.[field] === true;
  const [on, setOn] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = useId();
  // Follow /me when it moves (another tab, or this save landing).
  useEffect(() => setOn(saved), [saved]);

  async function change(next: boolean) {
    const before = on;
    setOn(next);
    setBusy(true);
    setError(null);
    try {
      const result = await api<Partial<Preferences>>("/settings/preferences", { method: "PUT", body: { [field]: next } });
      setOn(result[field] === true);
      client.setQueryData<Me | null | undefined>(["me"], (old) =>
        old ? { ...old, preferences: { ...old.preferences, ...result } as Preferences } : old,
      );
      void client.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      setOn(before);
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <label className="set-row set-switch-row">
        <span className="set-text">
          <span className="set-row-title" id={`${id}-name`}>
            {title}
          </span>
          <span className="caption" id={`${id}-hint`}>
            {hint}
          </span>
        </span>
        <input
          className="switch"
          type="checkbox"
          role="switch"
          checked={on}
          disabled={busy}
          aria-labelledby={`${id}-name`}
          aria-describedby={`${id}-hint`}
          onChange={(e) => void change(e.target.checked)}
        />
      </label>
      {error && (
        <p className="error-text set-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/** Settings: a short list. A switch for how logging works, then a row for each place to go, grouped
 * as Notifications, Connections and Your data. Each row opens its own page at /settings/<slug>. */
export function Settings({ me }: { me: Me }) {
  const summaries = useSummaries(me);
  const sections = sectionsFor(me);
  return (
    <div className="set-page">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Your preferences and connections.</p>
        </div>
      </div>
      <section className="set-group" aria-labelledby="set-preferences">
        <h2 className="section-title" id="set-preferences">
          Preferences
        </h2>
        <div className="set-list">
          <PreferenceSwitch
            me={me}
            field="track_cards"
            title="Track which card paid"
            hint="Off keeps logging simple. On adds a Paid with field to expenses."
          />
          <PreferenceSwitch me={me} field="show_invest" title="Investing" hint="Portfolio, watchlist and trade plans in the menu" />
          <PreferenceSwitch me={me} field="show_travel" title="Travel" hint="Trips and trip research in the menu" />
        </div>
      </section>
      {GROUPS.map((group) => {
        const id = `set-${group.replace(/\s/g, "-")}`;
        return (
          <section className="set-group" key={group} aria-labelledby={id}>
            <h2 className="section-title" id={id}>
              {group}
            </h2>
            <ul className="set-list">
              {sections
                .filter((s) => s.group === group)
                .map((s) => (
                  <li key={s.slug}>
                    <Link className="set-row" to={`/settings/${s.slug}`}>
                      <span className="set-row-title">{s.title}</span>
                      {summaries[s.slug] && <span className="set-row-value">{summaries[s.slug]}</span>}
                      <Icon name="chevron" size={18} />
                    </Link>
                  </li>
                ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** One section of Settings on its own page, at /settings/<slug>, with the way back. An address that
 * isn't one (or is not for this person) goes back to the list. */
export function SettingsSection({ me }: { me: Me }) {
  const { slug } = useParams();
  const section = sectionsFor(me).find((s) => s.slug === slug);
  if (!section?.render) return <Navigate to="/settings" replace />;
  return (
    <div className="set-page">
      <div className="page-head">
        <div>
          <BackLink to="/settings">Back to Settings</BackLink>
          <h1>{section.title}</h1>
        </div>
      </div>
      {section.render(me)}
    </div>
  );
}
