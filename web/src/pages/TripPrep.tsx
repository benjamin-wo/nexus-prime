import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, type Trip, type TripDetail } from "../api";
import { tripBody } from "./TripEntry";
import { PackingCard, WeatherCard } from "./TripExtras";
import { type Fix, StillToSort } from "./TripStage";

/** The trip's notes, edited where they're read. Saves on the button or when the field is left. */
function NotesEditor({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const saved = trip.notes?.trim() ?? "";
  const [text, setText] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  const changed = text.trim() !== saved;

  // Follow the trip when it's reloaded (a save, or an edit made elsewhere).
  useEffect(() => setText(saved), [saved]);
  useEffect(() => {
    if (!done) return;
    const timer = window.setTimeout(() => setDone(false), 2000);
    return () => window.clearTimeout(timer);
  }, [done]);

  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (!changed || sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}`, { method: "PUT", body: tripBody(trip, { notes: text.trim() || null }) });
      onChange();
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the notes");
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  return (
    <section className="card prep-notes" aria-labelledby="trip-notes">
      <div className="card-head">
        <h2 id="trip-notes">Notes</h2>
        {done && (
          <span className="caption" role="status">
            Saved
          </span>
        )}
      </div>
      <form onSubmit={(e) => void save(e)} aria-label="Trip notes">
        <label className="field">
          Notes
          <textarea
            className="input"
            rows={5}
            value={text}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            onBlur={() => void save()}
            placeholder="Visa details, a friend's address, what to remember…"
          />
        </label>
        <div className="prep-notes-actions">
          <button type="submit" className="btn btn-primary" disabled={!changed || busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** The Prep tab: what's left to sort, what to pack, the weather and the trip's notes.
 * ``adding``: the tab's + was pressed (a packing item). */
export function PrepTab({ detail, onChange, onFix, adding, onAddDone }: { detail: TripDetail; onChange: () => void; onFix: (fix: Fix) => void; adding: boolean; onAddDone: () => void }) {
  const { trip } = detail;
  return (
    <>
      {trip.status !== "finished" && <StillToSort detail={detail} onFix={onFix} />}
      <PackingCard key={trip.id} trip={trip} onChange={onChange} adding={adding} onAddDone={onAddDone} />
      <WeatherCard trip={trip} />
      <NotesEditor key={trip.id} trip={trip} onChange={onChange} />
    </>
  );
}
