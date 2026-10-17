import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, Fragment, type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Booking, type Hop, type ScreenshotRead, type Trip, type TripDetail } from "../api";
import { base64 } from "../files";
import { formatMoney } from "../format";
import { ResearchList } from "./Research";
import { type AddPreset, AddSheet } from "./TripAdd";
import { BookingLines, Companions, NextUp, OpenLink, PhotoCredit, TripCard, coverStyle, day, landingOn, landsOnly, leavingOn, legTimes, todayIso, tripWhen, useHome } from "./TripBits";
import { DayCarousel } from "./DayCarousel";
import { PackingCard, WeatherCard } from "./TripExtras";
import { type Fix, MoneyBar, SpendingNow, type Stage, StillToSort, TripTotals, stageOf } from "./TripStage";
import { ArrangeProvider, DayNotes, DropZone, MoveForm, type Spot, daySpot, useArrange, useDragEntry } from "./TripArrange";
import { DayHops, HopLine, MapAppPicker, TripMap } from "./TripMap";
import { TripPlacesProvider } from "./TripPlaces";
import { EntryEditor } from "./TripEntry";
import { Sections } from "./TripIdeas";
import { MoneyDetails, SettleUp } from "./TripMoney";
import { Notes } from "./TripPrep";
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
  const [companions, setCompanions] = useState(initial?.companions.join(", ") ?? "");
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
      companions: companions
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean),
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
      <label className="field">
        Who's going
        <input className="input" value={companions} onChange={(e) => setCompanions(e.target.value)} placeholder="Names, separated by commas" />
      </label>
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
            <button type="button" className="btn btn-small" onClick={() => setPlanned(planned.filter((_, i) => i !== n))}>
              Remove
            </button>
          </div>
        ))}
        {planned.length < 12 && (
          <button type="button" className="btn btn-small" onClick={() => setPlanned([...planned, { name: "", amount: "" }])}>
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
    <section className="card where-next" aria-labelledby="where-next">
      <h2 id="where-next">Where to next?</h2>
      {onAsk && (
        <form className="where-form" onSubmit={go} aria-label="Research a trip">
          <input className="input" value={where} maxLength={120} onChange={(e) => setWhere(e.target.value)} placeholder="A place and when, e.g. Japan in January" aria-label="Where and when" />
          <button type="submit" className="btn btn-primary" disabled={!where.trim()}>
            Research it
          </button>
        </form>
      )}
      <div className="chips">
        {onAsk &&
          WHERE_IDEAS.map((idea) => (
            <button key={idea} type="button" className="ask-chip" onClick={() => ask(idea)}>
              {idea}
            </button>
          ))}
        <button type="button" className="ask-chip" onClick={onAdd}>
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
  const all = trips.data ?? [];
  const groups: [string, Trip[]][] = [
    ["On now", all.filter((t) => t.status === "ongoing")],
    ["Coming up", all.filter((t) => t.status === "upcoming").reverse()],
    ["Past", all.filter((t) => t.status === "finished")],
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Trips</h1>
          <p className="muted">Each trip keeps its bookings, plans and money together. Nexus never books anything.</p>
        </div>
      </div>

      {adding && (
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
      {trips.data && all.length === 0 && !adding && (
        <section className="card">
          <p className="state">
            No trips yet. Add one here, or tell Nexus: "I'm going to Tokyo 10 to 20 Jan, budget 3000", or "I want to go to Japan in
            January" to have it researched.
          </p>
        </section>
      )}
      {groups.slice(0, 2).filter(([, list]) => list.length > 0).map(([title, list]) => tripGroup(title, list))}
      {!adding && <WhereNext onAsk={onAsk} onAdd={() => setAdding(true)} />}
      <LooseBookings trips={all} />
      {groups.slice(2).filter(([, list]) => list.length > 0).map(([title, list]) => tripGroup(title, list))}
      <ResearchList />
    </>
  );
}

function tripGroup(title: string, list: Trip[]) {
  return (
    <section key={title} className="trip-group" aria-label={title}>
      <h2>{title}</h2>
      <ul className={`trip-cards${title === "Past" ? " trip-cards-past" : ""}`}>
        {list.map((t) => (
          <TripCard key={t.id} trip={t} />
        ))}
      </ul>
    </section>
  );
}

const KIND_ICON: Record<Booking["kind"], string> = { flight: "✈️", hotel: "🏨", rail: "🚆", activity: "📍" };

function BookingRow({ booking, children }: { booking: Booking; children?: ReactNode }) {
  return (
    <li className="run-row">
      <span className="wrap">
        <span aria-hidden="true">{KIND_ICON[booking.kind]}</span> <strong>{booking.title}</strong>
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

const sortKey = (b: Booking) => `${b.starts}T${b.at ?? b.segments[0]?.departs?.slice(11) ?? (b.kind === "hotel" ? "15:00" : "00:00")}`;
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

/** One day's label ("Busan"), edited in place. */
function DayLabel({ trip, iso, onChange }: { trip: Trip; iso: string; onChange: () => void }) {
  const current = (trip.day_labels ?? {})[iso] ?? "";
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(current);
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
        <input className="input" value={text} maxLength={40} autoFocus onChange={(e) => setText(e.target.value)} placeholder="City or plan, e.g. Busan" />
        <button type="submit" className="btn btn-small">
          Save
        </button>
      </form>
    );
  }
  return (
    <button type="button" className="btn btn-ghost btn-small day-label" onClick={() => setEditing(true)} aria-label={current ? `Change the label ${current}` : `Add a label for ${dayPill(iso)}`}>
      {current || "+ Add a label"}
    </button>
  );
}

/** A flight or train as a slim strip, a hotel check-in or check-out, or a numbered stop. */
function TimelineEntry({ booking, iso, stop, spot, children }: { booking: Booking; iso: string; stop: number | null; spot?: Spot; children?: ReactNode }) {
  const drag = useDragEntry(booking, spot);
  if (booking.kind === "hotel") {
    const out = booking.check_out === iso && booking.check_in !== iso;
    return (
      <li ref={drag.ref} className={`timeline-strip${drag.className}`} id={out ? undefined : `entry-${booking.id}`}>
        <span aria-hidden="true">🏨</span>
        <span className="wrap">
          <strong>{booking.hotel ?? booking.title}</strong>
          {!out && <br />}
          {!out && <BookingLines booking={booking} />}
          {!out && <OpenLink booking={booking} />}
        </span>
        <span className={`badge ${out ? "badge-pending" : "badge-in"}`}>{out ? "Check out" : "Check in"}</span>
        {!out && children}
      </li>
    );
  }
  if (landsOnly(booking, iso)) {
    // The day after an overnight flight or train: where and when it lands.
    const legs = landingOn(booking, iso);
    const last = legs[legs.length - 1];
    const from = legs[0];
    return (
      <li ref={drag.ref} className={`timeline-strip timeline-landing${drag.className}`} id={`land-${booking.id}`}>
        <span aria-hidden="true">{booking.kind === "flight" ? "🛬" : "🚉"}</span>
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
        {children}
      </li>
    );
  }
  if ((booking.kind === "flight" || booking.kind === "rail") && iso !== booking.starts) {
    // A later leg of the same booking, such as the flight home.
    const legs = leavingOn(booking, iso);
    return (
      <li ref={drag.ref} className={`timeline-strip${drag.className}`} id={`leave-${booking.id}-${iso}`}>
        <span aria-hidden="true">{KIND_ICON[booking.kind]}</span>
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
        {children}
      </li>
    );
  }
  if (booking.kind === "flight" || booking.kind === "rail") {
    return (
      <li ref={drag.ref} className={`timeline-strip${drag.className}`} id={`entry-${booking.id}`}>
        <span aria-hidden="true">{KIND_ICON[booking.kind]}</span>
        <span className="wrap">
          <strong>{booking.title}</strong>
          {booking.provider && <span className="caption"> · {booking.provider}</span>}
          <br />
          <BookingLines booking={booking} />
          <OpenLink booking={booking} />
        </span>
        {booking.cost && <span className="num">{formatMoney(booking.cost)}</span>}
        {children}
      </li>
    );
  }
  return (
    <li ref={drag.ref} className={`timeline-stop${drag.className}`} id={`entry-${booking.id}`}>
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
        <br />
        <BookingLines booking={booking} noTime />
        <OpenLink booking={booking} />
      </span>
      {booking.cost && <span className="num">{formatMoney(booking.cost)}</span>}
      {children}
    </li>
  );
}

/** The trip day by day: a strip of days to jump between, each day's label, its
 * flights, trains and hotel check-ins and check-outs, and numbered plans in time order. */
function Itinerary({ detail, onChange, onAdd, collapsed }: {
  detail: TripDetail;
  onChange: () => void;
  onAdd: (preset: AddPreset) => void;
  /** Folded to this one line until opened. */
  collapsed?: string;
}) {
  const home = useHome();
  const [editing, setEditing] = useState<string | null>(null);
  const [moving, setMoving] = useState<string | null>(null);
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
  const busy = (iso: string) => sorted.some((b) => b.starts === iso) || checkingOut(iso).length > 0;
  const homeless = new Set(detail.ready.nights_without_stay);
  const dayLabel = (iso: string) => {
    const n = dayNumber(iso);
    const when = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso));
    return n >= 1 && n <= detail.trip.days ? `Day ${n} · ${when}` : when;
  };

  async function remove(b: Booking) {
    if (!window.confirm(`Take ${b.title} off the itinerary?`)) return;
    await api(`/travel/bookings/${b.id}`, { method: "DELETE" }).catch(() => undefined);
    onChange();
  }

  // Opens on today while the trip is on, else its first day.
  const today = todayIso();
  const startDay = detail.trip.status === "ongoing" && days.includes(today) ? today : days.includes(detail.trip.start) ? detail.trip.start : (days[0] ?? "");
  // A plan carried by keyboard to another day takes the carousel with it.
  const carriedTo = arrange.carrying ? arrange.drop?.spot : undefined;
  const following = carriedTo?.startsWith("day:") ? carriedTo.slice(4) : null;

  const actions = (b: Booking) => (
    <EntryActions
      booking={b}
      onEdit={() => setEditing(b.id)}
      onMove={arrange.on && b.kind === "activity" ? () => setMoving(b.id) : undefined}
      onRemove={() => void remove(b)}
    />
  );

  return (
    <Fold collapsed={collapsed}>
      <DayCarousel days={days} start={startDay} follow={following} pill={dayPill} name={dayLabel}>
        {(d, near) => {
        const entries = arrange.spots.get(daySpot(d)) ?? [];
        const outs = checkingOut(d).filter((b) => b.starts !== d);
        const n = dayNumber(d);
        const ends = d === detail.trip.start || d === detail.trip.end;
        const empty = !busy(d) && staying(d).length === 0;
        const dot = !inTrip(d) ? "day-dot-out" : ends ? "day-dot-end" : empty ? "day-dot-empty" : "day-dot-planned";
        return (
          <div key={d} id={`day-${d}`} className="itinerary-day">
            <div className="day-rail" aria-hidden="true">
              <span className={`day-dot ${dot}`}>{inTrip(d) ? n : "·"}</span>
              <span className="day-line" />
            </div>
            <div className="day-body">
              <div className="day-head">
                <h3>{dayLabel(d)}</h3>
                <DayLabel trip={detail.trip} iso={d} onChange={onChange} />
              </div>
              {staying(d).map((b) => (
                <p key={b.id} className="caption">
                  <span aria-hidden="true">🏨</span> Staying at {b.hotel ?? b.title}
                </p>
              ))}
              {homeless.has(d) && (
                <p className="gap-line">
                  <span>Nowhere to stay this night yet</span>
                  <button type="button" className="btn btn-small" onClick={() => onAdd({ kind: "hotel", day: d })} aria-label={`Add a place to stay on ${dayPill(d)}`}>
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
                              />
                            </li>
                          </Fragment>
                        ) : (
                          <Fragment key={b.id}>
                            {hopsIn}
                            <TimelineEntry booking={b} iso={d} stop={b.kind === "activity" ? stop : null} spot={daySpot(d)}>
                              {actions(b)}
                            </TimelineEntry>
                            {moving === b.id && (
                              <li>
                                <MoveForm booking={b} days={days} spots={arrange.spots} onDone={() => setMoving(null)} />
                              </li>
                            )}
                          </Fragment>
                        );
                      })}
                      {after.map((h) => (
                        <HopLine key={`hop-${h.start_id}-${h.end_id}`} tripId={detail.trip.id} day={d} hop={h} addressOf={addressOf} back={back(h)} />
                      ))}
                    </ul>
                    {empty && <p className="caption">Nothing planned yet</p>}
                    </DropZone>
                    </>
                  );
                }}
              </DayHops>
              <button type="button" className="btn btn-ghost btn-small" onClick={() => onAdd({ kind: "activity", day: d })} aria-label={`Add a plan on ${dayPill(d)}`}>
                + Add a plan
              </button>
            </div>
          </div>
        );
        }}
      </DayCarousel>
      <p className="caption">Times are local.</p>
      {detail.routes && detail.places && (
        <p className="trip-ways">
          <GettingAroundPicker trip={detail.trip} onChange={onChange} />
          <MapAppPicker />
        </p>
      )}
    </Fold>
  );
}

