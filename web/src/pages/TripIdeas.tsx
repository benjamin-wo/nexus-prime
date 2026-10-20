import { type ReactNode, useId, useState, useSyncExternalStore } from "react";

import { api, type Booking, type TripDetail } from "../api";
import { Icon } from "../components/Icon";
import { formatMoney } from "../format";
import type { Point } from "../geo";
import { DayPickerSheet, DropZone, PLACES, ideaHint, nearbyOf, useArrange, useDragEntry } from "./TripArrange";
import { OpenLink, onlyNamesDay, repeatsTitle, sortKey, useHome } from "./TripBits";
import { EntryEditor } from "./TripEntry";
import { IdeasMap } from "./TripIdeasMap";
import { dayNumber } from "./TripMap";
import { PlaceLine, SavePlaces, useLinkedPlaces } from "./TripPlaces";

/** The list an idea shows under: its own list, else its kind. */
export const listOf = (b: Booking) => b.list_name ?? b.category ?? null;

/** Dot colours for lists, told apart by lightness as well as hue. */
const DOTS = ["var(--accent)", "#e08a1e", "#9ca8b8", "var(--cyan-accent)"];

/** Each list's dot colour, by sorted name: a list keeps its colour as others come and go. */
export function listColors(lists: string[]): Map<string, string> {
  return new Map([...new Set(lists)].sort().map((l, i) => [l, DOTS[i % DOTS.length]]));
}

/** Wide enough for the list and the map to sit side by side. */
const WIDE = "(min-width: 1024px)";

function useWide(): boolean {
  return useSyncExternalStore(
    (changed) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const query = window.matchMedia(WIDE);
      query.addEventListener("change", changed);
      return () => query.removeEventListener("change", changed);
    },
    () => typeof window.matchMedia === "function" && window.matchMedia(WIDE).matches,
    () => false,
  );
}

