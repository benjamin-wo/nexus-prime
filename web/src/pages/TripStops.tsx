import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";

import { api, type Trip, type TripDetail, type TripStop } from "../api";
import { Icon } from "../components/Icon";
import { day, stopColor, stopOfDay, stopsOf } from "./TripBits";

const DAY_MS = 86400000;
const nightsBetween = (start: string, end: string) => Math.round((Date.parse(end) - Date.parse(start)) / DAY_MS);

/** How a travel day is shown: a plane when a flight is on it, a train when a train is,
 * else a plain arrow (the way there isn't booked). */
export type TravelIcon = "plane" | "train" | "arrow";

/** Whether a day is a travel day: one stop ends on it and the next starts. */
export function isTravelDay(stops: TripStop[], iso: string): boolean {
  return stops.some((s, i) => i > 0 && s.start === iso && stops[i - 1].end === iso);
}

export function travelIcon(detail: Pick<TripDetail, "bookings">, iso: string): TravelIcon {
  const onDay = detail.bookings.filter((b) => b.scheduled && (b.starts === iso || b.segments.some((s) => s.departs?.slice(0, 10) === iso || s.arrives?.slice(0, 10) === iso)));
  if (onDay.some((b) => b.kind === "flight")) return "plane";
  if (onDay.some((b) => b.kind === "rail")) return "train";
  return "arrow";
}

const ICONS: Record<TravelIcon, ReactNode> = {
  plane: <path d="M10.2 14 4 12.5l1-1.7 6.3.7 4.3-5.2a1.6 1.6 0 0 1 2.7 1.6L14.5 13l.9 6.5-1.8.8-2.9-5.6z" />,
  train: (
    <>
      <rect x="5" y="3" width="14" height="14" rx="3" />
      <path d="M5 11h14M9 21l2-4M15 21l-2-4" />
      <circle cx="9" cy="14" r="0.6" />
      <circle cx="15" cy="14" r="0.6" />
    </>
  ),
  arrow: <path d="M4 12h15m-5-5 5 5-5 5" />,
};

/** A small plane, train or arrow, drawn in the text's colour. Decoration: the text around it says it. */
export function TravelGlyph({ icon }: { icon: TravelIcon }) {
  return (
    <svg className="travel-glyph" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[icon]}
    </svg>
  );
}

/** What sits before a day pill's text: its stop's dot, and on a travel day the way there. */
export function pillMark(detail: TripDetail, iso: string) {
  const stops = stopsOf(detail);
  const stop = stopOfDay(stops, iso);
  if (!stop) return null;
  return (
    <>
      <span className="stop-dot" style={{ background: stopColor(stops.indexOf(stop)) }} aria-hidden="true" />
      {isTravelDay(stops, iso) && <TravelGlyph icon={travelIcon(detail, iso)} />}
    </>
  );
}

/** What a pill's hover title says: "Kyoto", or "Travel day: Tokyo to Kyoto". */
export function pillTitle(detail: TripDetail, iso: string): string | undefined {
  const stops = stopsOf(detail);
  const stop = stopOfDay(stops, iso);
  if (!stop) return undefined;
  const from = stops[stops.indexOf(stop) - 1];
  return isTravelDay(stops, iso) && from ? `Travel day: ${from.name} to ${stop.name}` : stop.name;
}

/** The trip's stops across the top of the plan: each with its dates and nights (a tap
 * opens its first day), and a marker where a travel day joins two. */
