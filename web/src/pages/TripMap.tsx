import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { api, type Booking, type Hop, type LinkedPlace, type TravelMode, type TripDetail } from "../api";
import { type GMap, type GOverlay, loadMaps, type MapsApi, onMapsAuthFailure } from "../maps";
import { duration } from "./TripArrange";
import { sortKey, todayIso } from "./TripBits";
import { useLinkedPlaces } from "./TripPlaces";

/** Each day's colour on the map, repeating after eight days; places to visit with
 * no day are grey. Chosen to stay apart from each other and readable under white. */
export const DAY_COLORS = ["#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626", "#65a30d"];
export const NO_DAY = "#6b7280";

export type Pin = {
  id: string;
  title: string;
  lat: number;
  lng: number;
  /** The plan's number in its day (as on the itinerary), "H" for a hotel, "" for a
   * place to visit. */
  label: string;
  color: string;
  kind: "plan" | "hotel" | "place" | "station";
  /** The days it's on: a plan's day, every day of a hotel stay, none for a place, the
   * days an airport or station is left from or landed at. */
  days: string[];
  sort: string;
  /** Its place in a given day's route, where that differs by day (an airport). */
  sortOn?: Record<string, string>;
  /** The element on the itinerary a tap on the pin finds. */
  target?: string;
};

/** The colour of an airport or station pin. */
export const STATION = "#374151";

const DAY_MS = 86400000;
const isoDay = (t: number) => new Date(t).toISOString().slice(0, 10);

export function dayNumber(trip: { start: string }, iso: string): number {
  return Math.round((Date.parse(iso) - Date.parse(trip.start)) / DAY_MS) + 1;
}

export function dayColor(trip: { start: string }, iso: string | null): string {
  if (!iso) return NO_DAY;
  const n = dayNumber(trip, iso) - 1;
  return DAY_COLORS[((n % DAY_COLORS.length) + DAY_COLORS.length) % DAY_COLORS.length];
}

function stayDays(b: Booking): string[] {
  if (!b.check_in) return [];
  const days: string[] = [];
  const last = Date.parse(b.check_out ?? b.check_in);
  for (let t = Date.parse(b.check_in); t <= last && days.length < 120; t += DAY_MS) days.push(isoDay(t));
  return days;
}

/** The trip's places that Google Maps knows where to find, as map pins: plans numbered
 * as on their day of the itinerary, hotels, and places to visit. */
export function mapPins(detail: Pick<TripDetail, "trip" | "bookings" | "days">, linked: Map<string, LinkedPlace>): Pin[] {
  const numbers = new Map<string, number>();
  // Each entry's place in its day, as the itinerary shows it (by time without one).
  const place = new Map<string, string>();
  for (const d of detail.days ?? []) d.order.forEach((id, i) => place.set(id, `${d.day}#${String(i).padStart(3, "0")}`));
  const keyOf = (b: Booking) => place.get(b.id) ?? sortKey(b);
  const scheduled = detail.bookings.filter((b) => b.scheduled).sort((a, b) => keyOf(a).localeCompare(keyOf(b)));
  const counts = new Map<string, number>();
  for (const b of scheduled) {
    if (b.kind !== "activity") continue;
    const n = (counts.get(b.starts) ?? 0) + 1;
    counts.set(b.starts, n);
    numbers.set(b.id, n);
  }
  const pins: Pin[] = [];
  for (const b of detail.bookings) {
    const found = linked.get(b.id)?.place;
    if (!found || typeof found.lat !== "number" || typeof found.lng !== "number") continue;
    const base = { id: b.id, title: b.kind === "hotel" ? (b.hotel ?? b.title) : b.title, lat: found.lat, lng: found.lng, sort: keyOf(b) };
    if (b.kind === "hotel") {
      pins.push({ ...base, label: "H", color: dayColor(detail.trip, b.check_in), kind: "hotel", days: stayDays(b) });
    } else if (b.kind === "activity" && b.scheduled) {
      pins.push({ ...base, label: String(numbers.get(b.id) ?? ""), color: dayColor(detail.trip, b.starts), kind: "plan", days: [b.starts] });
    } else if (b.kind === "activity") {
      pins.push({ ...base, label: "", color: NO_DAY, kind: "place", days: [] });
    }
  }
  // Airports and stations: on the days they're left from or landed at, in the
  // flight's place in that day (landing after leaving, on a short flight).
  const byId = new Map(detail.bookings.map((b) => [b.id, b]));
  for (const l of linked.values()) {
    const b = byId.get(l.booking_id);
    if (!l.station || !b || typeof l.place.lat !== "number" || typeof l.place.lng !== "number") continue;
    const stops = l.stops ?? [];
    const sortOn = Object.fromEntries(stops.map((s) => [s.day, `${s.day}#${placeOn(detail, b.id, s.day)}${s.side === "to" ? "b" : "a"}`]));
    const landing = stops.find((s) => s.side === "to");
    pins.push({
      id: `${b.id}#${l.station}`,
      title: l.station,
      lat: l.place.lat,
      lng: l.place.lng,
      label: b.kind === "flight" ? "✈" : "🚆",
      color: STATION,
      kind: "station",
      days: stops.map((s) => s.day),
      sort: Object.values(sortOn)[0] ?? keyOf(b),
      sortOn,
      target: landing && landing.day !== b.starts ? `land-${b.id}` : `entry-${b.id}`,
    });
  }
  return pins;
}