/** Public transport or a hire car: how longer hops go, unless one was picked. */
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
        <option value="transit">Public transport</option>
        <option value="car">Hire car</option>
      </select>
    </label>
  );
}

/** An entry's Edit and Remove, behind one small button so the timeline reads cleanly. */
function EntryActions({ booking, onEdit, onMove, onRemove }: { booking: Booking; onEdit: () => void; onMove?: () => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="entry-actions">
      {open ? (
        <>
          <button type="button" className="btn btn-small" onClick={onEdit} aria-label={`Edit ${booking.title}`}>
            Edit
          </button>
          {onMove && (
            <button
              type="button"
              className="btn btn-small"
              onClick={() => {
                setOpen(false);
                onMove();
              }}
              aria-label={`Move ${booking.title} to another day or place`}
            >
              Move
            </button>
          )}
          <button type="button" className="btn btn-small" onClick={onRemove} aria-label={`Remove ${booking.title}`}>
            Remove
          </button>
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setOpen(false)} aria-label="Done">
            ×
          </button>
        </>
      ) : (
        <button type="button" className="btn btn-ghost btn-small entry-more" onClick={() => setOpen(true)} aria-label={`Change ${booking.title}`} aria-expanded={false}>
          ⋯
        </button>
      )}
    </span>
  );
}

