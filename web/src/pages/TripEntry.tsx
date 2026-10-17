import { type FormEvent, useState } from "react";

import { api, type Booking, type Trip } from "../api";

/** What the editor adds: a booking kind, or a place to visit (a plan without a day). */
export type EntryKind = Booking["kind"] | "place";

export type EntryForm = {
  kind: EntryKind;
  category: string;
  name: string;
  day: string;
  at: string;
  ends: string;
  until: string;
  address: string;
  number: string;
  origin: string;
  destination: string;
  departs: string;
  arrives: string;
  provider: string;
  note: string;
  reference: string;
  bookedVia: string;
  cost: string;
  currency: string;
  link: string;
  list: string;
};

export const PLACE_KINDS = ["Food", "Sight", "Shopping", "Nature", "Nightlife", "Museum", "Activity"];

export const EMPTY: EntryForm = {
  kind: "activity", category: "", name: "", day: "", at: "", ends: "", until: "", address: "", number: "", origin: "", destination: "",
  departs: "", arrives: "", provider: "", note: "", reference: "", bookedVia: "", cost: "", currency: "", link: "", list: "",
};

export function formOf(b: Booking): EntryForm {
  const leg = b.segments[0];
  return {
    kind: b.kind === "activity" && !b.scheduled ? "place" : b.kind,
    category: b.category ?? "",
    name: b.kind === "hotel" ? (b.hotel ?? "") : (b.name ?? ""),
    day: (b.kind === "hotel" ? b.check_in : b.day) ?? "",
    at: b.at ?? "",
    ends: b.ends_at ?? "",
    until: b.check_out ?? "",
    address: b.address ?? "",
    number: leg?.number ?? "",
    origin: leg?.origin ?? "",
    destination: leg?.destination ?? "",
    departs: leg?.departs ?? "",
    arrives: leg?.arrives ?? "",
    provider: b.provider ?? "",
    note: b.note ?? "",
    reference: b.reference ?? "",
    bookedVia: b.booked_via ?? "",
    cost: b.cost ? String(Number(b.cost.amount)) : "",
    currency: b.cost?.currency ?? "",
    link: b.link ?? "",
    list: b.list_name ?? "",
  };
}

export function bodyOf(f: EntryForm, home: string) {
  const blank = (v: string) => v.trim() || null;
  const base = {
    kind: f.kind, note: blank(f.note), reference: blank(f.reference), booked_via: blank(f.bookedVia), link: blank(f.link),
    cost: blank(f.cost), currency: f.cost.trim() ? f.currency.trim() || home : null,
  };
  if (f.kind === "activity") {
    const at = blank(f.at);
    return { ...base, name: blank(f.name), day: blank(f.day), at, ends_at: at ? blank(f.ends) : null, address: blank(f.address), category: blank(f.category) };
  }
  // A place given a day goes onto the itinerary as a plan on that day.
  if (f.kind === "place") return { ...base, kind: "activity", name: blank(f.name), day: blank(f.day), at: null, address: blank(f.address), category: blank(f.category), list_name: blank(f.list) };
  if (f.kind === "hotel") return { ...base, hotel: blank(f.name), check_in: blank(f.day), check_out: blank(f.until), address: blank(f.address) };
  return {
    ...base,
    provider: blank(f.provider),
    segments: [{ number: blank(f.number), origin: blank(f.origin), destination: blank(f.destination), departs: blank(f.departs), arrives: blank(f.arrives) }],
  };
}

