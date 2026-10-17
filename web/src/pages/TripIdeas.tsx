import { type ReactNode, useState } from "react";

import { api, type Booking, type TripDetail } from "../api";
import { formatMoney } from "../format";
import { DropZone, PLACES, useArrange, useDragEntry } from "./TripArrange";
import { BookingLines, OpenLink, useHome } from "./TripBits";
import { EntryEditor } from "./TripEntry";
import { SavePlaces } from "./TripPlaces";

/** The list a place to visit shows under: its own list, else its kind. */
export const listOf = (b: Booking) => b.list_name ?? b.category ?? null;

/** A place to visit in the list: its grip, what it is, and its buttons. */
export function PlaceRow({ booking, n, children }: { booking: Booking; n: number; children: ReactNode }) {
  const drag = useDragEntry(booking, PLACES);
  return (
    <li ref={drag.ref} className={`run-row place-row${drag.className}`} id={`entry-${booking.id}`}>
      {drag.handle}
      <span className="stop-number" aria-hidden="true">
        {n}
      </span>
      <span className="wrap">
        <strong>{booking.title}</strong>
        {listOf(booking) && <span className="caption"> · {listOf(booking)}</span>}
        <br />
        <BookingLines booking={booking} />
        <OpenLink booking={booking} />
      </span>
      {booking.cost && <span className="num">{formatMoney(booking.cost)}</span>}
      {children}
    </li>
  );
}

/** Places to visit: saved without a day, each given one when it fits the plan (or
 * dragged onto a day). Bookings live on the timeline, so this is the one list kept
 * apart from it. Filed in lists, which filter it once there are two or more. */
export function Sections({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const home = useHome();
  const [editing, setEditing] = useState<string | null>(null);
  const [list, setList] = useState<string | null>(null);
  const arrange = useArrange(detail);
  const all = arrange.spots.get(PLACES) ?? [];
  const lists = [...new Set(all.map(listOf).filter((l): l is string => Boolean(l)))].sort();
  const picked = list && lists.includes(list) ? list : null;
  const items = picked ? all.filter((b) => listOf(b) === picked) : all;
  async function remove(b: Booking) {
    if (!window.confirm(`Take ${b.title} off the trip?`)) return;
    await api(`/travel/bookings/${b.id}`, { method: "DELETE" }).catch(() => undefined);
    onChange();
  }
  if (all.length === 0 && !detail.places) return null;
  return (
    <details id="section-place" className="card section" open>
      <summary>
        <h2>Places to visit</h2>
        <span className="caption">{all.length || "None yet"}</span>
      </summary>
      {lists.length > 1 && (
        <div className="chips list-chips" role="group" aria-label="Lists">
          <button type="button" className="day-pill" aria-pressed={!picked} onClick={() => setList(null)}>
            All
          </button>
          {lists.map((l) => (
            <button key={l} type="button" className="day-pill" aria-pressed={picked === l} onClick={() => setList(l)}>
              {l} <span className="caption">{all.filter((b) => listOf(b) === l).length}</span>
            </button>
          ))}
        </div>
      )}
      <DropZone spot={PLACES} empty={all.every((b) => b.id === arrange.dragging)}>
        <ul className="feed" aria-label="Places to visit">
          {items.map((b) =>
            editing === b.id ? (
              <li key={b.id}>
                <EntryEditor
                  trip={detail.trip}
                  home={home}
                  entry={b}
                  lists={lists}
                  onDone={(saved) => {
                    setEditing(null);
                    if (saved) onChange();
                  }}
                />
              </li>
            ) : (
              <PlaceRow key={b.id} booking={b} n={all.indexOf(b) + 1}>
                <span className="row-actions">
                  <button type="button" className="btn btn-small" onClick={() => setEditing(b.id)} aria-label={`Plan a day for ${b.title}`}>
                    Pick a day
                  </button>
                  <button type="button" className="btn btn-small" onClick={() => void remove(b)} aria-label={`Remove ${b.title}`}>
                    Remove
                  </button>
                </span>
              </PlaceRow>
            ),
          )}
        </ul>
      </DropZone>
      {arrange.on && all.length > 0 && <p className="caption">Drag a place onto a day to plan it.</p>}
      <SavePlaces />
    </details>
  );
}

/** The Ideas tab. ``viewing`` is the day open on the Plan tab. */
export function IdeasTab({ detail, onChange }: { detail: TripDetail; onChange: () => void; viewing: string | null }) {
  return <Sections detail={detail} onChange={onChange} />;
}
