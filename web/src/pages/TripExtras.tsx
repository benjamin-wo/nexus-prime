import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, type PackItem, type Trip, type TripWeather } from "../api";

const weekday = (iso: string) => new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", timeZone: "UTC" }).format(new Date(iso));

/** A weather code (WMO, as Open-Meteo reports it) as a picture. */
export function icon(code: number | null): string {
  if (code === null) return "·";
  if (code <= 1) return "☀️";
  if (code === 2) return "⛅";
  if (code === 3) return "☁️";
  if (code === 45 || code === 48) return "🌫️";
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "❄️";
  if (code >= 95) return "⛈️";
  return "🌧️";
}

export const degrees = (n: number | null) => (n === null ? "–" : `${Math.round(n)}°`);

/** The trip's weather: the forecast once it reaches the trip, before that the same
 * dates in recent years. Nothing shows when it isn't known. */
export function WeatherCard({ trip }: { trip: Trip }) {
  const weather = useQuery({
    queryKey: ["trip-weather", trip.id, trip.start, trip.end, trip.destination],
    queryFn: () => api<TripWeather | null>(`/travel/trips/${trip.id}/weather`),
    staleTime: 60 * 60 * 1000,
    enabled: trip.status !== "finished",
  });
  const w = weather.data;
  if (!w || w.days.length === 0) return null;
  const highs = w.days.map((d) => d.high).filter((n): n is number => n !== null);
  const lows = w.days.map((d) => d.low).filter((n): n is number => n !== null);
  return (
    <section className="card weather-card" aria-labelledby="trip-weather">
      <div className="card-head">
        <h2 id="trip-weather">Weather in {w.place}</h2>
        <span className="caption">{w.kind === "forecast" ? "Forecast" : `Typical for these dates, last ${w.years} years`}</span>
      </div>
      {highs.length > 0 && lows.length > 0 && (
        <p className="weather-range">
          {degrees(Math.min(...lows))} to {degrees(Math.max(...highs))}
        </p>
      )}
      <ol className="weather-days" aria-label={w.kind === "forecast" ? "Forecast by day" : "Typical weather by day"}>
        {w.days.map((d) => (
          <li key={d.day} className="weather-day" title={d.summary ?? undefined}>
            <span className="caption">{weekday(d.day)}</span>
            <span className="weather-icon" role="img" aria-label={d.summary ?? "Weather"}>
              {icon(d.code)}
            </span>
            <span className="num">
              {degrees(d.high)} <span className="caption">{degrees(d.low)}</span>
            </span>
            {d.rain !== null && <span className={`caption${d.rain >= 50 ? " is-wet" : ""}`}>{d.rain}% rain</span>}
          </li>
        ))}
      </ol>
      <p className="caption">
        <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">
          Weather data by Open-Meteo.com
        </a>
      </p>
    </section>
  );
}

/** What to bring, ticked off as it's packed, with suggestions for a trip like this. */
export function PackingCard({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [items, setItems] = useState<PackItem[]>(trip.packing ?? []);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const done = items.filter((i) => i.done).length;

  async function save(next: PackItem[]) {
    const before = items;
    setItems(next);
    setError(null);
    try {
      const saved = await api<Trip>(`/travel/trips/${trip.id}/packing`, { method: "PUT", body: { items: next } });
      setItems(saved.packing ?? next);
      onChange();
    } catch (e) {
      setItems(before);
      setError(e instanceof Error ? e.message : "Couldn't save the list");
    }
  }

  async function suggest() {
    setBusy(true);
    setError(null);
    try {
      const saved = await api<Trip>(`/travel/trips/${trip.id}/packing/suggest`, { method: "POST" });
      setItems(saved.packing ?? []);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't suggest anything");
    } finally {
      setBusy(false);
    }
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    void save([...items, { text: text.trim(), done: false }]);
    setText("");
  }

  return (
    <section className="card packing-card" aria-labelledby="trip-packing">
      <div className="card-head">
        <h2 id="trip-packing">Packing list</h2>
        {items.length > 0 && (
          <span className="caption">
            {done} of {items.length} packed
          </span>
        )}
      </div>
      {items.length > 0 && (
        <div className="meter meter-sky" aria-hidden="true">
          <span style={{ width: `${(done / items.length) * 100}%` }} />
        </div>
      )}
      {items.length === 0 && <p className="state">Nothing on the list yet. Add things, or let Nexus suggest the usual for this trip.</p>}
      <ul className="packing-list" aria-label="Things to pack">
        {items.map((item, i) => (
          <li key={`${item.text}-${i}`} className={item.done ? "is-done" : undefined}>
            <label>
              <input type="checkbox" checked={item.done} onChange={() => void save(items.map((x, j) => (j === i ? { ...x, done: !x.done } : x)))} />
              <span>{item.text}</span>
            </label>
            <button type="button" className="btn btn-ghost btn-small" aria-label={`Remove ${item.text}`} onClick={() => void save(items.filter((_, j) => j !== i))}>
              ×
            </button>
          </li>
        ))}
      </ul>
      <form className="packing-add" onSubmit={add} aria-label="Add to the packing list">
        <input className="input" value={text} maxLength={60} onChange={(e) => setText(e.target.value)} placeholder="Add something, e.g. Swimsuit" aria-label="Thing to pack" />
        <button type="submit" className="btn" disabled={!text.trim()}>
          Add
        </button>
        <button type="button" className="btn btn-ghost" onClick={() => void suggest()} disabled={busy}>
          {busy ? "Suggesting…" : "✨ Suggest"}
        </button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** The cover's photo choices: another photo of the place, or none. */
export function PhotoMenu({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  async function choose(choice: "next" | "off" | "on") {
    setNote(null);
    try {
      await api<Trip>(`/travel/trips/${trip.id}/photo`, { method: "POST", body: { choice } });
      setOpen(false);
      onChange();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Couldn't change the photo");
    }
  }
  return (
    <div className="photo-menu">
      <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>
        Photo
      </button>
      {open && (
        <div className="photo-menu-list" role="menu" aria-label="Cover photo">
          {trip.photo_off ? (
            <button type="button" role="menuitem" className="btn btn-ghost" onClick={() => void choose("on")}>
              Show a photo
            </button>
          ) : (
            <>
              <button type="button" role="menuitem" className="btn btn-ghost" onClick={() => void choose("next")}>
                Another photo
              </button>
              <button type="button" role="menuitem" className="btn btn-ghost" onClick={() => void choose("off")}>
                No photo
              </button>
            </>
          )}
          {note && (
            <p className="caption" role="status">
              {note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