/** Add or change an itinerary entry by hand: a plan, a flight, a hotel or a train. */
export function EntryEditor({ trip, home, entry, preset, lists = [], onDone }: {
  trip: Trip;
  home: string;
  entry?: Booking;
  preset?: { kind: EntryKind; day?: string };
  /** The trip's lists so far, offered as a place's list is typed. */
  lists?: string[];
  onDone: (saved: boolean) => void;
  /** Opens the day picker for this entry (editing only). */
  onMove?: () => void;
}) {
  const tripId = trip.id;
  // New entries start on the trip's dates (or the day they're added from), so the date
  // pickers open on the right month.
  const start = preset?.day ?? trip.start;
  const [f, setF] = useState<EntryForm>(
    entry
      ? formOf(entry)
      : { ...EMPTY, kind: preset?.kind ?? "activity", day: preset?.kind === "place" ? "" : start, until: trip.end, departs: `${start}T09:00` },
  );
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof EntryForm) => (e: { target: { value: string } }) => {
    const next = { ...f, [key]: e.target.value };
    // A check-in moved past the check-out takes the check-out along.
    if (key === "day" && next.kind === "hotel" && next.until && next.day > next.until) next.until = next.day;
    setF(next);
  };

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const body = bodyOf(f, home);
      if (entry) await api(`/travel/bookings/${entry.id}`, { method: "PUT", body });
      else await api(`/travel/trips/${tripId}/bookings`, { method: "POST", body });
      onDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
    }
  }

  const legs = f.kind === "flight" || f.kind === "rail";
  return (
    <form className="trip-form" onSubmit={save} aria-label={entry ? "Change the entry" : "Add to the itinerary"}>
      {!entry && (
        <label className="field">
          What
          <select className="input" value={f.kind} onChange={set("kind")}>
            <option value="activity">Plan on a day (dinner, tour, day trip)</option>
            <option value="place">Place to visit, no day yet</option>
            <option value="flight">Flight</option>
            <option value="hotel">Hotel</option>
            <option value="rail">Train</option>
          </select>
        </label>
      )}
      {f.kind === "activity" && (
        <div className="trip-form-row">
          <label className="field">
            Name
            <input className="input" value={f.name} maxLength={120} onChange={set("name")} required />
          </label>
          <label className="field">
            Day
            <input className="input" type="date" value={f.day} onChange={set("day")} required />
          </label>
          <label className="field">
            Time
            <input className="input" type="time" value={f.at} onChange={set("at")} />
          </label>
          <label className="field">
            Until
            <input className="input" type="time" value={f.ends} min={f.at || undefined} disabled={!f.at} onChange={set("ends")} />
          </label>
        </div>
      )}
      {f.kind === "place" && (
        <div className="trip-form-row">
          <label className="field">
            Name
            <input className="input" value={f.name} maxLength={120} onChange={set("name")} required />
          </label>
          <label className="field">
            Kind
            <input className="input" value={f.category} maxLength={30} list="place-kinds" onChange={set("category")} placeholder="Food, Sight…" />
            <datalist id="place-kinds">
              {PLACE_KINDS.map((k) => (
                <option key={k} value={k} />
              ))}
            </datalist>
          </label>
          <label className="field">
            List
            <input className="input" value={f.list} maxLength={30} list="place-lists" onChange={set("list")} placeholder="Eat, Must see…" />
            <datalist id="place-lists">
              {lists.map((k) => (
                <option key={k} value={k} />
              ))}
            </datalist>
          </label>
          {entry && (
            <label className="field">
              Day (puts it on the itinerary)
              <input className="input" type="date" value={f.day} onChange={set("day")} />
            </label>
          )}
        </div>
      )}
      {f.kind === "hotel" && (
        <div className="trip-form-row">
          <label className="field">
            Hotel
            <input className="input" value={f.name} maxLength={120} onChange={set("name")} required />
          </label>
          <label className="field">
            Check in
            <input className="input" type="date" value={f.day} onChange={set("day")} required />
          </label>
          <label className="field">
            Check out
            <input className="input" type="date" value={f.until} min={f.day || undefined} onChange={set("until")} />
          </label>
        </div>
      )}
      {legs && (
        <>
          <div className="trip-form-row">
            <label className="field">
              {f.kind === "flight" ? "Flight number" : "Train"}
              <input className="input" value={f.number} maxLength={20} onChange={set("number")} />
            </label>
            <label className="field">
              From
              <input className="input" value={f.origin} maxLength={80} onChange={set("origin")} />
            </label>
            <label className="field">
              To
              <input className="input" value={f.destination} maxLength={80} onChange={set("destination")} />
            </label>
          </div>
          <div className="trip-form-row">
            <label className="field">
              Departs (local)
              <input className="input" type="datetime-local" value={f.departs} onChange={set("departs")} required />
            </label>
            <label className="field">
              Arrives (local)
              <input className="input" type="datetime-local" value={f.arrives} onChange={set("arrives")} />
            </label>
            <label className="field">
              {f.kind === "flight" ? "Airline" : "Operator"}
              <input className="input" value={f.provider} maxLength={80} onChange={set("provider")} />
            </label>
          </div>
        </>
      )}
      {(f.kind === "activity" || f.kind === "hotel" || f.kind === "place") && (
        <label className="field">
          {f.kind === "hotel" ? "Address" : "Where"}
          <input className="input" value={f.address} maxLength={200} onChange={set("address")} />
        </label>
      )}
      <label className="field">
        Link
        <input className="input" type="url" inputMode="url" value={f.link} maxLength={500} onChange={set("link")} placeholder="https://… to book or read more" />
      </label>
      <div className="trip-form-row">
        <label className="field">
          Booking reference
          <input className="input" value={f.reference} maxLength={40} onChange={set("reference")} placeholder="Optional" />
        </label>
        <label className="field">
          Booked on
          <input className="input" value={f.bookedVia} maxLength={80} onChange={set("bookedVia")} placeholder="Agoda, the airline…" />
        </label>
      </div>
      <div className="trip-form-row">
        <label className="field">
          Note
          <input className="input" value={f.note} maxLength={300} onChange={set("note")} placeholder="Seat, what to bring…" />
        </label>
        <label className="field">
          Cost
          <input className="input" inputMode="decimal" value={f.cost} onChange={set("cost")} placeholder="Optional" />
        </label>
        <label className="field">
          Currency
          <input className="input" value={f.currency} maxLength={3} onChange={set("currency")} placeholder={home} />
        </label>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary">
          {entry ? "Save" : "Add"}
        </button>
        <button type="button" className="btn" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** The body of `PUT /travel/trips/{id}` for a trip as it stands, with `changes` laid over it:
 * the same shape the trip form sends, so one field can change without resending the rest by hand. */
export function tripBody(trip: Trip, changes: Partial<{ notes: string | null; planned: Record<string, string> }> = {}) {
  return {
    destination: trip.destination,
    start: trip.start,
    end: trip.end,
    currency: trip.currency,
    budget: trip.budget?.amount ? String(Number(trip.budget.amount)) : null,
    companions: trip.companions,
    set_aside: trip.set_aside ? String(Number(trip.set_aside.amount)) : null,
    planned: Object.fromEntries(Object.entries(trip.planned).map(([name, m]) => [name, String(Number(m.amount))])),
    notes: trip.notes?.trim() || null,
    ...changes,
  };
}