export function StopsRow({ detail, viewing, onDay, onEdit }: { detail: TripDetail; viewing: string; onDay: (iso: string) => void; onEdit: () => void }) {
  const stops = stopsOf(detail);
  const here = stopOfDay(stops, viewing);
  return (
    <div className="stops-row">
      <ol className="stops-list" aria-label="Stops">
        {stops.map((s, i) => {
          const nights = nightsBetween(s.start, s.end);
          const travel = i > 0 && stops[i - 1].end === s.start;
          return (
            <Fragment key={`${s.name}-${s.start}`}>
              {travel && (
                <li className="stop-travel" aria-label={`Travel day, ${day(s.start)}`}>
                  <TravelGlyph icon={travelIcon(detail, s.start)} />
                </li>
              )}
              <li>
                <button type="button" className="day-pill stop-chip" aria-current={s === here ? "true" : undefined} onClick={() => onDay(s.start)}>
                  <span className="stop-dot" style={{ background: stopColor(i) }} aria-hidden="true" />
                  <span className="stop-text">
                    <strong className="stop-name">{s.name}</strong>
                    <span className="caption">
                      {s.start === s.end ? day(s.start) : `${day(s.start)} – ${day(s.end)}`} · {nights === 0 ? "same day" : `${nights} ${nights === 1 ? "night" : "nights"}`}
                    </span>
                  </span>
                </button>
              </li>
            </Fragment>
          );
        })}
      </ol>
      <button type="button" className="btn btn-ghost btn-small" onClick={onEdit}>
        <Icon name="edit" size={16} />
        Edit stops
      </button>
    </div>
  );
}

type Row = TripStop & { key: number };

/** Change the stops: rename, move the dates, add or remove one, or go back to those the
 * hotels suggest. The server's reason is shown when it won't take them. */
export function StopsSheet({ trip, detail, onClose, onSaved }: { trip: Trip; detail: TripDetail; onClose: () => void; onSaved: () => void }) {
  const next = useRef(0);
  const fresh = (s: TripStop): Row => ({ ...s, key: (next.current += 1) });
  const [rows, setRows] = useState<Row[]>(() => stopsOf(detail).map(fresh));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saved = (trip.stops ?? []).length > 0;

  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [onClose]);

  const change = (key: number, patch: Partial<TripStop>) => setRows((was) => was.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const add = () => setRows((was) => [...was, fresh({ name: "", start: was.at(-1)?.end ?? trip.start, end: trip.end })]);

  async function send(stops: TripStop[]) {
    setBusy(true);
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}/stops`, { method: "PUT", body: { stops } });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the stops. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="add-sheet stops-sheet" role="dialog" aria-modal="true" aria-labelledby="stops-sheet-title">
        <div className="add-sheet-head">
          <h2 id="stops-sheet-title">Stops</h2>
          <button type="button" className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="caption">
          Where you are, and when. A travel day is the day one stop ends and the next starts.
          {!saved && " These follow your places to stay until you save them."}
        </p>
        <form
          className="stops-form"
          onSubmit={(e) => {
            e.preventDefault();
            void send(rows.map(({ name, start, end }) => ({ name: name.trim(), start, end })));
          }}
        >
          <ul className="stops-edit">
            {rows.map((r, i) => (
              <li key={r.key} className="stops-edit-row">
                <span className="stop-dot" style={{ background: stopColor(i) }} aria-hidden="true" />
                <input className="input stops-name" value={r.name} maxLength={40} onChange={(e) => change(r.key, { name: e.target.value })} placeholder="City or area, e.g. Kyoto" aria-label={`Name of stop ${i + 1}`} />
                <label className="stops-date">
                  <span className="caption">From</span>
                  <input className="input" type="date" value={r.start} min={trip.start} max={trip.end} onChange={(e) => change(r.key, { start: e.target.value })} aria-label={`Stop ${i + 1} starts`} />
                </label>
                <label className="stops-date">
                  <span className="caption">To</span>
                  <input className="input" type="date" value={r.end} min={trip.start} max={trip.end} onChange={(e) => change(r.key, { end: e.target.value })} aria-label={`Stop ${i + 1} ends`} />
                </label>
                <button type="button" className="btn btn-ghost btn-danger btn-small" onClick={() => setRows((was) => was.filter((x) => x.key !== r.key))} aria-label={`Remove stop ${i + 1}`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
          {rows.length === 0 && <p className="caption">No stops: saving goes back to the ones your places to stay suggest.</p>}
          {rows.length < 10 && (
            <button type="button" className="btn btn-ghost btn-small stops-add" onClick={add}>
              Add stop
            </button>
          )}
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Save"}
            </button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void send([])}>
              Use suggested
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
