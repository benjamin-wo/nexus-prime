import { type FormEvent, useEffect, useRef, useState } from "react";

import type { Booking, TripDetail, TripStop } from "../api";
import { type Point, metresBetween } from "../geo";
import { type GMap, type GOverlay, loadMaps, type MapsApi, onMapsAuthFailure } from "../maps";
import { type Nearby, pointOf } from "./TripArrange";
import { stopColor, stopOfDay } from "./TripBits";
import { dayColor, dayNumber } from "./TripMap";

/** How long a finger or button is held on the map before a pin is dropped. */
export const LONG_PRESS_MS = 550;
/** What a dropped pin is called until the user says. */
export const DROPPED_PIN = "Dropped pin";

const stopKey = (s: TripStop) => `${s.name}|${s.start}`;

/** A small question after a long press: what to call the pin. */
function PinPrompt({ onSave, onClose }: { onSave: (name: string) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState(DROPPED_PIN);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSave(name.trim() || DROPPED_PIN);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
      setBusy(false);
    }
  }

  return (
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <form className="add-sheet pin-prompt" role="dialog" aria-modal="true" aria-labelledby="pin-prompt-title" onSubmit={save}>
        <div className="add-sheet-head">
          <h2 id="pin-prompt-title">Drop a pin here</h2>
          <button type="button" className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <label className="field">
          Name
          <input ref={input} className="input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </label>
        <p className="caption">It's saved as an idea at this spot, then you pick its day.</p>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <span className="actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Save pin
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
        </span>
      </form>
    </div>
  );
}

type Drawn = {
  pins: { id: string; title: string; at: Point; color: string }[];
  zones: { iso: string; at: Point; radius: number; text: string; color: string; viewing: boolean }[];
};

/** The Ideas on a Google map: a pin for each idea with a place or pin of its own, coloured
 * by its list; a translucent ring for each day, at the middle of that day's places,
 * named like "Day 6 · Gion" (the day open on Plan stands out). Tapping a pin picks its
 * day. Holding the map drops a pin of the user's own, which becomes an idea. With several
 * stops, one stop's ideas and days show at a time. */
