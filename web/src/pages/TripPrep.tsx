import type { Trip, TripDetail } from "../api";
import { PackingCard, WeatherCard } from "./TripExtras";
import type { Fix } from "./TripStage";

export function Notes({ trip }: { trip: Trip }) {
  if (!trip.notes) return null;
  return (
    <section className="card" aria-labelledby="trip-notes">
      <div className="card-head">
        <h2 id="trip-notes">Notes</h2>
      </div>
      <p className="notes">{trip.notes}</p>
    </section>
  );
}

/** The Prep tab. ``adding``: the tab's + was pressed (a packing item). */
export function PrepTab({ detail, onChange }: { detail: TripDetail; onChange: () => void; onFix: (fix: Fix) => void; adding: boolean; onAddDone: () => void }) {
  return (
    <>
      <WeatherCard trip={detail.trip} />
      <PackingCard key={detail.trip.id} trip={detail.trip} onChange={onChange} />
      <Notes trip={detail.trip} />
    </>
  );
}
