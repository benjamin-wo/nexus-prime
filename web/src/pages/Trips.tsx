import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type CSSProperties, type FormEvent, Fragment, type ReactNode, type RefObject, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api, type Booking, type Hop, type ScreenshotRead, type Trip, type TripDetail } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { Sheet } from "../components/Sheet";
import { base64 } from "../files";
import { formatMoney } from "../format";
import { ResearchList } from "./Research";
import { type AddPreset, AddSheet } from "./TripAdd";
import { BookedWith, BookingLines, KindLines, OpenLink, PhotoCredit, TripCard, TripRow, coverStyle, day, isMember, landingOn, landsOnly, leavingOn, legTimes, onlyNamesDay, repeatsTitle, sharedBy, sortKey, suggestLabel, todayIso, tripWhen, useAppRole, useHome } from "./TripBits";
import { DayCarousel } from "./DayCarousel";
import { type Fix, type Go, type Stage, dayIsFree, nextUp, stageOf } from "./TripStage";
import { ArrangeProvider, DayNotes, DayPickerSheet, DropZone, type Spot, daySpot, useArrange, useDragEntry } from "./TripArrange";
import { DayHops, GETTING_AROUND, HopLine, MapAppPicker, TripMap } from "./TripMap";
import { PlaceLine, PlaceWarning, TripPlacesProvider, useLinkedPlaces } from "./TripPlaces";
import { StopsRow, StopsSheet, pillMark, pillTitle } from "./TripStops";
import { EntryEditor } from "./TripEntry";
import { IdeasTab, listOf } from "./TripIdeas";
import { MoneyTab, NameChips } from "./TripMoney";
import { ActivityLine } from "./TripActivity";
import { PrepTab } from "./TripPrep";
import { TripFaces, hasMembers, useMembers } from "./TripPeople";
import { ShareSheet } from "./TripShare";
import { TodayView } from "./TripToday";

export { tripWhen };

type FormRow = { name: string; amount: string };

/** Add or change a trip. Money is in the home currency; the trip's own currency is
 * what's spent there, which is how its spending is found. */
// Common travel currencies, offered as the trip's currency is typed.
const CURRENCIES: [string, string][] = [
  ["JPY", "Japan"], ["KRW", "South Korea"], ["THB", "Thailand"], ["MYR", "Malaysia"], ["IDR", "Indonesia"],
  ["VND", "Vietnam"], ["PHP", "Philippines"], ["TWD", "Taiwan"], ["HKD", "Hong Kong"], ["CNY", "China"],
  ["AUD", "Australia"], ["NZD", "New Zealand"], ["USD", "United States"], ["EUR", "Euro area"], ["GBP", "United Kingdom"],
  ["CHF", "Switzerland"], ["SGD", "Singapore"], ["INR", "India"], ["AED", "UAE"], ["CAD", "Canada"],
];

