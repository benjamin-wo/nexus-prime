import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Booking, type Me, type Money, type Trip, type TripDetail } from "../api";
import { formatMoney, formatShortDate } from "../format";

const day = (iso: string) => formatShortDate(iso, "UTC");

export function tripWhen(trip: Trip): string {
  if (trip.status === "ongoing") return `Day ${trip.day_number} of ${trip.days}`;
  if (trip.status === "finished") return "Finished";
  if (trip.days_until === 1) return "Tomorrow";
  return `In ${trip.days_until} days`;
}

type FormRow = { name: string; amount: string };

/** Add or change a trip. Money is in the home currency; the trip's own currency is
 * what's spent there, which is how its spending is found. */
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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
          <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label className="field">
          To
          <input className="input" type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
        </label>
        <label className="field">
          Currency there
          <input className="input" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} placeholder="JPY" required />
        </label>
      </div>
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
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {initial ? "Save changes" : "Add trip"}
        </button>
        <button type="button" className="btn" onClick={() => onDone()}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function useHome(): string {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me") });
  return me.data?.user.home_currency ?? "";
}

function TripRow({ trip }: { trip: Trip }) {
  return (
    <li className="run-row">
      <span className="wrap">
        <Link to={`/travel/trips/${trip.id}`}>
          <strong>{trip.destination}</strong>
        </Link>{" "}
        · {day(trip.start)} to {day(trip.end)}
        <br />
        <span className="caption">
          {tripWhen(trip)}
          {trip.budget && ` · budget ${formatMoney(trip.budget)}`}
          {trip.companions.length > 0 && ` · with ${trip.companions.join(", ")}`}
        </span>
      </span>
    </li>
  );
}

/** Travel's dashboard: trips on now, coming up and past. */
export function TripsPage() {
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
          <p className="muted">
            A trip keeps its money together: the budget, what to set aside each payday, bookings from your email, what you spend there
            and who still owes you after. Nexus never books anything.
          </p>
        </div>
        {!adding && (
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            Add a trip
          </button>
        )}
      </div>
      {adding && (
        <section className="card" aria-labelledby="new-trip">
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
            No trips yet. Add one here, or tell Nexus: "I'm going to Tokyo 10 to 20 Jan, budget 3000".
          </p>
        </section>
      )}
      <LooseBookings trips={all} />
      {groups
        .filter(([, list]) => list.length > 0)
        .map(([title, list]) => (
          <section key={title} className="card" aria-label={title}>
            <div className="card-head">
              <h2>{title}</h2>
            </div>
            <ul className="feed">
              {list.map((t) => (
                <TripRow key={t.id} trip={t} />
              ))}
            </ul>
          </section>
        ))}
    </>
  );
}

function Figure({ label, value, note }: { label: string; value: Money | null; note?: string }) {
  if (!value) return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd className="num">{formatMoney(value)}</dd>
      {note && <dd className="caption">{note}</dd>}
    </div>
  );
}

function BudgetMeter({ percent }: { percent: number }) {
  const tone = percent >= 100 ? " meter-over" : percent >= 80 ? " meter-warn" : "";
  return (
    <div className={`meter${tone}`} role="progressbar" aria-label="Budget used" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  );
}