/** A day's route on the map, in itinerary order: from last night's hotel, through the
 * day's plans (a hotel check-in at 15:00), to tonight's hotel. */
/** An entry's place in a day's order, padded to sort ("004"); "999" when not there. */
function placeOn(detail: Pick<TripDetail, "days">, id: string, day: string): string {
  const i = detail.days?.find((d) => d.day === day)?.order.indexOf(id) ?? -1;
  return String(i < 0 ? 999 : i).padStart(3, "0");
}

export function dayPath(pins: Pin[], day: string): Pin[] {
  const before = isoDay(Date.parse(day) - DAY_MS);
  const hotels = pins.filter((p) => p.kind === "hotel");
  const sleptIn = (p: Pin, night: string) => p.days.includes(night) && p.days.at(-1) !== night;
  const morning = hotels.find((p) => sleptIn(p, before));
  const tonight = hotels.find((p) => sleptIn(p, day));
  const at = (p: Pin) => p.sortOn?.[day] ?? p.sort;
  const stops = pins
    .filter((p) => ((p.kind === "plan" || p.kind === "hotel") && p.days[0] === day) || (p.kind === "station" && p.days.includes(day)))
    .sort((a, b) => at(a).localeCompare(at(b)));
  const path: Pin[] = [];
  for (const p of [morning, ...stops, tonight]) {
    if (p && path.at(-1)?.id !== p.id) path.push(p);
  }
  return path;
}

function tripDayList(trip: TripDetail["trip"]): string[] {
  const days: string[] = [];
  for (let t = Date.parse(trip.start); t <= Date.parse(trip.end) && days.length < 120; t += DAY_MS) days.push(isoDay(t));
  return days;
}

/** The trip on a Google map: every place it knows where to find, coloured by day,
 * with a day's route when one day is picked. Beside the itinerary on wide screens; a
 * card that opens full screen on phones. */