function TripForm({ initial, home, onDone }: { initial?: Trip; home: string; onDone: (trip?: Trip) => void }) {
  const [destination, setDestination] = useState(initial?.destination ?? "");
  const [start, setStart] = useState(initial?.start ?? "");
  const [end, setEnd] = useState(initial?.end ?? "");
  const [currency, setCurrency] = useState(initial?.currency ?? "");
  const [budget, setBudget] = useState(initial?.budget?.amount ? String(Number(initial.budget.amount)) : "");
  const [companions, setCompanions] = useState<string[]>(initial?.companions ?? []);
  const [setAside, setSetAside] = useState(initial?.set_aside ? String(Number(initial.set_aside.amount)) : "");
  const [planned, setPlanned] = useState<FormRow[]>(
    Object.entries(initial?.planned ?? {}).map(([name, m]) => ({ name, amount: String(Number(m.amount)) })),
  );
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A new trip's currency comes from where it goes, until it's picked by hand.
  const [picking, setPicking] = useState(Boolean(initial));
  // What the lookup said, and for which place: only an answer for what's typed now counts.
  const [found, setFound] = useState<{ place: string; currency: string | null; country: string | null } | null>(null);
  const place = destination.trim();
  useEffect(() => {
    if (initial || picking || place.length < 2) return;
    const timer = window.setTimeout(() => {
      api<{ currency: string | null; country: string | null }>(`/travel/currency?place=${encodeURIComponent(place)}`)
        .then((answer) => {
          setFound({ place, ...answer });
          setCurrency(answer.currency ?? "");
        })
        .catch(() => setFound({ place, currency: null, country: null }));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [place, initial, picking]);
  const answered = found !== null && found.place === place;
  // Asked by hand when chosen, or when the place's currency isn't known; never while looking.
  const askCurrency = picking || (answered && !found.currency);
  const looking = !picking && !initial && place.length >= 2 && !answered;

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const body = {
      destination: destination.trim(),
      start,
      end,
      currency: currency.trim().toUpperCase(),
      budget: budget.trim() || null,
      companions,
      set_aside: setAside.trim() || null,
      planned: Object.fromEntries(planned.filter((p) => p.name.trim() && p.amount.trim()).map((p) => [p.name.trim(), p.amount.trim()])),
      notes: notes.trim() || null,
    };
    try {
      const saved = initial
        ? await api<Trip>(`/travel/trips/${initial.id}`, { method: "PUT", body })
        : await api<Trip>("/travel/trips", { method: "POST", body });
      onDone(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the trip");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="trip-form" onSubmit={save} aria-label={initial ? "Change the trip" : "Add a trip"}>
      <label className="field">
        Where
        <input className="input" value={destination} maxLength={80} onChange={(e) => setDestination(e.target.value)} placeholder="Tokyo" required />
      </label>
      <div className="trip-form-row">
        <label className="field">
          From
          <input
            className="input"
            type="date"
            value={start}
            onChange={(e) => {
              setStart(e.target.value);
              if (!end || end < e.target.value) setEnd(e.target.value);
            }}
            required
          />
        </label>
        <label className="field">
          To
          <input className="input" type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} required />
        </label>
        {askCurrency && (
        <label className="field">
          Currency there
          <input
            className="input"
            value={currency}
            maxLength={3}
            list="trip-currencies"
            onChange={(e) => setCurrency(e.target.value)}
            placeholder="JPY"
            required
          />
          <datalist id="trip-currencies">
            {CURRENCIES.map(([code, where]) => (
              <option key={code} value={code}>
                {where}
              </option>
            ))}
          </datalist>
        </label>
        )}
      </div>
      {looking && (
        <p className="caption currency-line" role="status">
          Finding the currency for {place}…
        </p>
      )}
      {!askCurrency && !looking && currency && (
        <p className="caption currency-line">
          Spending in {currency}
          {found?.country && ` (${found.country})`}{" "}
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setPicking(true)}>
            Change
          </button>
        </p>
      )}
      <details className="more-options" open={Boolean(initial)}>
        <summary>{initial ? "Budget, people and notes" : "Budget, who's going and notes (optional)"}</summary>
      <div className="trip-form-row">
        <label className="field">
          Budget ({home})
          <input className="input" inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="Optional" />
        </label>
        <label className="field">
          Set aside each payday ({home})
          <input className="input" inputMode="decimal" value={setAside} onChange={(e) => setSetAside(e.target.value)} placeholder="Optional" />
        </label>
      </div>
      <fieldset className="field-group">
        <legend>Who's going</legend>
        <NameChips names={companions} onChange={setCompanions} addOnBlur />
      </fieldset>
      <fieldset className="trip-planned">
        <legend>Planned by category ({home}, optional)</legend>
        {planned.map((row, n) => (
          <div key={n} className="trip-form-row">
            <input
              className="input"
              aria-label="Category"
              value={row.name}
              onChange={(e) => setPlanned(planned.map((p, i) => (i === n ? { ...p, name: e.target.value } : p)))}
              placeholder="Dining Out"
            />
            <input
              className="input"
              aria-label="Planned amount"
              inputMode="decimal"
              value={row.amount}
              onChange={(e) => setPlanned(planned.map((p, i) => (i === n ? { ...p, amount: e.target.value } : p)))}
            />
            <button type="button" className="btn btn-ghost btn-danger btn-small" onClick={() => setPlanned(planned.filter((_, i) => i !== n))}>
              Remove
            </button>
          </div>
        ))}
        {planned.length < 12 && (
          <button type="button" className="btn btn-soft btn-small" onClick={() => setPlanned([...planned, { name: "", amount: "" }])}>
            Add a category
          </button>
        )}
      </fieldset>
      <label className="field">
        Notes
        <textarea
          className="input"
          rows={3}
          maxLength={2000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What to pack, who to meet, booking references. Card and passport numbers aren't kept."
        />
      </label>
      </details>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={busy || looking}>
          {initial ? "Save changes" : "Add trip"}
        </button>
        <button type="button" className="btn" onClick={() => onDone()}>
          Cancel
        </button>
      </div>
    </form>
  );
}

const WHERE_IDEAS = ["Japan in spring", "A long weekend in Bali", "Seoul in December"];

/** "Where to next?": a place and a time, handed to Nexus to research. */
function WhereNext({ onAsk, onAdd }: { onAsk?: (text: string) => void; onAdd: () => void }) {
  const [where, setWhere] = useState("");
  const ask = (text: string) => onAsk?.(`I'm thinking of a trip: ${text}. Can you research it?`);
  function go(event: FormEvent) {
    event.preventDefault();
    if (!where.trim()) return;
    ask(where.trim());
    setWhere("");
  }
  return (
    <section className="where-next" aria-labelledby="where-next">
      <h2 id="where-next">Where to next?</h2>
      {onAsk && (
        <form className="where-form" onSubmit={go} aria-label="Research a trip">
          <input className="input" value={where} maxLength={120} onChange={(e) => setWhere(e.target.value)} placeholder="A place and when, e.g. Japan in January" aria-label="Where and when" />
          <button type="submit" className="btn btn-soft" disabled={!where.trim()}>
            Research it
          </button>
        </form>
      )}
      <div className="chips where-chips">
        {onAsk &&
          WHERE_IDEAS.map((idea) => (
            <button key={idea} type="button" className="day-pill" onClick={() => ask(idea)}>
              {idea}
            </button>
          ))}
        <button type="button" className="day-pill" onClick={onAdd}>
          Add a trip
        </button>
      </div>
      <p className="caption">Nexus looks up when to go, what it costs and whether it fits your money.</p>
    </section>
  );
}

/** Travel's dashboard: where to next, trips on now, coming up and past, and research. */
export function TripsPage({ onAsk }: { onAsk?: (text: string) => void } = {}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const home = useHome();
  const trips = useQuery({ queryKey: ["trips"], queryFn: () => api<Trip[]>("/travel/trips") });
  const [adding, setAdding] = useState(false);
  // A guest only has the trips they were invited to: nothing here starts, researches or
  // sorts a trip of their own, and what asks for their own bookings or research stays unasked.
  // Nothing of their own is asked or shown until /me says so (it is already known once signed in).
  const role = useAppRole();
  const guest = role === undefined || role === "guest";
  const everything = trips.data ?? [];
  const all = everything.filter((t) => !isMember(t));
  const shared = everything.filter(isMember);
  const onNow = all.filter((t) => t.status === "ongoing");
  const comingUp = all.filter((t) => t.status === "upcoming").reverse();
  const past = all.filter((t) => t.status === "finished");
  const summary = [onNow.length > 0 && `${onNow.length} on now`, comingUp.length > 0 && `${comingUp.length} coming up`].filter(Boolean).join(" · ");

  return (
    <>
      <div className="page-head trips-head">
        <div>
          <h1>
            Your <span className="accent-serif">trips</span>
          </h1>
          {role === "guest" ? <p className="trips-summary">The trips you were invited to.</p> : summary && <p className="trips-summary">{summary}</p>}
        </div>
        {!adding && !guest && (
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            <Icon name="plus" size={16} />
            New trip
          </button>
        )}
      </div>

      {adding && !guest && (
        <section className="card" aria-labelledby="new-trip" data-no-reveal>
          <div className="card-head">
            <h2 id="new-trip">New trip</h2>
          </div>
          <TripForm
            home={home}
            onDone={(trip) => {
              setAdding(false);
              void client.invalidateQueries({ queryKey: ["trips"] });
              if (trip) navigate(`/travel/trips/${trip.id}`);
            }}
          />
        </section>
      )}
      {trips.isLoading && <p className="state">Loading…</p>}
      {trips.isError && <p className="error-text">Couldn't load your trips.</p>}
      {trips.data && everything.length === 0 && !adding && (
        <section className="card">
          <p className="state">
            {guest
              ? "You're not on any trips yet. Open an invite link to join one."
              : `No trips yet. Add one here, or tell Nexus: "I'm going to Tokyo 10 to 20 Jan, budget 3000", or "I want to go to Japan in January" to have it researched.`}
          </p>
        </section>
      )}
      {onNow.length > 0 && tripGroup("On now", onNow)}
      {comingUp.length > 0 && tripGroup("Coming up", comingUp)}
      {shared.length > 0 && tripGroup("Shared with you", shared)}
      {!adding && !guest && <WhereNext onAsk={onAsk} onAdd={() => setAdding(true)} />}
      {!guest && <LooseBookings trips={all} />}
      {!guest && <ResearchList />}
      {past.length > 0 && <PastTrips list={past} />}
      {!guest && <p className="caption trips-foot">Each trip keeps its bookings, plans and money together. Nexus never books anything.</p>}
    </>
  );
}

function tripGroup(title: string, list: Trip[]) {
  return (
    <section key={title} className="trip-group" aria-label={title}>
      <h2>{title}</h2>
      <ul className="trip-cards">
        {list.map((t) => (
          <TripCard key={t.id} trip={t} />
        ))}
      </ul>
    </section>
  );
}

/** Past trips: shut behind one button, then compact rows. */
function PastTrips({ list }: { list: Trip[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <section className="trip-group trip-past" aria-label="Past trips">
      <button type="button" className="trip-past-button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        Past trips · {list.length}
        <Icon name="chevron" size={16} className="money-chev" />
      </button>
      <ul className="trip-rows" id={id} hidden={!open}>
        {list.map((t) => (
          <TripRow key={t.id} trip={t} />
        ))}
      </ul>
    </section>
  );
}

const KIND_ICON: Record<Booking["kind"], IconName> = { flight: "flight", hotel: "stay", rail: "train", activity: "place" };

function BookingRow({ booking, children }: { booking: Booking; children?: ReactNode }) {
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

const DAY_MS = 86400000;
const isoDay = (t: number) => new Date(t).toISOString().slice(0, 10);
const dayPill = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso));

/** Every day from the trip's first to its last, plus any day outside it with an entry. */
function tripDays(detail: TripDetail): string[] {
  const days = new Set<string>();
  for (let t = Date.parse(detail.trip.start); t <= Date.parse(detail.trip.end); t += DAY_MS) days.add(isoDay(t));
  for (const b of detail.bookings) if (b.scheduled) days.add(b.starts);
  return [...days].sort();
}

/** Nights of a hotel stay after its check-in night, before check-out. */
function nightsOf(b: Booking): string[] {
  const nights: string[] = [];
  if (!b.check_in || !b.check_out) return nights;
  for (let t = Date.parse(b.check_in) + DAY_MS; t < Date.parse(b.check_out); t += DAY_MS) nights.push(isoDay(t));
  return nights;
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
        <button type="submit" className="btn btn-soft btn-small">
          Save
        </button>
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setEditing(false)}>
          Cancel
        </button>
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
        <button type="button" className="btn btn-ghost btn-small" onClick={onEdit} aria-label={`Change ${booking.title}`}>
          <Icon name="edit" size={16} />
          Change
        </button>
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
function Itinerary({ detail, day, onDay, onChange, onAdd, onIdeas }: {
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
  const staying = (d: string) => stays.filter((b) => nightsOf(b).includes(d));
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
                  <span className="day-when">{dayLabel(d)}</span>
                  <span className="day-name">{named || suggested || (free ? "Free day" : `${count} ${count === 1 ? "plan" : "plans"}`)}</span>
                  {suggested && <span className="chip suggest-chip">Suggested</span>}
                </h3>
                <DayLabel trip={detail.trip} iso={d} suggested={suggested} onChange={onChange} />
              </div>
              {staying(d).map((b) => (
                <p key={b.id} className="caption">
                  <Icon name="stay" size={16} className="icon-inline" />
                  Staying at {b.hotel ?? b.title}
                </p>
              ))}
              {homeless.has(d) && (
                <p className="gap-line">
                  <span>Nowhere to stay this night yet</span>
                  <button type="button" className="btn btn-soft btn-small" onClick={() => onAdd({ kind: "hotel", day: d })} aria-label={`Add a place to stay on ${dayPill(d)}`}>
                    Add
                  </button>
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
                      {entries.map((b) => {
                        if (b.kind === "activity") stop += 1;
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
                            <TimelineEntry booking={b} iso={d} stop={b.kind === "activity" ? stop : null} spot={daySpot(d)} onEdit={() => setEditing(b.id)} />
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
              <button type="button" className="btn btn-ghost btn-small" onClick={() => onAdd({ kind: "activity", day: d })}>
                <Icon name="plus" size={16} />
                {addLabel}
              </button>
              {inTrip(d) && (detail.places || detail.ideas) && (
                <button type="button" className="btn btn-ghost btn-small" onClick={() => onAdd({ kind: "activity", day: d, near: true })} aria-label={`Find ideas near here, Day ${n}`}>
                  <Icon name="find" size={16} />
                  Find ideas near here
                </button>
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

/** Public transport or a hire car: how longer hops go, unless one was picked. Reached from
 * the trip's menu (``TripMenu``), with the app directions open in. */
function GettingAroundPicker({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  async function choose(by: string) {
    setBusy(true);
    await api(`/travel/trips/${trip.id}/getting-around`, { method: "PUT", body: { by } }).catch(() => undefined);
    setBusy(false);
    onChange();
  }
  return (
    <label className="caption map-app">
      Getting around{" "}
      <select value={trip.getting_around ?? "transit"} disabled={busy} onChange={(e) => void choose(e.target.value)}>
        <option value="transit">{GETTING_AROUND.transit}</option>
        <option value="car">{GETTING_AROUND.car}</option>
      </select>
    </label>
  );
}

/** Bookings from email that aren't on a trip yet: put each on one, or forget it. */
function LooseBookings({ trips }: { trips: Trip[] }) {
  const client = useQueryClient();
  const loose = useQuery({ queryKey: ["loose-bookings"], queryFn: () => api<Booking[]>("/travel/bookings") });
  const ahead = trips.filter((t) => t.status !== "finished");
  if (!loose.data?.length) return null;

  async function move(booking: Booking, tripId: string) {
    if (tripId === "forget") await api(`/travel/bookings/${booking.id}`, { method: "DELETE" });
    else await api(`/travel/bookings/${booking.id}/trip`, { method: "PUT", body: { trip_id: tripId } });
    void client.invalidateQueries({ queryKey: ["loose-bookings"] });
    void client.invalidateQueries({ queryKey: ["home"] });
  }

  return (
    <section className="card quiet-list" aria-labelledby="loose-bookings">
      <div className="card-head">
        <h2 id="loose-bookings">Bookings not on a trip</h2>
      </div>
      <ul className="quiet-rows">
        {loose.data.map((b) => (
          <BookingRow key={b.id} booking={b}>
            <select className="input quiet-select" aria-label={`Trip for ${b.title}`} value="" onChange={(e) => void move(b, e.target.value)}>
              <option value="" disabled>
                Put on a trip…
              </option>
              {ahead.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.destination} ({day(t.start)})
                </option>
              ))}
              <option value="forget">Not for a trip: forget it</option>
            </select>
          </BookingRow>
        ))}
      </ul>
    </section>
  );
}

/** How longer hops go and which app directions open in: a small sheet off the trip's menu,
 * for the owner. Out in the body, since the cover's light text colours would carry into it. */
function WaysSheet({ trip, onChange, onClose }: { trip: Trip; onChange: () => void; onClose: () => void }) {
  return (
    <Sheet title="Getting around and directions" titleId="ways-sheet-title" className="ways-sheet" onClose={onClose}>
      <div className="trip-ways">
        <GettingAroundPicker trip={trip} onChange={onChange} />
        <MapAppPicker />
      </div>
    </Sheet>
  );
}

/** A trip's menu: its cover photo, changing it and deleting it, and (where the trip has maps
 * and routes) how it gets around. */
function TripMenu({ trip, onEdit, onDelete, onChange }: { trip: Trip; onEdit: () => void; onDelete: () => void; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  // Only a trip with places and routes has anything to pick; the page already holds that.
  const detail = useQueryClient().getQueryData<TripDetail>(["trip", trip.id]);
  const ways = Boolean(detail?.routes && detail.places);
  const [waysOpen, setWaysOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  async function photo(choice: "next" | "off" | "on") {
    setNote(null);
    try {
      await api<Trip>(`/travel/trips/${trip.id}/photo`, { method: "POST", body: { choice } });
      setOpen(false);
      onChange();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Couldn't change the photo");
    }
  }
  const item = (label: string, run: () => void, danger = false) => (
    <button
      type="button"
      role="menuitem"
      className={`btn btn-ghost${danger ? " btn-danger" : ""}`}
      onClick={() => {
        run();
      }}
    >
      {label}
    </button>
  );
  return (
    <div className="trip-menu">
      <button type="button" className="trip-chip trip-chip-icon" aria-label="Trip options" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        ⋯
      </button>
      {open && (
        <div className="trip-menu-list" role="menu" aria-label="Trip options">
          {item("Edit trip", () => {
            setOpen(false);
            onEdit();
          })}
          {ways &&
            item("Getting around and directions", () => {
              setOpen(false);
              setWaysOpen(true);
            })}
          {trip.photo_off ? item("Show a photo", () => void photo("on")) : item("Another photo", () => void photo("next"))}
          {!trip.photo_off && item("No photo", () => void photo("off"))}
          {item(
            "Delete trip",
            () => {
              setOpen(false);
              onDelete();
            },
            true,
          )}
          {note && (
            <p className="caption" role="status">
              {note}
            </p>
          )}
        </div>
      )}
      {waysOpen && <WaysSheet trip={trip} onChange={onChange} onClose={() => setWaysOpen(false)} />}
    </div>
  );
}

const TABS = [
  ["plan", "Plan"],
  ["ideas", "Ideas"],
  ["money", "Money"],
  ["prep", "Prep"],
] as const;
type Tab = (typeof TABS)[number][0];
const isTab = (value: string | null): value is Tab => TABS.some(([tab]) => tab === value);

/** The trip's idea lists so far: where a new idea can be filed. */
function ideaLists(detail: TripDetail): string[] {
  const lists = detail.bookings.filter((b) => b.kind === "activity" && !b.scheduled).map((b) => listOf(b)?.trim() ?? "");
  return [...new Set(lists.filter(Boolean))];
}

/** The one thing to do next, as one quiet line in the trip's header on Plan. */
function NextUpStrip({ detail, onGo }: { detail: TripDetail; onGo: (go: Go) => void }) {
  // The ideas that could fill a free day: everything not yet on a day.
  const ideas = detail.bookings.filter((b) => b.kind === "activity" && !b.scheduled).length;
  const next = nextUp(detail, () => ideas);
  if (!next) return null;
  return (
    <section className="next-up" aria-label="Next up">
      <Icon name="sparkle" size={16} className="next-up-icon" />
      <p className="next-up-text">{next.text}</p>
      <button type="button" className="btn btn-ghost next-up-action" onClick={() => onGo(next.go)} aria-label={`${next.action}: ${next.text}`}>
        {next.action}
      </button>
    </section>
  );
}

/** The trip's photo for the cover and the slim bar's thumbnail: the photo itself, with no fade over it. */
const heroStyle = (trip: Trip): CSSProperties => (trip.photo ? { backgroundImage: `url("${trip.photo.url}")` } : coverStyle(trip));

/** The header's actions, on the cover and in the slim bar: Share (People for a member), the
 * one Add on a wide screen, and the owner's ⋯ menu. */
function TripActions({ trip, member, editing, add, onShare, onEdit, onDelete, onChange }: {
  trip: Trip;
  member: boolean;
  editing: boolean;
  add: { label: string; run: () => void } | null;
  onShare: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onChange: () => void;
}) {
  return (
    <div className="trip-actions">
      {!editing && (
        <button type="button" className="trip-chip" onClick={onShare} aria-label={member ? "People on this trip" : "Share the plan"}>
          {member ? "People" : "Share"}
        </button>
      )}
      {add && (
        <button type="button" className="btn btn-primary trip-add-desktop" onClick={add.run} aria-label={add.label}>
          <Icon name="plus" size={16} />
          Add
        </button>
      )}
      {/* Editing the trip, its photo and deleting it are the owner's. */}
      {!editing && !member && <TripMenu trip={trip} onEdit={onEdit} onDelete={onDelete} onChange={onChange} />}
    </div>
  );
}

/** The height of the slim bar: the cover counts as gone once its photo is behind it. */
const SLIM_BAR = 56;

/** Whether the cover's photo has scrolled up behind the slim bar. Without an observer it never has. */
function useCoverGone(photo: RefObject<HTMLElement | null>, on: boolean): boolean {
  const [gone, setGone] = useState(false);
  useEffect(() => {
    const el = photo.current;
    if (!on || !el || typeof IntersectionObserver === "undefined") {
      setGone(false);
      return;
    }
    const seen = new IntersectionObserver(([entry]) => setGone(!entry.isIntersecting), {
      root: el.closest(".main-viewport"),
      rootMargin: `-${SLIM_BAR}px 0px 0px 0px`,
    });
    seen.observe(el);
    return () => {
      seen.disconnect();
      setGone(false);
    };
  }, [photo, on]);
  return gone;
}

/** One trip, on one page that follows it: Plan, Ideas, Money and Prep as tabs, and under
 * the header the one thing to do next. It opens on Plan, or on Money once it's over. */
export function TripPage({ onAsk }: { onAsk?: (text: string) => void } = {}) {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const home = useHome();
  const [params, setParams] = useSearchParams();
  const detail = useQuery({
    queryKey: ["trip", id],
    queryFn: () => api<TripDetail>(`/travel/trips/${id}`),
    // Someone else's change turns up when the window comes back; a 404 (removed, or left) is an answer, not a blip to retry.
    refetchOnWindowFocus: true,
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 3,
  });
  // Taken off the trip (or it's gone): the server tells a person with no part in a trip there is no such trip.
  const gone = detail.error instanceof ApiError && detail.error.status === 404;
  const [editing, setEditing] = useState(false);
  const [sheet, setSheet] = useState<{ preset: AddPreset | null } | null>(null);
  const [sharing, setSharing] = useState(false);
  const [reading, setReading] = useState(false);
  const [imported, setImported] = useState<string | null>(null);
  const [shotError, setShotError] = useState<string | null>(null);
  // The + on Money and Prep: the tab opens its own form.
  const [addingCost, setAddingCost] = useState(false);
  const [addingPacking, setAddingPacking] = useState(false);
  // The map shows every day, not just the one open.
  const [mapAll, setMapAll] = useState(false);
  const data = gone ? undefined : detail.data;
  const member = data ? isMember(data.trip) : false;
  const members = useMembers(id, Boolean(data));
  const stage: Stage = data ? stageOf(data) : "planning";
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["trip", id] }),
      client.invalidateQueries({ queryKey: ["trips"] }),
      client.invalidateQueries({ queryKey: ["trip-places", id] }),
      // A change to the day can change who goes where, and so the travel times.
      client.invalidateQueries({ queryKey: ["trip-hops", id] }),
    ]);

  // The open tab lives in the address, so Back goes to the one before.
  // A member has no Money tab: money is the owner's, so its address opens Plan.
  const asked = params.get("tab");
  const tab: Tab = isTab(asked) && !(member && asked === "money") ? asked : stage === "after" && !member ? "money" : "plan";
  useEffect(() => {
    if (member && asked === "money") {
      setParams(
        (was) => {
          const query = new URLSearchParams(was);
          query.set("tab", "plan");
          return query;
        },
        { replace: true },
      );
    }
  }, [member, asked, setParams]);
  // A trip that's gone from the list too, so it isn't offered again.
  useEffect(() => {
    if (gone) void client.invalidateQueries({ queryKey: ["trips"] });
  }, [gone, client]);
  // A + pressed on one tab doesn't wait for the next visit to it.
  useEffect(() => {
    setAddingCost(false);
    setAddingPacking(false);
  }, [tab]);
  // The day open on Plan, shared with the map and the Ideas tab: today while the trip
  // is on, else its first day, until one is picked.
  const days = useMemo(() => (data ? tripDays(data) : []), [data]);
  const today = todayIso();
  const startDay = data && data.trip.status === "ongoing" && days.includes(today) ? today : data && days.includes(data.trip.start) ? data.trip.start : (days[0] ?? "");
  const picked = params.get("day");
  const selectedDay = picked && days.includes(picked) ? picked : startDay;

  function open(next: Tab, onDay?: string) {
    setParams((was) => {
      const query = new URLSearchParams(was);
      query.set("tab", next);
      if (onDay) query.set("day", onDay);
      return query;
    });
    if (onDay) setMapAll(false);
  }

  function pickDay(iso: string) {
    setMapAll(false);
    setParams(
      (was) => {
        const query = new URLSearchParams(was);
        query.set("day", iso);
        return query;
      },
      { replace: true },
    );
  }

  function fix(f: Fix) {
    if (f === "budget") {
      // The budget is the owner's.
      if (!member) setEditing(true);
    } else setSheet({ preset: f });
  }

  function go(to: Go) {
    if ("fix" in to) fix(to.fix);
    else if (to.tab === "plan" || (to.tab === "ideas" && to.day)) open(to.tab, to.day);
    else open(to.tab);
  }

  async function screenshot(file: File) {
    setShotError(null);
    setImported(null);
    setReading(true);
    try {
      const read = await api<ScreenshotRead>(`/travel/trips/${id}/screenshot`, {
        method: "POST",
        body: { image: await base64(file), mime_type: file.type || "image/png" },
      });
      setImported(read.message);
      refresh();
    } catch (e) {
      setShotError(e instanceof Error ? e.message : "Couldn't read that screenshot");
    } finally {
      setReading(false);
    }
  }

  async function remove() {
    if (!data || !window.confirm(`Delete the trip to ${data.trip.destination}? Its expenses stay in the ledger.`)) return;
    await api(`/travel/trips/${id}`, { method: "DELETE" });
    void client.invalidateQueries({ queryKey: ["trips"] });
    navigate("/travel");
  }

  // The one + on each tab: what it's called, and what it does.
  const dayNo = data ? Math.round((Date.parse(selectedDay) - Date.parse(data.trip.start)) / DAY_MS) + 1 : 0;
  const adds: Record<Tab, { label: string; run: () => void }> = {
    plan: { label: data && dayNo >= 1 && dayNo <= data.trip.days ? `Add to Day ${dayNo}` : "Add to this day", run: () => setSheet({ preset: null }) },
    ideas: { label: "Add an idea", run: () => setSheet({ preset: { kind: "place" } }) },
    money: { label: "Add a planned cost", run: () => setAddingCost(true) },
    prep: { label: "Add to prep", run: () => setAddingPacking(true) },
  };
  const add = adds[tab];
  const canAdd = stage !== "after";

  // The big cover is Plan's; on the other tabs, or once the photo has scrolled away, a slim sticky bar stands in.
  const cover = tab === "plan";
  const photo = useRef<HTMLDivElement>(null);
  const coverGone = useCoverGone(photo, cover);
  const away = cover && coverGone;
  const slim = !cover || away;
  const actions = data ? (
    <TripActions
      trip={data.trip}
      member={member}
      editing={editing}
      add={canAdd ? add : null}
      onShare={() => setSharing(true)}
      onEdit={() => setEditing(true)}
      onDelete={() => void remove()}
      onChange={refresh}
    />
  ) : null;
  const dates = data ? `${day(data.trip.start)} – ${day(data.trip.end)}` : "";
  const SlimName = cover ? "p" : "h1";

  return (
    <div className="trip-page trip-v2" data-tab={tab} data-cover={cover && !away ? "in" : "out"}>
      {slim && (
        <div className="trip-slim" data-over={cover || undefined}>
          <Link className="trip-icon-button" to="/travel" aria-label="Back to trips">
            <Icon name="chevron" size={20} className="icon-back" />
          </Link>
          <span className="trip-slim-thumb" style={data ? heroStyle(data.trip) : undefined} aria-hidden="true" />
          <div className="trip-slim-title">
            <SlimName className="accent-serif trip-slim-name">{data?.trip.destination ?? "Trip"}</SlimName>
            {data && <span className="trip-slim-dates">{dates}</span>}
          </div>
          {actions}
        </div>
      )}
      {cover && (
        <header className="trip-hero">
          <div ref={photo} className={`trip-hero-photo${data?.trip.photo ? "" : " no-photo"}`} style={data ? heroStyle(data.trip) : undefined}>
            <div className="trip-hero-bar" aria-hidden={away || undefined} inert={away}>
              <Link className="trip-chip" to="/travel" aria-label="Back to trips">
                <Icon name="chevron" size={16} className="icon-back" />
                Trips
              </Link>
              {actions}
            </div>
            {data?.trip.photo && (
              <div className="trip-hero-credit" aria-hidden={away || undefined} inert={away}>
                <PhotoCredit photo={data.trip.photo} />
              </div>
            )}
          </div>
          <div className="trip-hero-body">
            <h1 className="accent-serif trip-hero-title">{data?.trip.destination ?? "Trip"}</h1>
            {data && (
              <p className="trip-hero-meta">
                <span>
                  {dates} · {data.trip.days} {data.trip.days === 1 ? "day" : "days"}
                </span>
                <span className="pill">{tripWhen(data.trip)}</span>
                <TripFaces trip={data.trip} members={members.data} />
              </p>
            )}
            {data && member && <p className="trip-hero-shared">{sharedBy(data.trip)}</p>}
            {data && <NextUpStrip detail={data} onGo={go} />}
            {data && <ActivityLine tripId={id} shared={hasMembers(members.data)} />}
          </div>
        </header>
      )}
      {detail.isLoading && <p className="state">Loading…</p>}
      {gone && (
        <section className="card trip-gone" aria-labelledby="trip-gone">
          <h2 id="trip-gone">You're no longer on this trip.</h2>
          <p className="caption">The owner may have taken you off it, or deleted it.</p>
          <div className="actions">
            <Link className="btn btn-soft" to="/travel">
              Go to your trips
            </Link>
          </div>
        </section>
      )}
      {detail.isError && !gone && (
        <p className="error-text" role="alert">
          {detail.error instanceof Error ? detail.error.message : "Couldn't load that trip."}
        </p>
      )}
      {data && editing && (
        <section className="card" aria-labelledby="edit-trip" data-no-reveal>
          <div className="card-head">
            <h2 id="edit-trip">Change the trip</h2>
          </div>
          <TripForm
            initial={data.trip}
            home={home}
            onDone={(saved) => {
              setEditing(false);
              if (saved) refresh();
            }}
          />
        </section>
      )}
      {data && (
        <TripPlacesProvider tripId={id} destination={data.trip.destination} enabled={data.places} ideas={data.ideas ?? false} detail={data} onChange={refresh}>
          <ArrangeProvider detail={data} days={days} on={stage !== "after"} onChange={refresh}>
          {reading && (
            <p className="state" role="status">
              Reading the screenshot…
            </p>
          )}
          {shotError && (
            <p className="error-text" role="alert">
              {shotError}
            </p>
          )}
          {imported && (
            <section className="card import-banner" role="status" aria-label="Imported from a screenshot">
              <p style={{ whiteSpace: "pre-line", margin: 0 }}>{imported}</p>
              <p className="caption">Does everything look right?</p>
              <span className="quick">
                <button type="button" className="btn btn-soft btn-small" onClick={() => setImported(null)}>
                  Looks right
                </button>
                <button
                  type="button"
                  className="btn btn-small"
                  onClick={() => {
                    setImported(null);
                    open("plan");
                    window.setTimeout(() => document.getElementById("itinerary")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
                  }}
                >
                  Fix something
                </button>
              </span>
            </section>
          )}

          <div className="trip-tabbar">
            <nav className="trip-tabs" aria-label="Trip sections">
              {TABS.filter(([name]) => !(member && name === "money")).map(([name, label]) => (
                <button key={name} type="button" className="trip-tab" aria-current={tab === name ? "page" : undefined} onClick={() => open(name)}>
                  {label}
                </button>
              ))}
            </nav>
          </div>

          {tab === "plan" && (
            <>
              <div className="plan-layout">
                {stage === "during" && selectedDay && <TodayView detail={data} day={selectedDay} />}
                <Itinerary detail={data} day={selectedDay} onDay={pickDay} onChange={refresh} onAdd={(preset) => setSheet({ preset })} onIdeas={() => open("ideas")} />
                <TripMap
                  detail={data}
                  day={mapAll ? null : selectedDay}
                  selected={selectedDay}
                  onDay={(iso) => (iso === null ? setMapAll(true) : pickDay(iso))}
                />
              </div>
              {onAsk && stage !== "after" && (
                <button
                  type="button"
                  className="btn btn-ghost trip-ask"
                  onClick={() =>
                    onAsk(
                      // A member's chat sees the plan only: no budget to ask about.
                      member
                        ? `How's the ${data.trip.destination} trip shared with me looking? What's booked and what's missing?`
                        : `How's my ${data.trip.destination} trip looking? What's booked, what's missing and what's left in the budget?`,
                    )
                  }
                >
                  <Icon name="sparkle" size={16} className="icon-inline" />
                  Ask Nexus about this trip
                </button>
              )}
            </>
          )}
          {tab === "ideas" && <IdeasTab detail={data} onChange={refresh} viewing={selectedDay || null} />}
          {tab === "money" && (
            <div className="trip-narrow trip-money-tab">
              <MoneyTab detail={data} onChange={refresh} adding={addingCost} onAddDone={() => setAddingCost(false)} />
            </div>
          )}
          {tab === "prep" && (
            <div className="trip-narrow trip-prep-tab">
              <PrepTab detail={data} onChange={refresh} onFix={fix} adding={addingPacking} onAddDone={() => setAddingPacking(false)} />
            </div>
          )}

          {stage !== "after" && (
            <button type="button" className="trip-fab-button" aria-label={add.label} onClick={add.run}>
              <Icon name="plus" size={20} />
              Add
            </button>
          )}
          {sheet && (
            <AddSheet
              trip={data.trip}
              preset={sheet.preset}
              places={data.places || (data.ideas ?? false)}
              lists={ideaLists(data)}
              viewing={selectedDay || null}
              onScreenshot={(file) => void screenshot(file)}
              onChanged={refresh}
              onClose={() => setSheet(null)}
            />
          )}
          {sharing && <ShareSheet trip={data.trip} onClose={() => setSharing(false)} onLeft={() => navigate("/travel")} />}
          </ArrangeProvider>
        </TripPlacesProvider>
      )}
    </div>
  );
}