/** Google Maps, opened on the idea: its pin if it has one, else its name and address. */
function mapsLink(b: Booking): string {
  const query = b.lat != null && b.lng != null ? `${b.lat},${b.lng}` : [b.title, b.address].filter(Boolean).join(" ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

/** An idea, as one quiet row: a dot for its list, its name over one grey line (where it is,
 * its list, how it fits the plan), its cost and its button. Tapping the name opens it to
 * show its note, Google Maps and place details, and Change and Remove. A grip shows while
 * ideas are being arranged. ``dragging`` off for an idea already on a day, which is moved
 * from Plan. ``hint``: how it fits the plan ("Near Day 6 · 1.2 km"). */
export function PlaceRow({ booking, color, dragging = true, hint = null, onEdit, onRemoved, children }: {
  booking: Booking;
  color: string;
  dragging?: boolean;
  hint?: string | null;
  /** Opens the idea to change it. */
  onEdit: () => void;
  /** Called once Remove has taken the idea off the trip. */
  onRemoved?: () => void;
  /** The button at the end of the row. */
  children: ReactNode;
}) {
  const grip = useDragEntry(booking, dragging ? PLACES : undefined);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const openId = useId();
  const address = booking.address && !repeatsTitle(booking.address, booking.title) ? booking.address : null;
  // Where it is, which list and how it fits the plan, each said once.
  const meta = [address ?? booking.category, booking.list_name, hint].filter((t, i, all): t is string => Boolean(t) && all.indexOf(t) === i);
  const note = booking.note && !onlyNamesDay(booking.note) ? booking.note : null;

  // The same call, and the same question, as the editor's Remove.
  async function remove() {
    if (!window.confirm(`Take ${booking.title} off the trip?`)) return;
    setError(null);
    setBusy(true);
    try {
      await api(`/travel/bookings/${booking.id}`, { method: "DELETE" });
      onRemoved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove that");
      setBusy(false);
    }
  }

  return (
    <li ref={grip.ref} className={`place-row${grip.className}`} id={`entry-${booking.id}`}>
      <div className="place-main">
        <span className="place-grip">{grip.handle}</span>
        <span className="list-dot" style={{ background: color }} aria-hidden="true" />
        <button type="button" className="place-name" aria-expanded={open} aria-controls={open ? openId : undefined} onClick={() => setOpen(!open)}>
          <strong>{booking.title}</strong>
          {meta.length > 0 && <span className="place-meta">{meta.join(" · ")}</span>}
        </button>
        <span className="num place-cost">{booking.cost ? formatMoney(booking.cost) : null}</span>
        <span className="place-action">{children}</span>
      </div>
      {open && (
        <div id={openId} className="place-open">
          {note && <p className="place-note">{note}</p>}
          <span className="place-links">
            <a className="caption entry-link" href={mapsLink(booking)} target="_blank" rel="noopener noreferrer">
              Open in Google Maps ↗
            </a>
            <OpenLink booking={booking} />
          </span>
          <PlaceLine booking={booking} />
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <div className="place-open-actions">
            <button type="button" className="btn btn-ghost btn-small" onClick={onEdit} aria-label={`Change ${booking.title}`}>
              <Icon name="edit" size={16} />
              Change
            </button>
            <button type="button" className="btn btn-ghost btn-danger btn-small" disabled={busy} onClick={() => void remove()} aria-label={`Remove ${booking.title}`}>
              <Icon name="trash" size={16} />
              Remove
            </button>
          </div>
        </div>
      )}
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
  const [view, setView] = useState<"list" | "map">("list");
  const [finding, setFinding] = useState(false);
  const [arranging, setArranging] = useState(false);
  const wide = useWide();
  const linked = useLinkedPlaces();
  const near = nearbyOf(detail, linked);
  const mapKey = detail.map_key ?? null;
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
  const hint = (b: Booking) => ideaHint(detail, b, near, viewing);

  // A pin dropped by holding the map is an idea of the user's own, in the list being looked
  // at; its day is asked for straight after.
  async function drop(at: Point, name: string) {
    const created = await api<Booking>(`/travel/trips/${detail.trip.id}/bookings`, {
      method: "POST",
      body: { kind: "activity", name: name.slice(0, 120), lat: at.lat, lng: at.lng, list_name: picked?.slice(0, 30) ?? null },
    });
    onChange();
    setPicking(created);
  }

  const canFind = Boolean(detail.places || detail.ideas);
  const canArrange = arrange.on && ideas.length > 0;
  const arrangingNow = arranging && canArrange;
  const count = items.length;

  return (
    <>
    {/* Wide, the list and the map sit side by side and there is nothing to switch. */}
    {((mapKey && !wide) || canFind) && (
      <div className="ideas-bar">
        {mapKey && !wide && (
          <div className="ideas-switch" role="group" aria-label="Show ideas as">
            {(["list", "map"] as const).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>
                <Icon name={v} size={16} />
                {v === "list" ? "List" : "Map"}
              </button>
            ))}
          </div>
        )}
        {canFind && (
          <button type="button" className="btn btn-soft ideas-find" onClick={() => setFinding(true)}>
            <Icon name="find" size={18} />
            Find ideas
          </button>
        )}
      </div>
    )}
    <div className="ideas-layout" data-view={mapKey && !wide ? view : "list"}>
    <section id="section-place" className="card ideas" aria-labelledby="ideas-title">
      <div className="ideas-head">
        <h2 id="ideas-title">{count === 1 ? "1 idea" : `${count} ideas`}</h2>
        {canArrange && (
          <button type="button" className="btn btn-ghost btn-small ideas-arrange" aria-pressed={arrangingNow} onClick={() => setArranging(!arrangingNow)}>
            {arrangingNow ? "Done" : "Arrange"}
          </button>
        )}
      </div>
      {arrangingNow && <p className="caption">Drag an idea by its grip to put your ideas in order, or tap its calendar button to plan it.</p>}
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
          <ul className={`place-list${arrangingNow ? " can-drag" : ""}`} aria-label="Ideas">
            {items.map((b) =>
              editing === b.id ? (
                <li key={b.id} className="place-editing">
                  <EntryEditor
                    trip={detail.trip}
                    home={home}
                    entry={b}
                    lists={lists}
                    onMove={() => {
                      setEditing(null);
                      setPicking(b);
                    }}
                    onDone={(saved) => {
                      setEditing(null);
                      if (saved) onChange();
                    }}
                  />
                </li>
              ) : b.scheduled ? (
                <PlaceRow key={b.id} booking={b} color={color(b)} dragging={false} hint={hint(b)} onEdit={() => setEditing(b.id)} onRemoved={onChange}>
                  <button type="button" className="btn btn-soft btn-small" onClick={() => setPicking(b)} aria-label={`${b.title} is on Day ${dayNumber(detail.trip, b.day ?? b.starts)}, change the day`}>
                    Day {dayNumber(detail.trip, b.day ?? b.starts)}
                  </button>
                </PlaceRow>
              ) : (
                <PlaceRow key={b.id} booking={b} color={color(b)} dragging={arrangingNow} hint={hint(b)} onEdit={() => setEditing(b.id)} onRemoved={onChange}>
                  <button type="button" className="place-day" onClick={() => setPicking(b)} aria-label={`Put ${b.title} on a day`}>
                    <Icon name="calendarPlus" size={22} />
                  </button>
                </PlaceRow>
              ),
            )}
          </ul>
        )}
      </DropZone>
    </section>
    {mapKey && (wide || view === "map") && (
      <IdeasMap detail={detail} apiKey={mapKey} ideas={items} color={color} near={near} viewing={viewing} onPick={setPicking} onDrop={drop} />
    )}
    </div>
    {/* Outside the card: a card's own stacking would put the sheet under the tab bar on a phone. */}
    {picking && <DayPickerSheet detail={detail} booking={picking} viewing={viewing} onClose={() => setPicking(null)} />}
    {finding && <SavePlaces viewing={viewing} onClose={() => setFinding(false)} />}
    </>
  );
}
