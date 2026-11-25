import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, type Trip } from "../api";
import { Icon } from "../components/Icon";
import { LoadError } from "../components/LoadError";
import { ResearchList } from "./Research";
import { TripCard, TripRow, isMember, useAppRole, useHome } from "./TripBits";
import { NameChips } from "./TripMoney";
import { Button, Chip } from "../components/ui";
import { LooseBookings } from "./TripHeader";

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

export function TripForm({ initial, home, onDone }: { initial?: Trip; home: string; onDone: (trip?: Trip) => void }) {
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
          <Button variant="text" size="sm" onClick={() => setPicking(true)}>
            Change
          </Button>
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
            <Button variant="danger" size="sm" onClick={() => setPlanned(planned.filter((_, i) => i !== n))}>
              Remove
            </Button>
          </div>
        ))}
        {planned.length < 12 && (
          <Button variant="secondary" size="sm" onClick={() => setPlanned([...planned, { name: "", amount: "" }])}>
            Add a category
          </Button>
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
        <Button type="submit" variant="primary" disabled={busy || looking}>
          {initial ? "Save changes" : "Add trip"}
        </Button>
        <Button onClick={() => onDone()}>
          Cancel
        </Button>
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
          <Button type="submit" variant="secondary" disabled={!where.trim()}>
            Research it
          </Button>
        </form>
      )}
      <div className="chips where-chips">
        {onAsk &&
          WHERE_IDEAS.map((idea) => (
            <Chip key={idea} onClick={() => ask(idea)}>
              {idea}
            </Chip>
          ))}
        <Chip onClick={onAdd}>
          Add a trip
        </Chip>
      </div>
      <p className="caption">Nexus looks up when to go and what it costs.</p>
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
  // With the list failed, the page below would read as if there were no trips: it waits for the list.
  const failed = trips.isError && !trips.data;
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
          <h1>Your trips</h1>
          {role === "guest" ? <p className="trips-summary">The trips you were invited to.</p> : summary && <p className="trips-summary">{summary}</p>}
        </div>
        {!adding && !guest && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Icon name="plus" size={16} />
            New trip
          </Button>
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
      {failed && <LoadError message="Couldn't load your trips." query={trips} variant="page" />}
      {/* Someone with trips of their own and none yet is led by "Where to next?" below, which already
          offers to add one or have Nexus research it; only a guest, who has no such card, is told. */}
      {trips.data && everything.length === 0 && !adding && guest && (
        <section className="card">
          <p className="state">You're not on any trips yet. Open an invite link to join one.</p>
        </section>
      )}
      {onNow.length > 0 && tripGroup("On now", onNow)}
      {comingUp.length > 0 && tripGroup("Coming up", comingUp)}
      {shared.length > 0 && tripGroup("Shared with you", shared)}
      {!failed && !adding && !guest && <WhereNext onAsk={onAsk} onAdd={() => setAdding(true)} />}
      {!failed && !guest && <LooseBookings trips={all} />}
      {!failed && !guest && <ResearchList />}
      {past.length > 0 && <PastTrips list={past} />}
      {!failed && !guest && <p className="caption trips-foot">Nexus never books anything.</p>}
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