export function IdeasMap({ detail, apiKey, ideas, color, near, viewing, onPick, onDrop }: {
  detail: TripDetail;
  apiKey: string;
  /** The ideas the list shows (its list filter applied). */
  ideas: Booking[];
  color: (b: Booking) => string;
  near: Nearby;
  /** The day open on Plan. */
  viewing: string | null;
  onPick: (b: Booking) => void;
  /** Saves a dropped pin as an idea and opens its day picker. */
  onDrop: (at: Point, name: string) => Promise<void>;
}) {
  const { trip } = detail;
  const { stops, zones, labels, linked } = near;
  const element = useRef<HTMLDivElement>(null);
  const [maps, setMaps] = useState<{ api: MapsApi; map: GMap } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [holding, setHolding] = useState<Point | null>(null);
  const several = stops.length > 1;
  const stop = several ? (stops.find((s) => stopKey(s) === chosen) ?? (viewing ? stopOfDay(stops, viewing) : null) ?? stops[0]) : null;

  const located = ideas.map((b) => ({ b, at: pointOf(b, linked) }));
  const unpinned = located.filter((l) => l.at === null).map((l) => l.b);

  // The stop an idea falls in: that of the day with places nearest it. With no day to go
  // by, it shows whichever stop is open.
  const stopOfIdea = (at: Point): TripStop | null => {
    let best: { iso: string; metres: number } | null = null;
    for (const [iso, z] of zones) {
      const metres = metresBetween(at, z);
      if (!best || metres < best.metres) best = { iso, metres };
    }
    return best ? stopOfDay(stops, best.iso) : null;
  };
  const inStop = (s: TripStop | null) => !stop || s === null || stopKey(s) === stopKey(stop);

  const drawn: Drawn = {
    pins: located
      .filter((l): l is { b: Booking; at: Point } => l.at !== null && inStop(stopOfIdea(l.at)))
      .map((l) => ({ id: l.b.id, title: l.b.title, at: l.at, color: color(l.b) })),
    zones: [...zones]
      .filter(([iso]) => inStop(stopOfDay(stops, iso)))
      .map(([iso, z]) => ({
        iso,
        at: { lat: z.lat, lng: z.lng },
        radius: z.radius,
        text: `Day ${dayNumber(trip, iso)}${labels.get(iso) ? ` · ${labels.get(iso)}` : ""}`,
        color: dayColor(trip, iso),
        viewing: iso === viewing,
      })),
  };
  // With nothing of the stop's own to show, the hotels give the map somewhere to be.
  const hotels = detail.bookings.filter((b) => b.kind === "hotel").map((b) => pointOf(b, linked)).filter((p): p is Point => p !== null);
  const anchors: Point[] = drawn.pins.length + drawn.zones.length > 0 ? [...drawn.pins.map((p) => p.at), ...drawn.zones.map((z) => z.at)] : hotels;
  const anywhere = located.some((l) => l.at !== null) || zones.size > 0 || hotels.length > 0;

  // What's drawn, as a string: the page re-renders with fresh maps of places each time, and
  // the map should be redrawn only when something on it changed.
  const drawKey = JSON.stringify([drawn, stop && stopKey(stop)]);
  const latest = useRef({ drawn, anchors, ideas, onPick, stop: stop && stopKey(stop) });
  latest.current = { drawn, anchors, ideas, onPick, stop: stop && stopKey(stop) };
  const fitted = useRef<string | null>(null);

  useEffect(() => onMapsAuthFailure(() => setError("Google didn't accept the map's key.")), []);

  useEffect(() => {
    if (!anywhere || maps || !element.current) return;
    let live = true;
    loadMaps(apiKey)
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
  }, [apiKey, anywhere, maps]);

  // Holding the map drops a pin: a press that stays put for LONG_PRESS_MS, not moved,
  // lifted or zoomed. (Google fires these for a touch as well as the mouse.)
  useEffect(() => {
    if (!maps) return;
    let timer: number | undefined;
    const cancel = () => {
      window.clearTimeout(timer);
      timer = undefined;
    };
    maps.map.addListener("mousedown", (e) => {
      cancel();
      const at = e.latLng;
      if (!at) return;
      const point = { lat: Math.round(at.lat() * 1e6) / 1e6, lng: Math.round(at.lng() * 1e6) / 1e6 };
      timer = window.setTimeout(() => {
        timer = undefined;
        setHolding(point);
      }, LONG_PRESS_MS);
    });
    for (const event of ["mouseup", "dragstart", "zoom_changed"] as const) maps.map.addListener(event, cancel);
    return cancel;
  }, [maps]);

  useEffect(() => {
    if (!maps) return;
    const { api, map } = maps;
    const { drawn: now, anchors: fit, ideas: tappable, onPick: pick, stop: scope } = latest.current;
    const overlays: GOverlay[] = [];
    for (const z of now.zones) {
      overlays.push(
        new api.Circle({
          map,
          center: z.at,
          radius: z.radius,
          strokeColor: z.color,
          strokeOpacity: z.viewing ? 0.9 : 0.5,
          strokeWeight: z.viewing ? 3 : 1.5,
          fillColor: z.color,
          fillOpacity: z.viewing ? 0.22 : 0.1,
          clickable: false,
        }),
        // The ring's name, written at its middle: a marker with no pin, only its label.
        new api.Marker({
          map,
          position: z.at,
          title: z.text,
          clickable: false,
          zIndex: 1,
          label: { text: z.text, color: "#1f2937", fontWeight: "600", fontSize: "12px" },
          icon: { path: api.circle, scale: 0 },
        }),
      );
    }
    for (const p of now.pins) {
      const marker = new api.Marker({
        map,
        position: p.at,
        title: p.title,
        zIndex: 2,
        icon: { path: api.circle, scale: 9, fillColor: p.color, fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2 },
      });
      marker.addListener("click", () => {
        const b = tappable.find((i) => i.id === p.id);
        if (b) pick(b);
      });
      overlays.push(marker);
    }
    // Fit to what's there once per stop (and again when the first things turn up), not
    // every time a pin is added, which would pull the map from under the user.
    const fitKey = `${scope}|${fit.length > 0}`;
    if (fitted.current !== fitKey && fit.length > 0) {
      fitted.current = fitKey;
      if (fit.length === 1) {
        map.setCenter(fit[0]);
        map.setZoom(15);
      } else {
        const bounds = new api.LatLngBounds();
        fit.forEach((p) => bounds.extend(p));
        map.fitBounds(bounds, 48);
      }
    }
    return () => overlays.forEach((o) => o.setMap(null));
    // What's drawn is read from ``latest``; ``drawKey`` says when it changed.
  }, [maps, drawKey]);

  return (
    <>
      <section className="card ideas-map" aria-labelledby="ideas-map-title">
        <div className="card-head">
          <h2 id="ideas-map-title">Map</h2>
        </div>
        {several && (
          <div className="chips stop-switch" role="group" aria-label="Stop">
            {stops.map((s, i) => (
              <button key={stopKey(s)} type="button" className="day-pill" aria-pressed={stop !== null && stopKey(s) === stopKey(stop)} onClick={() => setChosen(stopKey(s))}>
                <span className="list-dot" style={{ background: stopColor(i) }} aria-hidden="true" /> {s.name}
              </button>
            ))}
          </div>
        )}
        {!anywhere ? (
          <p className="caption">Ideas linked to a place on Google Maps show here, with a ring round each day's plans.</p>
        ) : error ? (
          <p className="error-text" role="alert">
            {error}
          </p>
        ) : (
          <>
            <div ref={element} className="ideas-map-canvas" role="img" aria-label={`Map of ideas in ${stop?.name ?? trip.destination}`} />
            <p className="caption">Tap a pin to put it on a day. Hold the map to drop a pin of your own.</p>
          </>
        )}
        <ul className="sr-only" aria-label="On the map">
          {drawn.pins.map((p) => (
            <li key={p.id}>
              {p.title} (idea)
            </li>
          ))}
          {drawn.zones.map((z) => (
            <li key={z.iso}>{z.text}</li>
          ))}
        </ul>
        {unpinned.length > 0 && (
          <p className="caption ideas-unpinned">
            Not on the map: link a place to pin it. {unpinned.map((b) => b.title).join(", ")}
          </p>
        )}
      </section>
      {/* Outside the card, like the day picker: the card's own stacking would put it under the tab bar. */}
      {holding && (
        <PinPrompt
          onClose={() => setHolding(null)}
          onSave={async (name) => {
            await onDrop(holding, name);
            setHolding(null);
          }}
        />
      )}
    </>
  );
}
