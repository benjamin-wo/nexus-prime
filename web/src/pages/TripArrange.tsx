import {
  type Announcements,
  type ClientRect,
  type CollisionDetection,
  DndContext,
  type DragEndEvent,
  type DragMoveEvent,
  DragOverlay,
  type DragStartEvent,
  MouseSensor,
  TouchSensor,
  closestCenter,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { type FormEvent, type KeyboardEvent, type ReactNode, createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

import { api, type Booking, type DayNote, type Hop, type LinkedPlace, type TripDetail, type TripStop } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { distance, metresBetween, type Point } from "../geo";
import { sortKey, stopOfDay, stopsOf, suggestLabel } from "./TripBits";
import { useLinkedPlaces } from "./TripPlaces";

const dayName = (iso: string) => new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso));

/** Where an entry sits: a day of the itinerary ("day:2026-11-12") or places to visit. */
export type Spot = `day:${string}` | "places";
export const PLACES: Spot = "places";
export const daySpot = (iso: string): Spot => `day:${iso}`;
const dayOf = (spot: Spot) => (spot === PLACES ? null : spot.slice(4));

/** Every spot's entries in order: each day as the server arranged it (or by time, for
 * an older server), then places to visit in the user's order. */
export function spotsOf(detail: Pick<TripDetail, "bookings" | "days" | "places_order">): Map<Spot, Booking[]> {
  const byId = new Map(detail.bookings.map((b) => [b.id, b]));
  const spots = new Map<Spot, Booking[]>();
  const placed = new Set<string>();
  for (const d of detail.days ?? []) {
    const entries = d.order.map((id) => byId.get(id)).filter((b): b is Booking => b !== undefined);
    entries.forEach((b) => placed.add(b.id));
    spots.set(daySpot(d.day), entries);
  }
  // Anything the server didn't place (or no order at all): by time, as before.
  const rest = detail.bookings.filter((b) => b.scheduled && !placed.has(b.id)).sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  for (const b of rest) {
    const spot = daySpot(b.starts);
    spots.set(spot, [...(spots.get(spot) ?? []), b]);
  }
  const places = detail.bookings.filter((b) => b.kind === "activity" && !b.scheduled);
  const order = new Map((detail.places_order ?? []).map((id, i) => [id, i]));
  spots.set(PLACES, places.sort((a, b) => (order.get(a.id) ?? Infinity) - (order.get(b.id) ?? Infinity) || sortKey(a).localeCompare(sortKey(b))));
  return spots;
}

/** The entry a moved one goes right after, dropped on ``over`` (an entry, or the spot
 * itself: the end) above or below its middle. Null puts it first. */
export function afterFor(list: string[], moving: string, over: string, below: boolean): string | null {
  const ids = list.filter((id) => id !== moving);
  const i = ids.indexOf(over);
  if (i < 0) return ids.at(-1) ?? null;
  return below ? ids[i] : (ids[i - 1] ?? null);
}

/** The spots with one entry moved, as the page shows it while the server catches up. */
export function withMove(spots: Map<Spot, Booking[]>, moving: Booking, to: Spot, after: string | null): Map<Spot, Booking[]> {
  const next = new Map<Spot, Booking[]>();
  for (const [spot, list] of spots) next.set(spot, list.filter((b) => b.id !== moving.id));
  const list = [...(next.get(to) ?? [])];
  const at = after === null ? 0 : list.findIndex((b) => b.id === after) + 1;
  const day = dayOf(to);
  list.splice(at, 0, { ...moving, day, scheduled: day !== null, starts: day ?? moving.starts });
  next.set(to, list);
  return next;
}

type Drop = { over: string; spot: Spot; below: boolean } | null;
type Pending = { moving: Booking; to: Spot; after: string | null } | null;

type Arrange = {
  /** Plans can be dragged and moved. */
  on: boolean;
  spots: Map<Spot, Booking[]>;
  drop: Drop;
  dragging: string | null;
  move: (b: Booking, to: Spot, after: string | null) => Promise<void>;
  /** The keyboard on a plan's grip: pick up, up and down, put down, Escape. */
  key: (b: Booking, event: KeyboardEvent) => void;
  /** Picked up with the keyboard. */
  carrying: string | null;
  /** Focus left the grip: whatever was picked up stays where it was. */
  letGo: () => void;
};

const Context = createContext<Arrange | null>(null);

/** The entries in order and, under the provider, a way to move them. Without one (a
 * finished trip), the same order with nothing to move. */