/** The timeline as a card, or folded to one line that opens it. */
function Fold({ collapsed, children }: { collapsed?: string; children: ReactNode }) {
  if (!collapsed) {
    return (
      <section className="card itinerary-card" aria-labelledby="itinerary">
        <div className="card-head">
          <h2 id="itinerary">Itinerary</h2>
        </div>
        {children}
      </section>
    );
  }
  return (
    <details className="card section itinerary-fold itinerary-card">
      <summary>
        <h2 id="itinerary">{collapsed}</h2>
        <span className="caption">Open</span>
      </summary>
      {children}
    </details>
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
    <section className="card" aria-labelledby="loose-bookings">
      <div className="card-head">
        <h2 id="loose-bookings">Bookings not on a trip</h2>
      </div>
      <ul className="feed">
        {loose.data.map((b) => (
          <BookingRow key={b.id} booking={b}>
            <select className="input" aria-label={`Trip for ${b.title}`} value="" onChange={(e) => void move(b, e.target.value)}>
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

/** A trip's menu: its cover photo, changing it and deleting it. */
function TripMenu({ trip, onEdit, onDelete, onChange }: { trip: Trip; onEdit: () => void; onDelete: () => void; onChange: () => void }) {
  const [open, setOpen] = useState(false);
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
  const item = (label: string, run: () => void) => (
    <button
      type="button"
      role="menuitem"
      className="btn btn-ghost"
      onClick={() => {
        run();
      }}
    >
      {label}
    </button>
  );
  return (
    <div className="trip-menu">
      <button type="button" className="cover-button" aria-label="Trip options" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        ⋯
      </button>
      {open && (
        <div className="trip-menu-list" role="menu" aria-label="Trip options">
          {item("Edit trip", () => {
            setOpen(false);
            onEdit();
          })}
          {trip.photo_off ? item("Show a photo", () => void photo("on")) : item("Another photo", () => void photo("next"))}
          {!trip.photo_off && item("No photo", () => void photo("off"))}
          {item("Delete trip", () => {
            setOpen(false);
            onDelete();
          })}
          {note && (
            <p className="caption" role="status">
              {note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** One trip, on one page that follows it: the gaps while it's being planned, getting
 * ready in the last week, today while it's on, and settling up after. */
export function TripPage({ onAsk }: { onAsk?: (text: string) => void } = {}) {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const home = useHome();
  const detail = useQuery({ queryKey: ["trip", id], queryFn: () => api<TripDetail>(`/travel/trips/${id}`) });
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState<AddPreset | null>(null);
  const [sheet, setSheet] = useState<{ preset: AddPreset | null } | null>(null);
  const [moneyOpen, setMoneyOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [reading, setReading] = useState(false);
  const [imported, setImported] = useState<string | null>(null);
  const [shotError, setShotError] = useState<string | null>(null);
  const data = detail.data;
  const stage: Stage = data ? stageOf(data) : "planning";
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["trip", id] }),
      client.invalidateQueries({ queryKey: ["trips"] }),
      client.invalidateQueries({ queryKey: ["trip-places", id] }),
      // A change to the day can change who goes where, and so the travel times.
      client.invalidateQueries({ queryKey: ["trip-hops", id] }),
    ]);

  function form(preset: AddPreset) {
    setSheet(null);
    setAdding(preset);
    window.setTimeout(() => document.getElementById("trip-adding")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  function fix(f: Fix) {
    if (f === "budget") setEditing(true);
    else setSheet({ preset: f });
  }

  function openMoney() {
    setMoneyOpen(true);
    window.setTimeout(() => document.getElementById("trip-money-details")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
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

  async function takeOff(transactionId: string) {
    await api(`/travel/trips/${id}/expenses/${transactionId}`, { method: "DELETE" }).catch(() => undefined);
    refresh();
  }

  async function remove() {
    if (!data || !window.confirm(`Delete the trip to ${data.trip.destination}? Its expenses stay in the ledger.`)) return;
    await api(`/travel/trips/${id}`, { method: "DELETE" });
    void client.invalidateQueries({ queryKey: ["trips"] });
    navigate("/travel");
  }

  const timeline = (collapsed?: string) =>
    data && <Itinerary detail={data} onChange={refresh} onAdd={(preset) => setSheet({ preset })} collapsed={collapsed} />;
  const money = (title?: string) => data && <MoneyDetails detail={data} open={moneyOpen} onToggle={setMoneyOpen} onTakeOff={(t) => void takeOff(t)} title={title} />;
  const nights = data ? Math.max(data.trip.days - 1, 0) : 0;
  const sorted = data ? data.ready.nights_without_stay.length === 0 : false;

  return (
    <div className="trip-page">
      <header className="trip-cover trip-cover-compact" style={data ? coverStyle(data.trip) : undefined}>
        <div className="trip-cover-top">
          <Link className="cover-button" to="/travel" aria-label="Back to trips">
            <span aria-hidden="true">‹</span> Trips
          </Link>
          {data && !editing && (
            <div className="cover-actions">
              <button type="button" className="cover-button" onClick={() => setSharing(true)} aria-label="Share the plan">
                Share
              </button>
              <TripMenu trip={data.trip} onEdit={() => setEditing(true)} onDelete={() => void remove()} onChange={refresh} />
            </div>
          )}
        </div>
        <div className="trip-cover-main">
          <h1>{data?.trip.destination ?? "Trip"}</h1>
          {data && (
            <p className="trip-meta">
              <span>
                {day(data.trip.start)} – {day(data.trip.end)} · {data.trip.days} {data.trip.days === 1 ? "day" : "days"}
              </span>
              <span className="pill">{tripWhen(data.trip)}</span>
              <Companions names={data.trip.companions} />
            </p>
          )}
          {data?.trip.photo && <PhotoCredit photo={data.trip.photo} />}
        </div>
      </header>
      {detail.isLoading && <p className="state">Loading…</p>}
      {detail.isError && (
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
        <TripPlacesProvider tripId={id} destination={data.trip.destination} enabled={data.places} ideas={data.ideas ?? false} onChange={refresh}>
          <ArrangeProvider detail={data} days={tripDays(data)} on={stage !== "after"} onChange={refresh}>
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
                <button type="button" className="btn btn-small" onClick={() => setImported(null)}>
                  👍 Looks right
                </button>
                <button
                  type="button"
                  className="btn btn-small"
                  onClick={() => {
                    setImported(null);
                    document.getElementById("itinerary")?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  👎 Fix something
                </button>
              </span>
            </section>
          )}
          {adding && (
            <section id="trip-adding" className="card" aria-labelledby="trip-adding-title" data-no-reveal>
              <div className="card-head">
                <h2 id="trip-adding-title">Add to the trip</h2>
              </div>
              <EntryEditor
                key={`${adding.kind}-${adding.day ?? ""}`}
                trip={data.trip}
                home={home}
                preset={adding}
                onDone={(saved) => {
                  setAdding(null);
                  if (saved) refresh();
                }}
              />
            </section>
          )}

          {stage === "planning" && (
            <>
              <StillToSort detail={data} onFix={fix} />
              <MoneyBar detail={data} onOpen={openMoney} />
              <div className="trip-plan">
                <TripMap detail={data} />
                {timeline()}
              </div>
              <Sections detail={data} onChange={refresh} />
              <Notes trip={data.trip} />
              {money()}
            </>
          )}

          {stage === "soon" && (
            <>
              <StillToSort detail={data} onFix={fix} quiet />
              <NextUp detail={data} />
              <div className="trip-pair">
                <WeatherCard trip={data.trip} />
                <PackingCard key={data.trip.id} trip={data.trip} onChange={refresh} />
              </div>
              <MoneyBar detail={data} onOpen={openMoney} />
              <TripMap detail={data} />
              {timeline(`Itinerary · ${data.trip.days} days${sorted && nights > 0 ? " · every night booked" : ""}`)}
              <Sections detail={data} onChange={refresh} />
              <Notes trip={data.trip} />
              {money()}
            </>
          )}

          {stage === "during" && (
            <>
              <SpendingNow detail={data} />
              <TodayView detail={data} />
              <WeatherCard trip={data.trip} />
              <TripMap detail={data} />
              {timeline("The whole trip, day by day")}
              <Sections detail={data} onChange={refresh} />
              <Notes trip={data.trip} />
              {money()}
            </>
          )}

          {stage === "after" && (
            <>
              <SettleUp detail={data} />
              <TripTotals detail={data} />
              {money("All expenses")}
              {timeline("The trip, day by day")}
            </>
          )}

          {onAsk && stage !== "after" && (
            <button
              type="button"
              className="btn btn-ghost trip-ask"
              onClick={() => onAsk(`How's my ${data.trip.destination} trip looking? What's booked, what's missing and what's left in the budget?`)}
            >
              <span aria-hidden="true">✨</span> Ask Nexus about this trip
            </button>
          )}
          {stage !== "after" && (
            <button type="button" className="trip-fab-button" aria-label="Add to the trip" onClick={() => setSheet({ preset: null })}>
              +
            </button>
          )}
          {sheet && (
            <AddSheet
              trip={data.trip}
              preset={sheet.preset}
              places={data.places || (data.ideas ?? false)}
              onScreenshot={(file) => void screenshot(file)}
              onForm={form}
              onChanged={refresh}
              onClose={() => setSheet(null)}
            />
          )}
          {sharing && <ShareSheet trip={data.trip} onClose={() => setSharing(false)} />}
          </ArrangeProvider>
        </TripPlacesProvider>
      )}
    </div>
  );
}