function Spending({ detail }: { detail: TripDetail }) {
  const { trip, spending: s } = detail;
  const biggest = Math.max(1, ...s.categories.map((c) => Number(c.spent.amount)));
  return (
    <section className="card" aria-labelledby="trip-spending">
      <div className="card-head">
        <h2 id="trip-spending">Trip spending</h2>
        <span className="caption">Your share, in {s.spent.currency} at each day's rate</span>
      </div>
      {trip.budget && s.percent !== null && (
        <div className="budget solo">
          <div className="budget-head">
            <span>
              {formatMoney(s.spent)} of {formatMoney(trip.budget)}
            </span>
            <span className={`num ${s.percent >= 100 ? "budget-state-over" : s.percent >= 80 ? "budget-state-warn" : ""}`}>{s.percent}%</span>
          </div>
          <BudgetMeter percent={s.percent} />
        </div>
      )}
      <dl className="totals" aria-label="Trip totals">
        <Figure label="Spent" value={s.spent} note={Number(s.before.amount) > 0 ? `${formatMoney(s.before)} before the trip` : undefined} />
        {s.left && <Figure label={Number(s.left.amount) < 0 ? "Over budget" : "Left"} value={{ ...s.left, amount: String(Math.abs(Number(s.left.amount))) }} />}
        <Figure label="Today" value={s.today} />
        <Figure label="Average a day" value={s.per_day} />
        <Figure label="To stay on budget" value={s.per_day_left} note="a day, for the rest of the trip" />
        <Figure
          label="Booked"
          value={detail.booked}
          note={detail.booked_unlogged && Number(detail.booked_unlogged.amount) > 0 ? `${formatMoney(detail.booked_unlogged)} not logged yet` : undefined}
        />
        {detail.booked && <Figure label="Still to spend" value={detail.to_spend} note="the budget less what's spent and booked" />}
      </dl>
      {s.categories.length > 0 && (
        <ul className="bars" aria-label="Biggest categories">
          {s.categories.slice(0, trip.status === "finished" ? undefined : 5).map((c) => (
            <li key={c.name} className="bar-row">
              <span className="wrap">{c.name}</span>
              <span className="bar-track">
                <span className="bar" style={{ width: `${(Number(c.spent.amount) / biggest) * 100}%` }} />
              </span>
              <span className="num">
                {formatMoney(c.spent)}
                {c.planned && <span className="caption"> of {formatMoney(c.planned)}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {detail.items.length === 0 && (
        <p className="state">
          Nothing spent yet. Expenses in {trip.currency} between {day(trip.start)} and {day(trip.end)} count by themselves.
        </p>
      )}
      {s.unconverted > 0 && <p className="caption">{s.unconverted} expenses have no exchange rate yet and aren't counted.</p>}
    </section>
  );
}

function PlannedVsActual({ detail }: { detail: TripDetail }) {
  const rows = detail.spending.categories.filter((c) => c.planned);
  if (detail.trip.status !== "finished" || (!detail.trip.budget && rows.length === 0)) return null;
  return (
    <section className="card" aria-labelledby="planned-actual">
      <div className="card-head">
        <h2 id="planned-actual">Planned against actual</h2>
      </div>
      <div className="table-wrap">
      <table className="holdings">
        <thead>
          <tr>
            <th scope="col">What</th>
            <th scope="col" className="num">
              Planned
            </th>
            <th scope="col" className="num">
              Actual
            </th>
          </tr>
        </thead>
        <tbody>
          {detail.trip.budget && (
            <tr>
              <td>Whole trip</td>
              <td className="num">{formatMoney(detail.trip.budget)}</td>
              <td className="num">{formatMoney(detail.spending.spent)}</td>
            </tr>
          )}
          {rows.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              <td className="num">{c.planned && formatMoney(c.planned)}</td>
              <td className="num">{formatMoney(c.spent)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </section>
  );
}

const KIND_ICON: Record<Booking["kind"], string> = { flight: "✈️", hotel: "🏨", rail: "🚆" };

const localTime = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(
    new Date(`${iso}:00Z`),
  );

function BookingLines({ booking }: { booking: Booking }) {
  if (booking.kind === "hotel") {
    return (
      <span className="caption">
        {booking.check_in && `Check in ${day(booking.check_in)}`}
        {booking.check_out && ` · out ${day(booking.check_out)}`}
        {booking.address && ` · ${booking.address}`}
      </span>
    );
  }
  return (
    <>
      {booking.segments.map((s, n) => (
        <span key={n} className="caption">
          {[s.number, [s.origin, s.destination].filter(Boolean).join(" → ")].filter(Boolean).join(" ")}
          {s.departs && ` · ${localTime(s.departs)}`}
          {s.arrives && ` to ${localTime(s.arrives)}`}
          <br />
        </span>
      ))}
    </>
  );
}

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

function Itinerary({ detail }: { detail: TripDetail }) {
  return (
    <section className="card" aria-labelledby="itinerary">
      <div className="card-head">
        <h2 id="itinerary">Itinerary</h2>
        <span className="caption">From your booking emails; times are local</span>
      </div>
      {detail.bookings.length === 0 ? (
        <p className="state">No bookings yet. Flight, hotel and train confirmations in your email land here.</p>
      ) : (
        <ul className="feed" aria-label="Bookings">
          {detail.bookings.map((b) => (
            <BookingRow key={b.id} booking={b} />
          ))}
        </ul>
      )}
    </section>
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

function SetAside({ detail }: { detail: TripDetail }) {
  const { trip, saving: a } = detail;
  if (trip.status !== "upcoming") return null;
  return (
    <section className="card" aria-labelledby="set-aside">
      <div className="card-head">
        <h2 id="set-aside">Setting money aside</h2>
      </div>
      {!a.pay_schedule ? (
        <p className="muted">Set your pay schedule (Accounting, Plan) and Nexus can plan an amount to put aside each payday.</p>
      ) : a.per_payday ? (
        <>
          <p>
            {formatMoney(a.per_payday)} each payday: about {a.saved && formatMoney(a.saved)} so far, {a.by_start && formatMoney(a.by_start)} by the
            trip ({a.paydays_left} {a.paydays_left === 1 ? "payday" : "paydays"} left
            {a.next_payday && `, next ${day(a.next_payday)}`}).
          </p>
          {a.covers_budget === false && a.suggested && (
            <p className="budget-state-warn">That's short of the budget: {formatMoney(a.suggested)} each payday would cover it.</p>
          )}
          {a.covers_budget && <p className="budget-state-ok-strong">That covers the budget.</p>}
          {a.fits === false && <p className="budget-state-over">With it, the cash-flow forecast to the trip goes below zero.</p>}
          {a.fits && <p className="caption">It fits the cash-flow forecast, where it shows on each payday.</p>}
        </>
      ) : a.suggested ? (
        <p className="muted">
          Put aside about {formatMoney(a.suggested)} on each of the {a.paydays_left} paydays before the trip to cover the budget. Edit the trip
          to plan it.
        </p>
      ) : (
        <p className="muted">Add a budget, or an amount to set aside, and Nexus plans it into your paydays.</p>
      )}
    </section>
  );
}

function SettleUp({ detail }: { detail: TripDetail }) {
  if (detail.owed.length === 0 && detail.trip.companions.length === 0) return null;
  return (
    <section className="card" aria-labelledby="settle-up">
      <div className="card-head">
        <h2 id="settle-up">Settle up</h2>
      </div>
      {detail.owed.length === 0 ? (
        <p className="muted">Nobody owes you for this trip. Split a bill in chat ("split the hotel with Ann") and it shows here.</p>
      ) : (
        <ul className="feed" aria-label="Still owed">
          {detail.owed.map((o) => (
            <li key={o.name} className="run-row">
              <span className="wrap">{o.name}</span>
              <span className="num">
                {o.amounts.map(formatMoney).join(" + ")}
                {o.home && o.amounts.some((m) => m.currency !== o.home?.currency) && <span className="caption"> (about {formatMoney(o.home)})</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One trip: its budget, spending, set-aside, settle-up and expenses. */
export function TripPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const home = useHome();
  const detail = useQuery({ queryKey: ["trip", id], queryFn: () => api<TripDetail>(`/travel/trips/${id}`) });
  const [editing, setEditing] = useState(false);
  const data = detail.data;
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["trip", id] });
    void client.invalidateQueries({ queryKey: ["trips"] });
  };

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

  return (
    <>
      <div className="page-head">
        <div>
          <p className="caption">
            <Link to="/travel">Trips</Link>
          </p>
          <h1>{data?.trip.destination ?? "Trip"}</h1>
          {data && (
            <p className="muted">
              {day(data.trip.start)} to {day(data.trip.end)} · {data.trip.days} days · {tripWhen(data.trip)} · spending in {data.trip.currency}
              {data.trip.companions.length > 0 && ` · with ${data.trip.companions.join(", ")}`}
            </p>
          )}
        </div>
        {data && !editing && (
          <div className="actions">
            <button type="button" className="btn" onClick={() => setEditing(true)}>
              Edit
            </button>
            <button type="button" className="btn" onClick={() => void remove()}>
              Delete
            </button>
          </div>
        )}
      </div>
      {detail.isLoading && <p className="state">Loading…</p>}
      {detail.isError && (
        <p className="error-text" role="alert">
          {detail.error instanceof Error ? detail.error.message : "Couldn't load that trip."}
        </p>
      )}
      {data && editing && (
        <section className="card" aria-labelledby="edit-trip">
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
        <>
          <Spending detail={data} />
          <Itinerary detail={data} />
          <PlannedVsActual detail={data} />
          <SetAside detail={data} />
          <SettleUp detail={data} />
          <section className="card" aria-labelledby="trip-expenses">
            <div className="card-head">
              <h2 id="trip-expenses">Expenses</h2>
              <span className="caption">To count something else, like flights paid earlier, tell Nexus "add it to {data.trip.destination}"</span>
            </div>
            {data.items.length === 0 ? (
              <p className="state">None yet.</p>
            ) : (
              <ul className="feed" aria-label="Trip expenses">
                {data.items.map((i) => (
                  <li key={i.transaction_id} className="run-row">
                    <span className="wrap">
                      {i.counterparty ?? "Expense"}
                      <br />
                      <span className="caption">
                        {day(i.day)}
                        {i.category && ` · ${i.category}`}
                        {i.linked && " · added by hand"}
                      </span>
                    </span>
                    <span className="num">
                      {formatMoney(i.amount)}
                      {i.home && i.home.currency !== i.amount.currency && <span className="caption"> ({formatMoney(i.home)})</span>}
                    </span>
                    <button type="button" className="btn btn-small" onClick={() => void takeOff(i.transaction_id)} aria-label={`Take ${i.counterparty ?? "this expense"} off the trip`}>
                      Take off
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </>
  );
}