export function useArrange(detail: TripDetail): Arrange {
  const arrange = useContext(Context);
  const spots = useMemo(() => spotsOf(detail), [detail]);
  return arrange ?? { on: false, spots, drop: null, dragging: null, carrying: null, move: async () => undefined, key: () => undefined, letGo: () => undefined };
}

const isEntry = (data: unknown): data is { entry: true; spot: Spot; booking: string } => typeof data === "object" && data !== null && "entry" in data;
const isZone = (data: unknown): data is { zone: true; spot: Spot; empty: boolean } => typeof data === "object" && data !== null && "zone" in data;

/** Over an entry if the pointer's on one; between entries in a list, the nearest of
 * them; on an empty day, the day. */
const collide: CollisionDetection = (args) => {
  // Not the plan being dragged; a flight shows on each day it leaves or lands, so
  // its spots are told apart by day.
  const others = args.droppableContainers.filter((c) => !(isEntry(c.data.current) && c.data.current.booking === args.active.id));
  const entries = others.filter((c) => isEntry(c.data.current));
  const zones = others.filter((c) => isZone(c.data.current));
  if (args.pointerCoordinates) {
    const hit = pointerWithin({ ...args, droppableContainers: entries });
    if (hit.length > 0) return hit;
    const zone = pointerWithin({ ...args, droppableContainers: zones })[0];
    if (!zone) return [];
    const spot = (zone.data?.droppableContainer.data.current as { spot: Spot }).spot;
    const inside = entries.filter((c) => (c.data.current as { spot: Spot }).spot === spot);
    return inside.length > 0 ? closestCenter({ ...args, droppableContainers: inside }) : [zone];
  }
  return [];
};

const middle = (r: ClientRect) => r.top + r.height / 2;

/** The day whose pill is under the pointer or finger, if any. Where the pointer
 * really is, not the drag's own sum: that shifts when the days slide under it. */
function pillAt(point: { x: number; y: number } | null): Spot | null {
  if (!point || typeof document.elementsFromPoint !== "function") return null;
  const pill = document.elementsFromPoint(point.x, point.y).find((n): n is HTMLElement => n instanceof HTMLElement && Boolean(n.dataset.pill));
  return (pill?.dataset.pill as Spot | undefined) ?? null;
}

/** Every place a plan can be put, top to bottom: first on each day and after each of
 * its entries, then the same in places to visit. */
export type Gap = { spot: Spot; after: string | null };
export function gapsFor(spots: Map<Spot, Booking[]>, days: string[], moving: string): Gap[] {
  const gaps: Gap[] = [];
  for (const spot of [...days.map(daySpot), PLACES]) {
    gaps.push({ spot, after: null });
    for (const b of spots.get(spot) ?? []) if (b.id !== moving) gaps.push({ spot, after: b.id });
  }
  return gaps;
}

/** Drag plans within and across days and from places to visit, with a long press on
 * phones, or pick one up with the keyboard and step it through the gaps. Each drop is
 * one call to move it; the page shows the new order straight away and the server's
 * once it answers. */