export function TripMap({ detail }: { detail: TripDetail }) {
  const linked = useLinkedPlaces();
  const pins = useMemo(() => mapPins(detail, linked), [detail, linked]);
  const days = useMemo(() => tripDayList(detail.trip), [detail.trip]);
  const today = todayIso();
  const [day, setDay] = useState<string>(detail.trip.status === "ongoing" && days.includes(today) ? today : "all");
  const [full, setFull] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [maps, setMaps] = useState<{ api: MapsApi; map: GMap } | null>(null);
  const element = useRef<HTMLDivElement>(null);
  const key = detail.map_key ?? null;
  const shown = day === "all" ? pins : pins.filter((p) => p.days.includes(day));

  useEffect(() => onMapsAuthFailure(() => setError("Google didn't accept the map's key.")), []);

  useEffect(() => {
    if (!key || pins.length === 0 || maps || !element.current) return;
    let live = true;
    loadMaps(key)
      .then((api) => {
        if (!live || !element.current) return;
        const map = new api.Map(element.current, {
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          clickableIcons: false,
          gestureHandling: "cooperative",
        });
        setMaps({ api, map });
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "The map couldn't load."));
    return () => {
      live = false;
    };
  }, [key, pins.length, maps]);

  useEffect(() => {
    if (!maps) return;
    const { api, map } = maps;
    const drawn: GOverlay[] = [];
    const bounds = new api.LatLngBounds();
    for (const p of shown) {
      const marker = new api.Marker({
        map,
        position: { lat: p.lat, lng: p.lng },
        title: p.title,
        label: p.label ? { text: p.label, color: "#ffffff", fontWeight: "600", fontSize: "12px" } : undefined,
        icon: { path: api.circle, scale: p.label ? 11 : 7, fillColor: p.color, fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2 },
      });
      marker.addListener("click", () => {
        const target = document.getElementById(p.target ?? `entry-${p.id}`);
        if (!target) return;
        setFull(false);
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.add("entry-flash");
        window.setTimeout(() => target.classList.remove("entry-flash"), 1600);
      });
      drawn.push(marker);
      bounds.extend({ lat: p.lat, lng: p.lng });
    }
    if (day !== "all") {
      const path = dayPath(pins, day);
      if (path.length > 1) {
        drawn.push(
          new api.Polyline({
            map,
            path: path.map((p) => ({ lat: p.lat, lng: p.lng })),
            strokeColor: dayColor(detail.trip, day),
            strokeOpacity: 0.8,
            strokeWeight: 3,
          }),
        );
      }
    }
    if (shown.length === 1) {
      map.setCenter({ lat: shown[0].lat, lng: shown[0].lng });
      map.setZoom(15);
    } else if (shown.length > 1) {
      map.fitBounds(bounds, 48);
    }
    return () => drawn.forEach((o) => o.setMap(null));
  }, [maps, shown, pins, day, detail.trip]);

  if (!key) return null;
  const label = (iso: string) => `Day ${dayNumber(detail.trip, iso)}`;
  return (
    <section className={`card trip-map${full ? " trip-map-full" : ""}`} aria-labelledby="trip-map-title">
      <div className="card-head">
        <h2 id="trip-map-title">Map</h2>
        {pins.length > 0 && (
          <button type="button" className="btn btn-ghost btn-small trip-map-toggle" onClick={() => setFull(!full)} aria-pressed={full}>
            {full ? "Close map" : "Full screen"}
          </button>
        )}
      </div>
      {pins.length === 0 ? (
        <p className="caption">Places linked to Google Maps show here, coloured by day.</p>
      ) : (
        <>
          <nav className="day-strip trip-map-days" aria-label="Days on the map">
            <button type="button" className="day-pill" aria-pressed={day === "all"} onClick={() => setDay("all")}>
              All
            </button>
            {days.map((d) => (
              <button
                key={d}
                type="button"
                className="day-pill"
                aria-pressed={day === d}
                onClick={() => setDay(d)}
                style={{ borderColor: dayColor(detail.trip, d) }}
              >
                {label(d)}
              </button>
            ))}
          </nav>
          {error ? (
            <p className="error-text" role="alert">
              {error}
            </p>
          ) : (
            <div ref={element} className="trip-map-canvas" role="img" aria-label={`Map of ${detail.trip.destination}${day === "all" ? "" : `, ${label(day)}`}`} />
          )}
          <ul className="sr-only" aria-label="On the map">
            {shown.map((p) => (
              <li key={p.id}>
                {p.label && p.label !== "H" ? `${p.label}. ` : ""}
                {p.title}
                {p.kind === "hotel" ? " (stay)" : p.kind === "place" ? " (place to visit)" : p.kind === "station" ? " (airport or station)" : ""}
              </li>
            ))}
          </ul>
          {day !== "all" && shown.length === 0 && <p className="caption">Nothing on the map that day.</p>}
        </>
      )}
    </section>
  );
}

// --- travel times between stops on the itinerary ---------------------------------------

const MODE: Record<TravelMode, { icon: string; words: string }> = {
  walk: { icon: "🚶", words: "walk" },
  transit: { icon: "🚆", words: "by public transport" },
  drive: { icon: "🚗", words: "drive" },
};

export function distance(metres: number): string {
  return metres < 1000 ? `${Math.round(metres / 10) * 10} m` : `${(metres / 1000).toFixed(1)} km`;
}

/** Calls ``children`` with the day's travel times, asked for only once the day is
 * near the screen (each one is a call to Google). */
