import { type FormEvent, Fragment, type ReactNode, useId, useRef, useState } from "react";

import { api, type Booking, type Hop, type Trip, type TripDetail } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { formatMoney } from "../format";
import { type AddPreset } from "./TripAdd";
import { BookedWith, BookingLines, KindLines, OpenLink, landingOn, landsOnly, leavingOn, legTimes, onlyNamesDay, repeatsTitle, sortKey, suggestLabel, todayIso, useHome } from "./TripBits";
import { DayCarousel } from "./DayCarousel";
import { dayIsFree } from "./TripStage";
import { DayNotes, DayPickerSheet, DropZone, type Spot, daySpot, useArrange, useDragEntry } from "./TripArrange";
import { DayHops, HopLine } from "./TripMap";
import { LinkPlaceHint, linkable, PlaceLine, PlaceWarning, useLinkedPlaces } from "./TripPlaces";
import { StopsRow, StopsSheet, pillMark, pillTitle } from "./TripStops";
import { EntryEditor } from "./TripEntry";
import { DayWeather, PlaceActions, StayStrip, useTripWeather } from "./TripDayHead";
import { Button } from "../components/ui";

const KIND_ICON: Record<Booking["kind"], IconName> = { flight: "flight", hotel: "stay", rail: "train", activity: "place" };

export function BookingRow({ booking, children }: { booking: Booking; children?: ReactNode }) {
  return (
    <li className="run-row">
      <span className="wrap">
        <Icon name={KIND_ICON[booking.kind]} size={18} className="icon-inline" />
        <strong>{booking.title}</strong>
        {booking.provider && booking.kind !== "hotel" && <span className="caption"> · {booking.provider}</span>}
        <br />
        <BookingLines booking={booking} />
      </span>
      {booking.cost && (
        <span className="num">
          {formatMoney(booking.cost)}
          {!booking.logged && <span className="caption"> not logged</span>}
        </span>
      )}
      {children}
    </li>
  );
}

export const DAY_MS = 86400000;
const isoDay = (t: number) => new Date(t).toISOString().slice(0, 10);
const dayPill = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso));

/** Every day from the trip's first to its last, plus any day outside it with an entry. */
export function tripDays(detail: TripDetail): string[] {
  const days = new Set<string>();
  for (let t = Date.parse(detail.trip.start); t <= Date.parse(detail.trip.end); t += DAY_MS) days.add(isoDay(t));
  for (const b of detail.bookings) if (b.scheduled) days.add(b.starts);
  return [...days].sort();
}

/** One day's label ("Busan"): a pencil that opens its form, edited in place. With no
 * label saved, the form opens with the ``suggested`` one, and saving keeps it. */
function DayLabel({ trip, iso, suggested, onChange }: { trip: Trip; iso: string; suggested: string | null; onChange: () => void }) {
  const current = (trip.day_labels ?? {})[iso] ?? "";
  const start = current || suggested || "";
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(start);
  const inTrip = iso >= trip.start && iso <= trip.end;
  if (!inTrip) return null;
  async function save(event: FormEvent) {
    event.preventDefault();
    await api(`/travel/trips/${trip.id}/days/${iso}`, { method: "PUT", body: { label: text.trim() || null } }).catch(() => undefined);
    setEditing(false);
    onChange();
  }
  if (editing) {
    return (
      <form className="day-label-form" onSubmit={save} aria-label={`Label for ${dayPill(iso)}`}>
        <input className="input" value={text} maxLength={40} autoFocus onChange={(e) => setText(e.target.value)} placeholder="City or plan, e.g. Busan" aria-label="Name for this day" />
        <Button type="submit" variant="secondary" size="sm">
          Save
        </Button>
        <Button variant="text" size="sm" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </form>
    );
  }
  return (
    <button
      type="button"
      className="day-edit"
      onClick={() => {
        setText(start);
        setEditing(true);
      }}
      aria-label="Name this day"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z" />
        <path d="M13.5 6.5l4 4" />
      </svg>
    </button>
  );
}