export function ArrangeProvider({ detail, days, on, onChange, children }: {
  detail: TripDetail;
  /** The itinerary's days, in order. */
  days: string[];
  on: boolean;
  /** Refreshes the trip; resolves once the server's order is back. */
  onChange: () => unknown;
  children: ReactNode;
}) {
  const base = useMemo(() => spotsOf(detail), [detail]);
  const [pending, setPending] = useState<Pending>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [drop, setDrop] = useState<Drop>(null);
  const [error, setError] = useState<string | null>(null);
  const [carry, setCarry] = useState<{ id: string; gap: number } | null>(null);
  const [said, setSaid] = useState("");
  // The server's answer arrives as a new trip: its order replaces the guess.
  useEffect(() => setPending(null), [detail]);
  // Where the pointer or finger is during a drag, for the day pills.
  const pointer = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => {
    if (!dragging) return;
    const onPointer = (e: PointerEvent | MouseEvent) => (pointer.current = { x: e.clientX, y: e.clientY });
    const onTouch = (e: TouchEvent) => {
      const t = e.touches[0];
      if (t) pointer.current = { x: t.clientX, y: t.clientY };
    };
    // Caught on the way down, before the drag's own handlers read it.
    const early = { passive: true, capture: true };
    window.addEventListener("pointermove", onPointer, early);
    window.addEventListener("mousemove", onPointer, early);
    window.addEventListener("touchmove", onTouch, early);
    return () => {
      window.removeEventListener("pointermove", onPointer, true);
      window.removeEventListener("mousemove", onPointer, true);
      window.removeEventListener("touchmove", onTouch, true);
      pointer.current = null;
    };
  }, [dragging]);
  const spots = useMemo(() => (pending ? withMove(base, pending.moving, pending.to, pending.after) : base), [base, pending]);
  const byId = useMemo(() => new Map(detail.bookings.map((b) => [b.id, b])), [detail.bookings]);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
  );

  const spotOf = (id: string): Spot | undefined => {
    for (const [spot, list] of spots) if (list.some((b) => b.id === id)) return spot;
    return undefined;
  };

  async function move(b: Booking, to: Spot, after: string | null) {
    const list = (spots.get(to) ?? []).map((e) => e.id);
    const from = spotOf(b.id);
    const before = list[list.indexOf(b.id) - 1] ?? null;
    if (from === to && before === after) return; // dropped where it was
    setError(null);
    setPending({ moving: b, to, after });
    try {
      await api(`/travel/bookings/${b.id}/move`, { method: "PUT", body: { day: dayOf(to), after } });
      await onChange();
      // Show what the server kept, even when it's the same order as before.
      setPending(null);
    } catch (e) {
      setPending(null);
      setError(e instanceof Error ? e.message : "Couldn't move that");
    }
  }

  const gaps = carry ? gapsFor(spots, days, carry.id) : [];
  const spotName = (spot: Spot) => (spot === PLACES ? "Ideas" : dayName(spot.slice(4)));
  const gapName = (g: Gap) => (g.after ? `after ${byId.get(g.after)?.title ?? "that"}, ${spotName(g.spot)}` : `first, ${spotName(g.spot)}`);

  function key(b: Booking, event: KeyboardEvent) {
    const k = event.key;
    if (!carry || carry.id !== b.id) {
      if (k !== " " && k !== "Enter") return;
      event.preventDefault();
      const all = gapsFor(spots, days, b.id);
      const spot = spotOf(b.id) ?? PLACES;
      const list = (spots.get(spot) ?? []).map((e) => e.id);
      const before = list[list.indexOf(b.id) - 1] ?? null;
      const gap = Math.max(0, all.findIndex((g) => g.spot === spot && g.after === before));
      setError(null);
      setCarry({ id: b.id, gap });
      setSaid(`Picked up ${b.title}. Up and down arrows to choose where, space to put it there, Escape to leave it.`);
      return;
    }
    if (k === "ArrowUp" || k === "ArrowDown") {
      event.preventDefault();
      const gap = Math.min(gaps.length - 1, Math.max(0, carry.gap + (k === "ArrowUp" ? -1 : 1)));
      setCarry({ ...carry, gap });
      setSaid(`${b.title}: ${gapName(gaps[gap])}.`);
    } else if (k === " " || k === "Enter") {
      event.preventDefault();
      const g = gaps[carry.gap];
      setCarry(null);
      setSaid(`Moved ${b.title} ${gapName(g)}.`);
      // The plan's grip keeps the focus in its new place.
      void move(b, g.spot, g.after).then(() =>
        window.requestAnimationFrame(() => document.getElementById(`entry-${b.id}`)?.querySelector<HTMLButtonElement>(".drag-handle")?.focus()),
      );
    } else if (k === "Escape" || k === "Tab") {
      if (k === "Escape") event.preventDefault();
      setCarry(null);
      setSaid(`${b.title} stays where it was.`);
    }
  }

  // Where the carried plan would land, marked like a drop.
  const carried: Drop = (() => {
    if (!carry) return null;
    const g = gaps[carry.gap];
    if (!g) return null;
    if (g.after) return { over: g.after, spot: g.spot, below: true };
    const first = (spots.get(g.spot) ?? []).find((e) => e.id !== carry.id);
    return first ? { over: first.id, spot: g.spot, below: false } : { over: g.spot, spot: g.spot, below: true };
  })();

  function where(event: DragMoveEvent | DragEndEvent): { spot: Spot; over: string; below: boolean } | null {
    // A day's pill (pinned above the days, so found by the pointer itself): the end
    // of that day.
    const pill = pillAt(pointer.current);
    if (pill) return { spot: pill, over: `pill:${pill}`, below: true };
    const { active, over } = event;
    const moved = active.rect.current.translated;
    if (!over || !moved) return null;
    const data = over.data.current;
    if (isEntry(data)) {
      if (data.booking === active.id) return null;
      return { spot: data.spot, over: data.booking, below: middle(moved) > middle(over.rect) };
    }
    if (isZone(data)) return { spot: data.spot, over: String(over.id), below: true };
    return null;
  }

  function onDragStart(event: DragStartEvent) {
    setError(null);
    setDragging(String(event.active.id));
  }

  function onDragMove(event: DragMoveEvent) {
    const at = where(event);
    const next: Drop = at ? { over: at.over, spot: at.spot, below: at.below } : null;
    if (next?.over !== drop?.over || next?.spot !== drop?.spot || next?.below !== drop?.below) setDrop(next);
  }

  function onDragEnd(event: DragEndEvent) {
    const at = where(event);
    const b = byId.get(String(event.active.id));
    setDragging(null);
    setDrop(null);
    if (!at || !b) return;
    const list = (spots.get(at.spot) ?? []).map((e) => e.id);
    void move(b, at.spot, afterFor(list, b.id, at.over, at.below));
  }

  const name = (id: string | number | undefined) => {
    if (id === undefined) return "";
    const b = byId.get(String(id).split("@")[0]);
    if (b) return b.title;
    const spot = String(id) as Spot;
    return spot === PLACES ? "Ideas" : `the day ${dayOf(spot)}`;
  };
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${name(active.id)}.`,
    onDragOver: ({ active, over }) => (over ? `${name(active.id)} is next to ${name(over.id)}.` : `${name(active.id)} is not over a day.`),
    onDragEnd: ({ active, over }) => (over ? `Moved ${name(active.id)} next to ${name(over.id)}.` : `${name(active.id)} stays where it was.`),
    onDragCancel: ({ active }) => `${name(active.id)} stays where it was.`,
  };

  const letGo = () => {
    if (carry) setCarry(null);
  };
  const value: Arrange = { on, spots, drop: carried ?? drop, dragging, move, key, carrying: carry?.id ?? null, letGo };
  const moving = dragging ? byId.get(dragging) : undefined;
  return (
    <Context.Provider value={value}>
      <DndContext
        sensors={sensors}
        collisionDetection={collide}
        // Up and down near the edges, never sideways (that would swipe to another day),
        // and not while held over a day's pill.
        autoScroll={{ threshold: { x: 0, y: 0.15 }, canScroll: () => !pillAt(pointer.current) }}
        onDragStart={onDragStart}
        onDragMove={onDragMove}
        onDragEnd={onDragEnd}
        onDragCancel={() => {
          setDragging(null);
          setDrop(null);
        }}
        accessibility={{
          announcements,
          screenReaderInstructions: { draggable: "To move a plan, press space, use the up and down arrows to choose where it goes, then press space again. Escape leaves it where it was." },
        }}
      >
        <p className="sr-only" aria-live="assertive" role="status" aria-label="Moving a plan">
          {said}
        </p>
        {error && (
          <p className="error-text arrange-error" role="alert">
            {error}
          </p>
        )}
        {children}
        <DragOverlay dropAnimation={null}>{moving && <div className="drag-chip">{moving.title}</div>}</DragOverlay>
      </DndContext>
    </Context.Provider>
  );
}

/** A plan's grip and the spot it can be dropped on. Flights, trains and hotels can
 * take a drop next to them, but stay where their booking puts them. */
export function useDragEntry(booking: Booking, spot: Spot | undefined) {
  const arrange = useContext(Context);
  const on = Boolean(arrange?.on) && spot !== undefined;
  const movable = on && booking.kind === "activity";
  // Ids by spot: a flight shows on each day it leaves or lands, and a hotel's
  // check-out line (no spot) shows it again on a later day and takes no part.
  const where = `${booking.id}@${spot ?? "none"}`;
  const drag = useDraggable({ id: movable ? booking.id : `fixed-${where}`, disabled: !movable });
  const drop = useDroppable({ id: where, disabled: !on, data: { entry: true, spot, booking: booking.id } });
  const here = on && arrange?.drop?.over === booking.id && arrange.drop.spot === spot;
  const mark = here ? (arrange?.drop?.below ? " drop-after" : " drop-before") : "";
  const ref = (node: HTMLElement | null) => {
    drag.setNodeRef(node);
    drop.setNodeRef(node);
  };
  const handle = movable ? (
    <button
      type="button"
      ref={drag.setActivatorNodeRef}
      className="drag-handle"
      aria-label={`Drag ${booking.title}`}
      {...drag.attributes}
      {...drag.listeners}
      aria-pressed={arrange?.carrying === booking.id}
      onKeyDown={(e) => arrange?.key(booking, e)}
      onBlur={() => arrange?.letGo()}
    >
      <span aria-hidden="true">⠿</span>
    </button>
  ) : null;
  const lifted = drag.isDragging || arrange?.carrying === booking.id;
  return { ref, handle, className: `${mark}${lifted ? " dragging" : ""}` };
}

/** A day or places to visit as a drop target: the end of the list, or the only place
 * on an empty day. */
export function DropZone({ spot, empty, children }: { spot: Spot; empty: boolean; children: ReactNode }) {
  const arrange = useContext(Context);
  const { setNodeRef } = useDroppable({ id: spot, disabled: !arrange?.on, data: { zone: true, spot, empty } });
  const over = arrange?.drop?.over === spot;
  return (
    <div ref={setNodeRef} className={`drop-zone${over ? " drop-over" : ""}${arrange?.dragging ? " drop-ready" : ""}`}>
      {children}
    </div>
  );
}

/** A day's pill as somewhere to drop a plan: onto the end of that day. ``over`` while
 * a plan is held above it; ``pill`` marks the element as the day's. */
export function useDayPill(spot: Spot) {
  const arrange = useContext(Context);
  return { pill: arrange?.on ? spot : undefined, over: Boolean(arrange?.dragging) && arrange?.drop?.over === `pill:${spot}` };
}

/** Moving without dragging: pick the day and what it comes after. */
export function MoveForm({ booking, days, spots, onDone }: { booking: Booking; days: string[]; spots: Map<Spot, Booking[]>; onDone: () => void }) {
  const arrange = useContext(Context);
  const from = booking.scheduled ? daySpot(booking.starts) : PLACES;
  const [to, setTo] = useState<Spot>(from);
  const there = (spots.get(to) ?? []).filter((b) => b.id !== booking.id);
  const current = (spots.get(from) ?? []).map((b) => b.id);
  const before = current[current.indexOf(booking.id) - 1] ?? "";
  const [after, setAfter] = useState<string>(before);
  async function save(event: FormEvent) {
    event.preventDefault();
    await arrange?.move(booking, to, after || null);
    onDone();
  }
  return (
    <form className="move-form" onSubmit={save} aria-label={`Move ${booking.title}`}>
      <label className="field">
        To
        <select
          className="input"
          value={to}
          onChange={(e) => {
            setTo(e.target.value as Spot);
            setAfter("");
          }}
        >
          {days.map((d) => (
            <option key={d} value={daySpot(d)}>
              {dayName(d)}
            </option>
          ))}
          <option value={PLACES}>Ideas (no day)</option>
        </select>
      </label>
      <label className="field">
        Where
        <select className="input" value={after} onChange={(e) => setAfter(e.target.value)}>
          <option value="">First</option>
          {there.map((b) => (
            <option key={b.id} value={b.id}>
              After {b.title}
            </option>
          ))}
        </select>
      </label>
      <span className="actions">
        <button type="submit" className="btn btn-small btn-primary">
          Move
        </button>
        <button type="button" className="btn btn-small" onClick={onDone}>
          Cancel
        </button>
      </span>
    </form>
  );
}

const NOTE_ICON: Record<DayNote["kind"], IconName> = { clash: "warning", order: "order", free: "clock", arrival: "landing" };

const minutesOf = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
const clock = (minutes: number) => `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** "1 h 30 min", "25 min". */
export function duration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/** Landing well before check-in, with the way from the airport counted once its
 * travel time is known: "Arrive around 10:45 (land 09:15, then 1 h 30 min) …". */