export function DayHops({ tripId, day, enabled, soon, children }: {
  tripId: string;
  day: string;
  enabled: boolean;
  /** Ask now, without waiting to scroll near: a day next to the one in view. */
  soon?: boolean;
  children: (hops: Hop[]) => ReactNode;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [seen, setNear] = useState(false);
  const near = seen || Boolean(soon);
  useEffect(() => {
    if (!enabled || near || !holder.current) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const watch = new IntersectionObserver((seen) => seen.some((s) => s.isIntersecting) && setNear(true), { rootMargin: "300px" });
    watch.observe(holder.current);
    return () => watch.disconnect();
  }, [enabled, near]);
  const hops = useQuery({
    queryKey: ["trip-hops", tripId, day],
    queryFn: () => api<Hop[]>(`/travel/trips/${tripId}/days/${day}/hops`),
    enabled: enabled && near,
    staleTime: 10 * 60 * 1000,
  });
  return <div ref={holder}>{children(hops.data ?? [])}</div>;
}

/** The maps app directions open in, kept on this device. */
export type MapApp = "google" | "apple" | "waze";
export const MAP_APPS: { app: MapApp; name: string }[] = [
  { app: "google", name: "Google Maps" },
  { app: "apple", name: "Apple Maps" },
  { app: "waze", name: "Waze" },
];
const MAP_APP_KEY = "nexus.map-app";
const watchers = new Set<() => void>();
let chosen: MapApp | null = null;

function storedApp(): MapApp {
  try {
    const app = window.localStorage.getItem(MAP_APP_KEY);
    return app === "apple" || app === "waze" ? app : "google";
  } catch {
    return "google";
  }
}

export function useMapApp(): [MapApp, (app: MapApp) => void] {
  const app = useSyncExternalStore(
    (changed) => {
      watchers.add(changed);
      return () => watchers.delete(changed);
    },
    () => (chosen ??= storedApp()),
    () => "google" as MapApp,
  );
  const choose = (next: MapApp) => {
    chosen = next;
    try {
      window.localStorage.setItem(MAP_APP_KEY, next);
    } catch {
      // Still used for this visit.
    }
    watchers.forEach((w) => w());
  };
  return [app, choose];
}

const APPLE_MODE: Record<TravelMode, string> = { walk: "w", transit: "r", drive: "d" };

/** Directions in the chosen app. Google's link comes from the server, with Google's
 * place ids; Apple Maps and Waze get only the entries' names and addresses as saved on
 * the trip, never coordinates or place ids. */
export function directionsIn(app: MapApp, hop: Pick<Hop, "start" | "end" | "mode" | "directions">, start: string | null, end: string | null): string {
  const from = start ? `${hop.start}, ${start}` : hop.start;
  const to = end ? `${hop.end}, ${end}` : hop.end;
  if (app === "apple") return `https://maps.apple.com/?${new URLSearchParams({ saddr: from, daddr: to, dirflg: APPLE_MODE[hop.mode] })}`;
  if (app === "waze") return `https://waze.com/ul?${new URLSearchParams({ q: to, navigate: "yes" })}`;
  return hop.directions;
}

/** Which app directions open in. */
export function MapAppPicker() {
  const [app, choose] = useMapApp();
  return (
    <label className="caption map-app">
      Directions open in{" "}
      <select value={app} onChange={(e) => choose(e.target.value as MapApp)}>
        {MAP_APPS.map((m) => (
          <option key={m.app} value={m.app}>
            {m.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Getting from one stop to the next, between their cards: how, how long, and a
 * way to change it for that hop. */
export function HopLine({ tripId, day, hop, addressOf, back }: {
  tripId: string;
  day: string;
  hop: Hop;
  addressOf?: (id: string) => string | null;
  /** Back to somewhere already on the day's list, like tonight's hotel: named. */
  back?: boolean;
}) {
  const [app] = useMapApp();
  const [shown, setShown] = useState<Hop>(hop);
  const [busy, setBusy] = useState(false);
  useEffect(() => setShown(hop), [hop]);
  async function change(mode: TravelMode) {
    setBusy(true);
    try {
      setShown(await api<Hop>(`/travel/trips/${tripId}/days/${day}/hops/${hop.start_id}/${hop.end_id}?mode=${mode}`));
    } catch {
      // Leave the time as it was.
    } finally {
      setBusy(false);
    }
  }
  const how = MODE[shown.mode];
  const time = shown.minutes === null ? `No ${how.words === "walk" ? "walking" : how.words} route` : `${duration(shown.minutes)} ${how.words}`;
  return (
    <li className="timeline-hop" aria-label={`From ${shown.start} to ${shown.end}`}>
      <span aria-hidden="true">{how.icon}</span>
      <span className="wrap">
        {back && <span className="hop-back">Back to {shown.end} · </span>}
        {time}
        {shown.metres !== null && shown.minutes !== null && <span className="caption"> · {distance(shown.metres)}</span>}
        {shown.tight && (
          <span className="badge badge-pending" title="Takes longer than the time between the two plans">
            Tight
          </span>
        )}
      </span>
      <select aria-label={`How to get to ${shown.end}`} value={shown.mode} disabled={busy} onChange={(e) => void change(e.target.value as TravelMode)}>
        <option value="walk">Walk</option>
        <option value="transit">Transit</option>
        <option value="drive">Drive</option>
      </select>
      <a href={directionsIn(app, shown, addressOf?.(shown.start_id) ?? null, addressOf?.(shown.end_id) ?? null)} target="_blank" rel="noopener noreferrer" className="caption">
        Directions
      </a>
    </li>
  );
}
