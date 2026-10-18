import { type FormEvent, useState } from "react";

import { api, type Booking, type Trip } from "../api";

/** What the editor adds: a booking kind, a ticket (a booked plan), or an idea (a plan
 * without a day, "place" here and in the API's own words). */
export type EntryKind = Booking["kind"] | "place" | "ticket";

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
    // A ticket is a booked plan: it comes back as a plan, with its booking details open.
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
  // A ticket is saved as a plan on its day and time; the API has no kind for it.
  if (f.kind === "activity" || f.kind === "ticket") {
    const at = blank(f.at);
    return { ...base, kind: "activity", name: blank(f.name), day: blank(f.day), at, ends_at: at ? blank(f.ends) : null, address: blank(f.address), category: blank(f.category) };
  }
  // An idea has no day; it goes onto the itinerary when it is moved to one.
  if (f.kind === "place") return { ...base, kind: "activity", name: blank(f.name), day: blank(f.day), at: null, address: blank(f.address), category: blank(f.category), list_name: blank(f.list) };
  if (f.kind === "hotel") return { ...base, hotel: blank(f.name), check_in: blank(f.day), check_out: blank(f.until), address: blank(f.address) };
  return {
    ...base,
    provider: blank(f.provider),
    segments: [{ number: blank(f.number), origin: blank(f.origin), destination: blank(f.destination), departs: blank(f.departs), arrives: blank(f.arrives) }],
  };
}

/** Whether the form holds any of what "More details" holds, so it opens already showing it. */
export function hasExtras(f: EntryForm): boolean {
  const legs = f.kind === "flight" || f.kind === "rail";
  return [legs ? f.provider : f.address, f.link, f.reference, f.bookedVia, f.note, f.cost].some((v) => v.trim() !== "");
}

/** Each date of the trip, first to last. */
export function tripDays(trip: Pick<Trip, "start" | "end">): string[] {
  const first = new Date(`${trip.start}T00:00:00Z`).getTime();
  const days = [trip.start];
  if (Number.isNaN(first)) return days;
  for (let i = 1; i < 400; i += 1) {
    const day = new Date(first + i * 86_400_000).toISOString().slice(0, 10);
    if (day > trip.end) break;
    days.push(day);
  }
  return days;
}