export function arrivalText(note: DayNote, hops: Hop[]): string {
  const [from, to] = note.ids;
  // From the airport to the hotel, counting from a stop beside the airport (picking
  // up a hire car) when there is one.
  const hop = hops.find((h) => h.end_id === to && !h.beside_airport && (h.start_id === from || hops.some((a) => a.beside_airport && a.start_id === from && a.end_id === h.start_id)));
  if (!note.start || !note.end || !hop || hop.minutes === null) return note.text;
  const there = minutesOf(note.start) + hop.minutes;
  const wait = minutesOf(note.end) - there;
  const fill = wait >= 30 ? `about ${duration(Math.round(wait / 15) * 15)} to fill, or ask about checking in early` : "about right for check-in";
  return `Arrive around ${clock(there)} (land ${note.start}, then ${duration(hop.minutes)}) · check-in from ${note.end} · ${fill}`;
}

/** What's worth a look on a day: things that overlap, plans out of time order,
 * landing well before check-in, and free time, with a way to fill it. */
export function DayNotes({ notes, hops = [], onFind }: { notes: DayNote[]; hops?: Hop[]; onFind?: (start: string | null) => void }) {
  if (notes.length === 0) return null;
  return (
    <ul className="day-notes" aria-label="Worth a look">
      {notes.map((n) => (
        <li key={`${n.kind}-${n.text}`} className={`day-note day-note-${n.kind}`}>
          <Icon name={NOTE_ICON[n.kind]} size={18} />
          <span className="wrap">{n.kind === "arrival" ? arrivalText(n, hops) : n.text}</span>
          {n.kind === "free" && onFind && (
            <button type="button" className="btn btn-ghost btn-small" onClick={() => onFind(n.start ?? null)}>
              Find something to do
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

const DAY_MS = 86400000;

/** "Wed 7 Apr": a day's short name, without the comma some languages put in. */
const shortDay = (iso: string) => dayName(iso).replace(",", "");

export type PickerDay = {
  iso: string;
  /** Day 1 is the trip's first day. */
  number: number;
  /** "Wed 7 Apr". */
  name: string;
  /** The day's own label, else a suggested one, else "Free day" when nothing is on it,
   * else empty. */
  label: string;
  /** Entries on the day, not counting the one being put there. */
  plans: number;
  /** The one being put is on this day now. */
  here: boolean;
  /** The entry it would go after: the last on the day. Null on an empty day. */
  last: string | null;
  /** In "Closest days": how far the day's places are from the idea, in metres. */
  metres?: number;
};

/** A day's circle on the map: the middle of its places, and how far they spread. */
export type Zone = Point & { radius: number };

/** Days with places within this far of an idea are "Closest days". */
export const CLOSE_METRES = 15_000;
/** A row says "Near Day 6" when the nearest day's places are this close. */
export const NEAR_METRES = 3_000;
const CLOSEST_SHOWN = 5;
const FREE_SHOWN = 6;

/** What's known about where each day is, worked out from the places Google Maps gave
 * us this visit (never stored) and the user's own pins. */
export type Nearby = {
  linked: Map<string, LinkedPlace>;
  stops: TripStop[];
  /** Each day's circle, for the days with something on the map. */
  zones: Map<string, Zone>;
  /** Each day's name: its own label, else the suggested one. */
  labels: Map<string, string>;
};

/** Where an entry is: its Google Maps place if linked, else the user's own pin. */
export function pointOf(booking: Pick<Booking, "id" | "lat" | "lng">, linked: Map<string, LinkedPlace>): Point | null {
  const place = linked.get(booking.id)?.place;
  if (place && typeof place.lat === "number" && typeof place.lng === "number") return { lat: place.lat, lng: place.lng };
  if (typeof booking.lat === "number" && typeof booking.lng === "number") return { lat: booking.lat, lng: booking.lng };
  return null;
}

function tripDays(trip: Pick<TripDetail["trip"], "start" | "end">): string[] {
  const days: string[] = [];
  for (let t = Date.parse(trip.start); t <= Date.parse(trip.end) && days.length < 120; t += DAY_MS) days.push(new Date(t).toISOString().slice(0, 10));
  return days;
}

/** Each day's circle: centred on the mean of its plans' places and pins, and wide
 * enough to hold them (at least 400 m, at most 3 km). */
export function dayZones(detail: Pick<TripDetail, "trip" | "bookings">, linked: Map<string, LinkedPlace>): Map<string, Zone> {
  const byDay = new Map<string, Point[]>();
  for (const b of detail.bookings) {
    if (b.kind !== "activity" || !b.scheduled) continue;
    const at = pointOf(b, linked);
    if (!at) continue;
    const day = b.day ?? b.starts;
    byDay.set(day, [...(byDay.get(day) ?? []), at]);
  }
  const zones = new Map<string, Zone>();
  for (const [day, points] of byDay) {
    const centre = { lat: points.reduce((n, p) => n + p.lat, 0) / points.length, lng: points.reduce((n, p) => n + p.lng, 0) / points.length };
    const spread = Math.max(...points.map((p) => metresBetween(centre, p)));
    zones.set(day, { ...centre, radius: Math.min(3000, Math.max(400, spread * 1.2)) });
  }
  return zones;
}

/** The trip's stops, day circles and day names, for ranking days near an idea. */
export function nearbyOf(detail: TripDetail, linked: Map<string, LinkedPlace>): Nearby {
  const spots = spotsOf(detail);
  const labels = new Map<string, string>();
  for (const iso of tripDays(detail.trip)) {
    const label = detail.trip.day_labels?.[iso] || suggestLabel(spots.get(daySpot(iso)) ?? [], linked);
    if (label) labels.set(iso, label);
  }
  return { linked, stops: stopsOf(detail), zones: dayZones(detail, linked), labels };
}

const sameStop = (a: TripStop | null, b: TripStop | null) => a !== null && b !== null && a.start === b.start && a.name === b.name;

/** The days a plan or idea can be put on, for the day picker: the day open on Plan
 * first (if it's a trip day), then every day of the trip, each with its label and how
 * much is on it. ``here`` is the day it is on now; ``lastIdea`` is where it would go
 * at the end of Ideas.
 *
 * With ``near`` and coordinates for the idea (its place or its own pin), the days are
 * also ranked: ``closest`` (places within 15 km, nearest first, with ``metres``),
 * ``free`` days in the stop it falls in, and the ``other`` stops' days. ``ranked``
 * says there are coordinates; without them the order is as it always was. */
export function pickerDays(
  detail: Pick<TripDetail, "trip" | "bookings" | "days" | "places_order">,
  booking: Pick<Booking, "id" | "scheduled" | "day" | "starts" | "lat" | "lng">,
  viewing: string | null,
  near?: Nearby,
): {
  viewing: PickerDay | null;
  days: PickerDay[];
  here: PickerDay | null;
  lastIdea: string | null;
  ranked: boolean;
  closest: PickerDay[];
  free: PickerDay[];
  /** The stop the idea falls in: where the nearest day is, else the one being viewed. */
  home: string | null;
  other: { name: string; days: PickerDay[] }[];
} {
  const { trip } = detail;
  const spots = spotsOf(detail);
  const current = booking.scheduled ? (booking.day ?? booking.starts) : null;
  const days: PickerDay[] = [];
  const first = Date.parse(trip.start);
  for (const iso of tripDays(trip)) {
    const ids = (spots.get(daySpot(iso)) ?? []).filter((b) => b.id !== booking.id).map((b) => b.id);
    days.push({
      iso,
      number: Math.round((Date.parse(iso) - first) / DAY_MS) + 1,
      name: shortDay(iso),
      label: trip.day_labels?.[iso] || near?.labels.get(iso) || (ids.length === 0 ? "Free day" : ""),
      plans: ids.length,
      here: iso === current,
      last: ids.at(-1) ?? null,
    });
  }
  const ideas = (spots.get(PLACES) ?? []).filter((b) => b.id !== booking.id);

  const stops = near?.stops ?? [];
  const point = near ? pointOf(booking, near.linked) : null;
  const metres = new Map<string, number>();
  if (near && point) for (const d of days) {
    const zone = near.zones.get(d.iso);
    if (zone) metres.set(d.iso, metresBetween(point, zone));
  }
  const byDistance = days.filter((d) => metres.has(d.iso)).sort((a, b) => metres.get(a.iso)! - metres.get(b.iso)!);
  const closest = byDistance
    .filter((d) => metres.get(d.iso)! <= CLOSE_METRES)
    .slice(0, CLOSEST_SHOWN)
    .map((d) => ({ ...d, metres: metres.get(d.iso) }));
  const home = (byDistance[0] ? stopOfDay(stops, byDistance[0].iso) : null) ?? (viewing ? stopOfDay(stops, viewing) : null);
  const free = days
    .filter((d) => d.plans === 0 && (!home || sameStop(stopOfDay(stops, d.iso), home)))
    .slice(0, FREE_SHOWN);
  const other = stops
    .filter((s) => home && !sameStop(s, home))
    .map((s) => ({ name: s.name, days: days.filter((d) => sameStop(stopOfDay(stops, d.iso), s)) }))
    .filter((o) => o.days.length > 0);
  return {
    viewing: days.find((d) => d.iso === viewing) ?? null,
    days,
    here: days.find((d) => d.here) ?? null,
    lastIdea: ideas.at(-1)?.id ?? null,
    ranked: point !== null,
    closest,
    free,
    home: home?.name ?? null,
    other,
  };
}

/** What an idea's row says about the plan: "On Day 3" once planned, "Near Day 6 · 1.2 km"
 * when the nearest day's places are within 3 km, else "Fits free Day 4" for an empty
 * day in the stop it falls in. */
export function ideaHint(detail: TripDetail, booking: Booking, near: Nearby, viewing: string | null = null): string | null {
  const picker = pickerDays(detail, booking, viewing, near);
  if (picker.here) return `On Day ${picker.here.number}`;
  const nearest = picker.closest[0];
  if (nearest?.metres !== undefined && nearest.metres <= NEAR_METRES) return `Near Day ${nearest.number} · ${distance(nearest.metres)}`;
  const free = picker.free[0];
  return free ? `Fits free Day ${free.number}` : null;
}

/** Puts a plan or idea on a day (or back in Ideas): a sheet from the bottom on phones,
 * a dialog on desktop. A day takes it at the end. ``viewing``: the day open on Plan. */
export function DayPickerSheet({ detail, booking, viewing, onClose }: { detail: TripDetail; booking: Booking; viewing: string | null; onClose: () => void }) {
  const { move } = useArrange(detail);
  const sheet = useRef<HTMLElement>(null);
  const linked = useLinkedPlaces();
  const picker = useMemo(() => pickerDays(detail, booking, viewing, nearbyOf(detail, linked)), [detail, booking, viewing, linked]);

  // The first day is focused as the sheet opens, and the focus goes back when it closes.
  useEffect(() => {
    const before = document.activeElement;
    sheet.current?.querySelector<HTMLButtonElement>(".day-option")?.focus();
    return () => {
      if (before instanceof HTMLElement) before.focus();
    };
  }, []);

  useEffect(() => {
    const key = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  // The sheet closes at once; the provider keeps the move going and shows what the
  // server answers.
  function put(to: Spot, after: string | null) {
    void move(booking, to, after);
    onClose();
  }

  const option = (d: PickerDay) => (
    <li key={d.iso}>
      <button type="button" className="day-option" aria-current={d.here ? "true" : undefined} onClick={() => put(daySpot(d.iso), d.last)}>
        <span className="day-option-number" aria-hidden="true">
          {d.number}
        </span>
        <span className="wrap">
          <strong>
            Day {d.number} · {d.name}
          </strong>
          {d.label && <span className="caption">{d.label}</span>}
        </span>
        {d.here && <span className="badge badge-out">Here now</span>}
        {(d.metres !== undefined || d.plans > 0) && (
          <span className="caption day-option-count">
            {[d.metres !== undefined ? distance(d.metres) : null, d.plans > 0 ? `${d.plans} ${d.plans === 1 ? "plan" : "plans"}` : null].filter(Boolean).join(" · ")}
          </span>
        )}
      </button>
    </li>
  );

  return (
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section ref={sheet} className="add-sheet day-picker" role="dialog" aria-modal="true" aria-labelledby="day-picker-title">
        <div className="add-sheet-head">
          <h2 id="day-picker-title">Put on a day</h2>
          <button type="button" className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="day-picker-for">{booking.title}</p>
        {picker.ranked && picker.closest.length > 0 && (
          <section aria-labelledby="day-picker-closest">
            <h3 id="day-picker-closest" className="day-picker-heading">
              Closest days
            </h3>
            <ul className="day-options">{picker.closest.map(option)}</ul>
          </section>
        )}
        {/* Already offered among the closest days: not again under Viewing. */}
        {picker.viewing && !(picker.ranked && picker.closest.some((d) => d.iso === picker.viewing?.iso)) && (
          <section aria-labelledby="day-picker-viewing">
            <h3 id="day-picker-viewing" className="day-picker-heading">
              Viewing
            </h3>
            <ul className="day-options">{option(picker.viewing)}</ul>
          </section>
        )}
        {picker.ranked && picker.free.length > 0 && (
          <section aria-labelledby="day-picker-free">
            <h3 id="day-picker-free" className="day-picker-heading">
              Free days
            </h3>
            <ul className="day-options">{picker.free.map(option)}</ul>
          </section>
        )}
        {picker.ranked &&
          picker.other.map((o, i) => (
            <section key={`${o.name}-${i}`} aria-label={`In ${o.name} instead`}>
              <h3 className="day-picker-heading">In {o.name} instead</h3>
              <ul className="day-options">{o.days.map(option)}</ul>
            </section>
          ))}
        <section aria-labelledby="day-picker-all">
          <h3 id="day-picker-all" className="day-picker-heading">
            All days
          </h3>
          <ul className="day-options">{picker.days.map(option)}</ul>
        </section>
        {picker.here ? (
          <button type="button" className="btn btn-soft" onClick={() => put(PLACES, picker.lastIdea)}>
            Take it off Day {picker.here.number}
          </button>
        ) : (
          <button type="button" className="btn" onClick={onClose}>
            Keep it as an idea
          </button>
        )}
      </section>
    </div>
  );
}
