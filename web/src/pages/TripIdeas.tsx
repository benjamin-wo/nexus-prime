import { type ReactNode, useState } from "react";

import type { Booking, TripDetail } from "../api";
import { formatMoney } from "../format";
import { DayPickerSheet, DropZone, PLACES, useArrange, useDragEntry } from "./TripArrange";
import { OpenLink, onlyNamesDay, repeatsTitle, sortKey, useHome } from "./TripBits";
import { EntryEditor } from "./TripEntry";
import { dayNumber } from "./TripMap";
import { PlaceLine, SavePlaces } from "./TripPlaces";

/** The list an idea shows under: its own list, else its kind. */
export const listOf = (b: Booking) => b.list_name ?? b.category ?? null;

/** Dot colours for lists, told apart by lightness as well as hue. */
const DOTS = ["var(--accent)", "#e08a1e", "#9ca8b8", "var(--cyan-accent)"];

/** Each list's dot colour, by sorted name: a list keeps its colour as others come and go. */
export function listColors(lists: string[]): Map<string, string> {
  return new Map([...new Set(lists)].sort().map((l, i) => [l, DOTS[i % DOTS.length]]));
}

/** An idea: its grip, a dot for its list, its name and where it is, and its button.
 * ``dragging`` off for an idea already on a day, which is moved from Plan. */
export function PlaceRow({ booking, color, dragging = true, onEdit, children }: {
  booking: Booking;
  color: string;
  dragging?: boolean;
  /** Opens the idea to change it. */
  onEdit: () => void;
  /** The button at the end of the row. */
  children: ReactNode;
}) {
  const grip = useDragEntry(booking, dragging ? PLACES : undefined);
  const address = booking.address && !repeatsTitle(booking.address, booking.title) ? booking.address : null;
  // Where it is and which list, each said once.
  const caption = [address ?? booking.category, booking.list_name].filter((t, i, all): t is string => Boolean(t) && all.indexOf(t) === i);
  return (
    <li ref={grip.ref} className={`place-row${grip.className}`} id={`entry-${booking.id}`}>
      <span className="place-grip">{grip.handle}</span>
      <span className="list-dot" style={{ background: color }} aria-hidden="true" />
      <span className="place-text">
        <button type="button" className="place-name" onClick={onEdit} aria-label={`Change ${booking.title}`}>
          <strong>{booking.title}</strong>
          {caption.length > 0 && <span className="caption">{caption.join(" · ")}</span>}
        </button>
        {booking.note && !onlyNamesDay(booking.note) && <span className="caption">{booking.note}</span>}
        <PlaceLine booking={booking} />
        <OpenLink booking={booking} />
      </span>
      <span className="num place-cost">{booking.cost ? formatMoney(booking.cost) : null}</span>
      <span className="place-action">{children}</span>
    </li>
  );
}

/** The Ideas tab: places saved without a day, each given one when it fits the plan (or
 * dragged onto a day). Filed in lists, which filter it once there are two or more.
 * ``viewing`` is the day open on Plan. */
export function IdeasTab({ detail, onChange, viewing }: { detail: TripDetail; onChange: () => void; viewing: string | null }) {
  const home = useHome();
  const [editing, setEditing] = useState<string | null>(null);
  const [picking, setPicking] = useState<Booking | null>(null);
  const [list, setList] = useState<string | null>(null);
  const [planned, setPlanned] = useState(false);
  const arrange = useArrange(detail);
  const ideas = arrange.spots.get(PLACES) ?? [];
  // Ideas that were put on a day keep their list, which is how we know where they came from.
  const onDays = detail.bookings.filter((b) => b.kind === "activity" && b.scheduled && b.list_name).sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  const shown = planned ? [...ideas, ...onDays] : ideas;
  const lists = [...new Set(shown.map(listOf).filter((l): l is string => Boolean(l)))].sort();
  const colors = listColors([...ideas, ...onDays].map(listOf).filter((l): l is string => Boolean(l)));
  const picked = list && lists.includes(list) ? list : null;
  const items = picked ? shown.filter((b) => listOf(b) === picked) : shown;
  const color = (b: Booking) => colors.get(listOf(b) ?? "") ?? "var(--text-muted)";

  return (
    <section id="section-place" className="card ideas" aria-labelledby="ideas-title">
      <h2 id="ideas-title" className="sr-only">
        Ideas
      </h2>
      {(detail.places || detail.ideas) && <SavePlaces />}
      {(lists.length > 1 || onDays.length > 0) && (
        <div className="chips list-chips" role="group" aria-label="Lists">
          {lists.length > 1 && (
            <>
              <button type="button" className="day-pill" aria-pressed={!picked} onClick={() => setList(null)}>
                All
              </button>
              {lists.map((l) => (
                <button key={l} type="button" className="day-pill" aria-pressed={picked === l} onClick={() => setList(l)}>
                  {l} <span className="caption">{shown.filter((b) => listOf(b) === l).length}</span>
                </button>
              ))}
            </>
          )}
          {onDays.length > 0 && (
            <button type="button" className="day-pill" aria-pressed={planned} onClick={() => setPlanned(!planned)}>
              Show planned
            </button>
          )}
        </div>
      )}
      <DropZone spot={PLACES} empty={ideas.every((b) => b.id === arrange.dragging)}>
        {items.length === 0 ? (
          <p className="state">No ideas yet. Find some, or tap + to save one.</p>
        ) : (
          <ul className={`feed place-list${arrange.on ? " can-drag" : ""}`} aria-label="Ideas">
            {items.map((b) =>
              editing === b.id ? (
                <li key={b.id}>
                  <EntryEditor
                    trip={detail.trip}
                    home={home}
                    entry={b}
                    lists={lists}
                    onMove={() => setPicking(b)}
                    onDone={(saved) => {
                      setEditing(null);
                      if (saved) onChange();
                    }}
                  />
                </li>
              ) : b.scheduled ? (
                <PlaceRow key={b.id} booking={b} color={color(b)} dragging={false} onEdit={() => setEditing(b.id)}>
                  <button type="button" className="btn btn-small" onClick={() => setPicking(b)} aria-label={`${b.title} is on Day ${dayNumber(detail.trip, b.day ?? b.starts)}, change the day`}>
                    Day {dayNumber(detail.trip, b.day ?? b.starts)}
                  </button>
                </PlaceRow>
              ) : (
                <PlaceRow key={b.id} booking={b} color={color(b)} onEdit={() => setEditing(b.id)}>
                  <button type="button" className="btn btn-small btn-primary" onClick={() => setPicking(b)} aria-label={`Put ${b.title} on a day`}>
                    Add to day
                  </button>
                </PlaceRow>
              ),
            )}
          </ul>
        )}
      </DropZone>
      {arrange.on && ideas.length > 0 && <p className="caption">Drag an idea onto a day to plan it.</p>}
      {picking && <DayPickerSheet detail={detail} booking={picking} viewing={viewing} onClose={() => setPicking(null)} />}
    </section>
  );
}
