import type { Trip } from "../api";

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