/** A small padlock on flights, hotels and trains: booked, so the time isn't ours to move. */
function Lock() {
  return (
    <svg className="entry-lock" role="img" aria-label="Booked, fixed time" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

/** A tap that moves further than this between pressing and lifting was a scroll or a swipe. */
const TAP_SLOP = 8;

/** The open part of a plan row: where it is, its place on Google Maps, link, note and
 * booking reference, with Change (which opens the editor; Remove stays there). */
function EntryOpen({ booking, id, onEdit }: { booking: Booking; id: string; onEdit: () => void }) {
  const address = booking.address && !repeatsTitle(booking.address, booking.title) ? booking.address : null;
  const note = booking.note && !onlyNamesDay(booking.note) ? booking.note : null;
  return (
    <div id={id} className="entry-open">
      {address && <p className="caption entry-address">{address}</p>}
      <PlaceLine booking={booking} />
      <OpenLink booking={booking} />
      {note && <p className="caption entry-note">{note}</p>}
      <BookedWith booking={booking} />
      <div className="entry-open-actions">
        {/* A taxi driver's address, and the Maps app: for a hotel too (its strip is on the day). */}
        {booking.address && <PlaceActions name={booking.hotel ?? booking.title} address={booking.address} />}
        <Button variant="text" size="sm" onClick={onEdit} aria-label={`Change ${booking.title}`}>
          <Icon name="edit" size={16} />
          Change
        </Button>
      </div>
    </div>
  );
}

/** A plan row opens before it edits. The whole row is one button laid over it (``toggle``,
 * so links and buttons inside stay their own), which opens and folds ``panel``; Change in
 * the panel opens the editor. A press that moved, or landed while the days were scrolling,
 * was a swipe and does nothing. Each row opens and folds on its own. Without ``onEdit``
 * (a read-only line) there is neither. */
function useRowOpen(booking: Booking, onEdit?: () => void) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const down = useRef<{ x: number; y: number; scrolling: boolean } | null>(null);
  if (!onEdit) return { toggle: null, panel: null };
  const toggle = (
    <button
      type="button"
      className="entry-tap"
      aria-label={`Open ${booking.title}`}
      aria-expanded={open}
      aria-controls={open ? id : undefined}
      onPointerDown={(e) => {
        down.current = { x: e.clientX, y: e.clientY, scrolling: Boolean(e.currentTarget.closest("[data-scrolling]")) };
      }}
      onPointerCancel={() => {
        down.current = null;
      }}
      onClick={(e) => {
        const start = down.current;
        down.current = null;
        if (start && (start.scrolling || Math.hypot(e.clientX - start.x, e.clientY - start.y) > TAP_SLOP)) return;
        if (e.currentTarget.closest("[data-scrolling]")) return;
        setOpen(!open);
      }}
    />
  );
  return { toggle, panel: open ? <EntryOpen booking={booking} id={id} onEdit={onEdit} /> : null };
}

/** A flight or train as a slim strip, a hotel check-in or check-out, or a numbered stop.
 * ``onEdit``: tapping the entry opens it, and Change there opens it to change. */
function TimelineEntry({ booking, iso, stop, spot, onEdit }: { booking: Booking; iso: string; stop: number | null; spot?: Spot; onEdit?: () => void }) {
  const drag = useDragEntry(booking, spot);
  const { toggle, panel } = useRowOpen(booking, onEdit);
  if (booking.kind === "hotel") {
    const out = booking.check_out === iso && booking.check_in !== iso;
    return (
      <li ref={drag.ref} className={`timeline-strip entry-row${drag.className}`} id={out ? undefined : `entry-${booking.id}`}>
        {!out && toggle}
        <Icon name="stay" size={18} />
        <span className="wrap">
          <strong>{booking.hotel ?? booking.title}</strong>
          {!out && <br />}
          {!out && <KindLines booking={booking} noTime glance />}
        </span>
        <span className={`badge ${out ? "badge-pending" : "badge-in"}`}>{out ? "Check out" : "Check in"}</span>
        <Lock />
        {!out && panel}
      </li>
    );
  }
  if (landsOnly(booking, iso)) {
    // The day after an overnight flight or train: where and when it lands.
    const legs = landingOn(booking, iso);
    const last = legs[legs.length - 1];
    const from = legs[0];
    return (
      <li ref={drag.ref} className={`timeline-strip timeline-landing entry-row${drag.className}`} id={`land-${booking.id}`}>
        {toggle}
        <Icon name={booking.kind === "flight" ? "landing" : "train"} size={18} />
        <span className="wrap">
          <strong>
            {booking.kind === "flight" ? "Land" : "Arrive"} {last.destination ?? ""} {last.arrives?.slice(11, 16)}
          </strong>
          <br />
          <span className="caption">
            {[from.number, booking.provider].filter(Boolean).join(" · ")}
            {from.origin && ` from ${from.origin}`}
            {from.departs && `, left ${dayPill(from.departs.slice(0, 10))} ${from.departs.slice(11, 16)}`}
          </span>
        </span>
        <Lock />
        {panel}
      </li>
    );
  }
  if ((booking.kind === "flight" || booking.kind === "rail") && iso !== booking.starts) {
    // A later leg of the same booking, such as the flight home.
    const legs = leavingOn(booking, iso);
    return (
      <li ref={drag.ref} className={`timeline-strip entry-row${drag.className}`} id={`leave-${booking.id}-${iso}`}>
        {toggle}
        <Icon name={KIND_ICON[booking.kind]} size={18} />
        <span className="wrap">
          {legs.map((l, n) => (
            <span key={n}>
              <strong>{[l.number, [l.origin, l.destination].filter(Boolean).join(" → ")].filter(Boolean).join(" ")}</strong>
              {booking.provider && <span className="caption"> · {booking.provider}</span>}
              <br />
              <span className="caption">{legTimes(l.departs, l.arrives)}</span>
            </span>
          ))}
        </span>
        <Lock />
        {panel}
      </li>
    );
  }
  if (booking.kind === "flight" || booking.kind === "rail") {
    return (
      <li ref={drag.ref} className={`timeline-strip entry-row${drag.className}`} id={`entry-${booking.id}`}>
        {toggle}
        <Icon name={KIND_ICON[booking.kind]} size={18} />
        <span className="wrap">
          <strong>{booking.title}</strong>
          {booking.provider && <span className="caption"> · {booking.provider}</span>}
          <br />
          <KindLines booking={booking} noTime glance />
        </span>
        {booking.cost && <span className="num">{formatMoney(booking.cost)}</span>}
        <Lock />
        {panel}
      </li>
    );
  }
  return (
    <li ref={drag.ref} className={`timeline-stop entry-row${drag.className}`} id={`entry-${booking.id}`}>
      {toggle}
      {drag.handle}
      <span className="stop-number" aria-hidden="true">
        {stop}
      </span>
      <span className="wrap">
        <strong>{booking.title}</strong>
        {booking.at && (
          <span className="time-pill">
            {booking.at}
            {booking.ends_at && `–${booking.ends_at}`}
          </span>
        )}
        {booking.category && <span className="caption"> · {booking.category}</span>}
        {/* Open, the plan shows it with the place's details. */}
        {!panel && <PlaceWarning booking={booking} />}
      </span>
      {booking.cost && <span className="num">{formatMoney(booking.cost)}</span>}
      {panel}
    </li>
  );
}

/** The trip day by day: a strip of days to jump between, each day's name, its
 * flights, trains and hotel check-ins and check-outs, and numbered plans in time order.
 * The day in view is the page's (``day``), which the map and the other tabs share. */
export function Itinerary({ detail, day, onDay, onChange, onAdd, onIdeas }: {
  detail: TripDetail;
  day: string;
  onDay: (iso: string) => void;
  onChange: () => void;
  onAdd: (preset: AddPreset) => void;
  /** Opens the Ideas tab, for filling an empty day. */
  onIdeas: () => void;
}) {
  const home = useHome();
  const [editing, setEditing] = useState<string | null>(null);
  const [picking, setPicking] = useState<Booking | null>(null);
  const [stopsOpen, setStopsOpen] = useState(false);
  const linked = useLinkedPlaces();
  const arrange = useArrange(detail);
  const notesOf = (iso: string) => detail.days?.find((x) => x.day === iso)?.notes ?? [];
  const addressOf = (id: string) => detail.bookings.find((b) => b.id === id)?.address ?? null;
  const scheduled = detail.bookings.filter((b) => b.scheduled);
  const sorted = [...scheduled].sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  const stays = sorted.filter((b) => b.kind === "hotel" && b.check_in && b.check_out);
  // The stay for the night that starts on a day (its check-in night too).
  const sleepingAt = (d: string) => stays.find((b) => (b.check_in ?? "") <= d && d < (b.check_out ?? ""));
  const weather = useTripWeather(detail.trip);
  const today = todayIso();
  const checkingOut = (d: string) => stays.filter((b) => b.check_out === d);
  const days = tripDays(detail);
  const dayNumber = (iso: string) => Math.round((Date.parse(iso) - Date.parse(detail.trip.start)) / DAY_MS) + 1;
  const inTrip = (iso: string) => iso >= detail.trip.start && iso <= detail.trip.end;
  const homeless = new Set(detail.ready.nights_without_stay);
  const dayLabel = (iso: string) => {
    const n = dayNumber(iso);
    const when = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso));
    return n >= 1 && n <= detail.trip.days ? `Day ${n} · ${when}` : when;
  };
  // The day panel's heading: "Today · Day 3 of 6 · Wed, 21 Oct".
  const dayHeading = (iso: string) => {
    const n = dayNumber(iso);
    const when = dayLabel(iso).replace(/^Day \d+ · /, "");
    const where = n >= 1 && n <= detail.trip.days ? `Day ${n} of ${detail.trip.days} · ${when}` : when;
    return iso === today ? `Today · ${where}` : where;
  };

  // A plan carried by keyboard to another day takes the carousel with it.
  const carriedTo = arrange.carrying ? arrange.drop?.spot : undefined;
  const following = carriedTo?.startsWith("day:") ? carriedTo.slice(4) : null;

  return (
    <>
    <section id="itinerary" className="card itinerary-card" aria-label="Itinerary">
      <StopsRow detail={detail} viewing={day} onDay={onDay} onEdit={() => setStopsOpen(true)} />
      <DayCarousel days={days} value={day} onPick={onDay} follow={following} pill={dayPill} mark={(d) => pillMark(detail, d)} markTitle={(d) => pillTitle(detail, d)} name={dayLabel}>
        {(d, near) => {
        const entries = arrange.spots.get(daySpot(d)) ?? [];
        const outs = checkingOut(d).filter((b) => b.starts !== d);
        const n = dayNumber(d);
        const ends = d === detail.trip.start || d === detail.trip.end;
        const free = dayIsFree(detail, d);
        const dot = !inTrip(d) ? "day-dot-out" : ends ? "day-dot-end" : free ? "day-dot-empty" : "day-dot-planned";
        const named = (detail.trip.day_labels ?? {})[d];
        // What the day's places suggest it is called, until the user names it.
        const suggested = inTrip(d) && !named ? suggestLabel(entries, linked) : null;
        const count = entries.length + outs.length;
        const stay = sleepingAt(d);
        const addLabel = inTrip(d) ? `Add to Day ${n}` : `Add to ${dayPill(d)}`;
        return (
          <div key={d} id={`day-${d}`} className="itinerary-day">
            <div className="day-rail" aria-hidden="true">
              <span className={`day-dot ${dot}`}>{inTrip(d) ? n : "·"}</span>
              <span className="day-line" />
            </div>
            <div className="day-body">
              <div className="day-head">
                <h3 className="day-title">
                  <span className="day-when">{dayHeading(d)}</span>
                  <span className="day-name">{named || suggested || (free ? "Free day" : `${count} ${count === 1 ? "plan" : "plans"}`)}</span>
                  {suggested && <span className="chip suggest-chip">Suggested</span>}
                </h3>
                <DayLabel trip={detail.trip} iso={d} suggested={suggested} onChange={onChange} />
              </div>
              <DayWeather weather={weather} day={d} />
              {stay && <StayStrip booking={stay} />}
              {homeless.has(d) && (
                <p className="gap-line">
                  <span>Nowhere to stay this night yet</span>
                  <Button variant="secondary" size="sm" onClick={() => onAdd({ kind: "hotel", day: d })} aria-label={`Add a place to stay on ${dayPill(d)}`}>
                    Add
                  </Button>
                </p>
              )}
              <DayHops tripId={detail.trip.id} day={d} enabled={Boolean(detail.routes) && detail.places} soon={near}>
                {(hops) => {
                  // Counted here: this renders again when the travel times arrive.
                  let stop = 0;
                  const shownIds = new Set(entries.map((b) => b.id));
                  // Landing and collecting a hire car at the airport isn't a trip of its own.
                  const drawn = hops.filter((h) => !h.beside_airport);
                  // Each hop above where it goes; one back to somewhere earlier in the day
                  // (tonight's hotel, checked into before going out) at the end, saying so.
                  const at = new Map(entries.map((b, i) => [b.id, i]));
                  const back = (h: Hop) => {
                    const from = at.get(h.start_id);
                    const to = at.get(h.end_id);
                    return to !== undefined && from !== undefined && from >= to;
                  };
                  const into = (b: Booking) => drawn.filter((h) => h.end_id === b.id && !back(h));
                  const after = drawn.filter((h) => !shownIds.has(h.end_id) || back(h));
                  return (
                    <>
                    <DayNotes
                      notes={notesOf(d)}
                      hops={hops}
                      onFind={inTrip(d) ? (start) => onAdd({ kind: "activity", day: d, at: start ?? undefined, find: true }) : undefined}
                    />
                    <DropZone spot={daySpot(d)} empty={entries.every((b) => b.id === arrange.dragging)}>
                    <ul className="timeline" aria-label={dayLabel(d)}>
                      {outs.map((b) => (
                        <TimelineEntry key={`out-${b.id}`} booking={b} iso={d} stop={null} />
                      ))}
                      {entries.map((b, i) => {
                        if (b.kind === "activity") stop += 1;
                        // A plan with no place breaks the chain of travel times: say so, once, where one
                        // would go (after it, or before it when it is the day's last).
                        const unlinked = Boolean(detail.routes) && linkable(b) && !b.place_id && entries.some((o) => o.id !== b.id && linkable(o));
                        const hint = unlinked ? <LinkPlaceHint booking={b} /> : null;
                        const last = i === entries.length - 1;
                        const hopsIn = into(b).map((h) => <HopLine key={`hop-${h.start_id}-${h.end_id}`} tripId={detail.trip.id} day={d} hop={h} addressOf={addressOf} />);
                        return editing === b.id ? (
                          <Fragment key={b.id}>
                            {hopsIn}
                            <li>
                              <EntryEditor
                                trip={detail.trip}
                                home={home}
                                entry={b}
                                onDone={(saved) => {
                                  setEditing(null);
                                  if (saved) onChange();
                                }}
                                onMove={
                                  arrange.on && b.kind === "activity"
                                    ? () => {
                                        // The editor closes as the day picker opens, so the entry isn't left open on its new day.
                                        setEditing(null);
                                        setPicking(b);
                                      }
                                    : undefined
                                }
                              />
                            </li>
                          </Fragment>
                        ) : (
                          <Fragment key={b.id}>
                            {hopsIn}
                            {last && hint}
                            <TimelineEntry booking={b} iso={d} stop={b.kind === "activity" ? stop : null} spot={daySpot(d)} onEdit={() => setEditing(b.id)} />
                            {!last && hint}
                          </Fragment>
                        );
                      })}
                      {after.map((h) => (
                        <HopLine key={`hop-${h.start_id}-${h.end_id}`} tripId={detail.trip.id} day={d} hop={h} addressOf={addressOf} back={back(h)} />
                      ))}
                    </ul>
                    {free && entries.length === 0 && (
                      <p className="caption">
                        Nothing planned yet. Fill it from your{" "}
                        <button type="button" className="link-btn" onClick={onIdeas} aria-label="Open Ideas">
                          ideas
                        </button>
                        , or leave it open.
                      </p>
                    )}
                    </DropZone>
                    </>
                  );
                }}
              </DayHops>
              <Button variant="text" size="sm" onClick={() => onAdd({ kind: "activity", day: d })}>
                <Icon name="plus" size={16} />
                {addLabel}
              </Button>
              {inTrip(d) && (detail.places || detail.ideas) && (
                <Button variant="text" size="sm" onClick={() => onAdd({ kind: "activity", day: d, near: true })} aria-label={`Find ideas near here, Day ${n}`}>
                  <Icon name="find" size={16} />
                  Find ideas near here
                </Button>
              )}
            </div>
          </div>
        );
        }}
      </DayCarousel>
      <p className="caption">Times are local.</p>
    </section>
    {/* Outside the card: a card's own stacking would put the sheet under the tab bar on a phone. */}
    {picking && <DayPickerSheet detail={detail} booking={picking} viewing={day} onClose={() => setPicking(null)} />}
    {stopsOpen && <StopsSheet trip={detail.trip} detail={detail} onClose={() => setStopsOpen(false)} onSaved={onChange} />}
    </>
  );
}