/** "Sun 4 Apr". */
export function dayName(day: string): string {
  const parts = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).formatToParts(new Date(`${day}T00:00:00Z`));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("weekday")} ${part("day")} ${part("month")}`;
}

const BOOKINGS: { kind: EntryKind; label: string }[] = [
  { kind: "flight", label: "Flight" },
  { kind: "hotel", label: "Stay" },
  { kind: "rail", label: "Train" },
  { kind: "ticket", label: "Ticket" },
];

/** Add or change an itinerary entry by hand, with only the few fields its kind needs and
 * the rest under "More details": a booking, a plan or an idea. */
export function EntryEditor({ trip, home, entry, preset, lists = [], onDone, onMove }: {
  trip: Trip;
  home: string;
  entry?: Booking;
  preset?: { kind: EntryKind; day?: string };
  /** The trip's lists so far, offered as an idea's list is chosen. */
  lists?: string[];
  onDone: (saved: boolean) => void;
  /** Opens the day picker for this entry (editing a plan or idea only). */
  onMove?: () => void;
}) {
  const tripId = trip.id;
  // New entries start on the trip's dates (or the day they're added from), so the date
  // pickers open on the right month.
  const start = preset?.day ?? trip.start;
  const [f, setF] = useState<EntryForm>(() => {
    if (entry) return formOf(entry);
    const kind = preset?.kind ?? "activity";
    return { ...EMPTY, kind, day: kind === "place" ? "" : start, until: trip.end < start ? start : trip.end, departs: `${start}T09:00` };
  });
  const [more, setMore] = useState(() => (entry ? hasExtras(formOf(entry)) : false));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof EntryForm) => (e: { target: { value: string } }) => {
    const next = { ...f, [key]: e.target.value };
    // A check-in moved past the check-out takes the check-out along.
    if (key === "day" && next.kind === "hotel" && next.until && next.day > next.until) next.until = next.day;
    setF(next);
  };
  const pick = (kind: EntryKind) => setF({ ...f, kind, until: kind === "hotel" && f.until && f.day > f.until ? f.day : f.until });

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = bodyOf(f, home);
      if (entry) await api(`/travel/bookings/${entry.id}`, { method: "PUT", body });
      else await api(`/travel/trips/${tripId}/bookings`, { method: "POST", body });
      onDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!entry || !window.confirm(`Take ${entry.title} off the trip?`)) return;
    setError(null);
    setBusy(true);
    try {
      await api(`/travel/bookings/${entry.id}`, { method: "DELETE" });
      onDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove that");
    } finally {
      setBusy(false);
    }
  }

  const legs = f.kind === "flight" || f.kind === "rail";
  const booking = legs || f.kind === "hotel" || f.kind === "ticket";
  const planned = f.kind === "activity" || f.kind === "ticket";
  const days = tripDays(trip);
  return (
    <form className="trip-form" onSubmit={save} aria-label={entry ? "Change the entry" : "Add to the itinerary"}>
      {!entry && booking && (
        <div className="chips" role="group" aria-label="What kind of booking">
          {BOOKINGS.map((b) => (
            <button key={b.kind} type="button" className="pick" aria-pressed={f.kind === b.kind} onClick={() => pick(b.kind)}>
              {b.label}
            </button>
          ))}
        </div>
      )}
      {planned && (
        <>
          <label className="field">
            Name
            <input className="input" value={f.name} maxLength={120} onChange={set("name")} placeholder={f.kind === "ticket" ? "Museum entry, concert…" : "Dinner, tour, day trip…"} required />
          </label>
          <div className="trip-form-row">
            <label className="field">
              Day
              <select className="input" value={f.day} onChange={set("day")} required>
                {!f.day && (
                  <option value="" disabled>
                    Pick a day
                  </option>
                )}
                {f.day && !days.includes(f.day) && <option value={f.day}>{dayName(f.day)} (outside the trip)</option>}
                {days.map((d, i) => (
                  <option key={d} value={d}>
                    Day {i + 1} · {dayName(d)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Time
              <input className="input" type="time" value={f.at} onChange={set("at")} />
            </label>
            {f.kind === "activity" && f.at && (
              <label className="field">
                Until
                <input className="input" type="time" value={f.ends} min={f.at} onChange={set("ends")} />
              </label>
            )}
          </div>
        </>
      )}
      {f.kind === "place" && (
        <>
          <label className="field">
            Name
            <input className="input" value={f.name} maxLength={120} onChange={set("name")} required />
          </label>
          <fieldset className="field-group">
            <legend>List</legend>
            {lists.length > 0 && (
              <div className="chips">
                {lists.map((name) => (
                  <button key={name} type="button" className="pick" aria-pressed={f.list === name} onClick={() => setF({ ...f, list: f.list === name ? "" : name })}>
                    {name}
                  </button>
                ))}
              </div>
            )}
            <input
              className="input"
              aria-label="New list"
              value={lists.includes(f.list) ? "" : f.list}
              maxLength={30}
              onChange={set("list")}
              placeholder="New list…"
            />
          </fieldset>
          <label className="field">
            Kind (optional)
            <input className="input" value={f.category} maxLength={30} list="place-kinds" onChange={set("category")} placeholder="Food, Sight…" />
            <datalist id="place-kinds">
              {PLACE_KINDS.map((k) => (
                <option key={k} value={k} />
              ))}
            </datalist>
          </label>
        </>
      )}
      {f.kind === "hotel" && (
        <>
          <label className="field">
            Name
            <input className="input" value={f.name} maxLength={120} onChange={set("name")} required />
          </label>
          <div className="trip-form-row">
            <label className="field">
              Check in
              <input className="input" type="date" value={f.day} onChange={set("day")} required />
            </label>
            <label className="field">
              Check out
              <input className="input" type="date" value={f.until} min={f.day || undefined} onChange={set("until")} />
            </label>
          </div>
        </>
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
          </div>
        </>
      )}
      <details className="more" open={more} onToggle={(e) => setMore(e.currentTarget.open)}>
        <summary>More details</summary>
        <div className="more-body">
          {legs ? (
            <label className="field">
              {f.kind === "flight" ? "Airline" : "Operator"}
              <input className="input" value={f.provider} maxLength={80} onChange={set("provider")} />
            </label>
          ) : (
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
          <label className="field">
            Note
            <input className="input" value={f.note} maxLength={300} onChange={set("note")} placeholder="Seat, what to bring…" />
          </label>
          <div className="trip-form-row">
            <label className="field">
              Cost
              <input className="input" inputMode="decimal" value={f.cost} onChange={set("cost")} placeholder="Optional" />
            </label>
            <label className="field">
              Currency
              <input className="input" value={f.currency} maxLength={3} onChange={set("currency")} placeholder={home} />
            </label>
          </div>
        </div>
      </details>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {entry ? "Save" : "Add"}
        </button>
        <button type="button" className="btn" onClick={() => onDone(false)}>
          Cancel
        </button>
        {entry && entry.kind === "activity" && onMove && (
          <button type="button" className="btn" onClick={onMove}>
            Move to…
          </button>
        )}
        {entry && (
          <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void remove()}>
            Remove
          </button>
        )}
      </div>
    </form>
  );
}

/** The body of `PUT /travel/trips/{id}` for a trip as it stands, with `changes` laid over it:
 * the same shape the trip form sends, so one field can change without resending the rest by hand. */
export function tripBody(trip: Trip, changes: Partial<{ notes: string | null; planned: Record<string, string>; companions: string[] }> = {}) {
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
