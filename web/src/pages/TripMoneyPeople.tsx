import { type FormEvent, useState } from "react";

import {
  api,
  type Balance,
  type BalancePart,
  type PaidByOther,
  type PaidByOtherBody,
  type SettleResult,
  type Trip,
  type TripDetail,
} from "../api";
import { Icon } from "../components/Icon";
import { formatMoney, formatWithHome } from "../format";
import { day } from "./TripBits";
import { tripBody } from "./TripEntry";
import { Button, Row, RowList } from "../components/ui";
import { balanceWords, failure, joinNames, settleConfirmText } from "./tripMoneyText";

// --- Travellers, splitting, costs others paid, and settling up --------------------------

/** Names as chips after "You", with a field to add more. It saves nothing: ``onChange`` gets
 * the new list (the trip form keeps it for Save, the Travellers card saves it at once).
 * ``addOnBlur``: a name typed and left behind is added, so Save doesn't lose it. */
export function NameChips({
  names,
  onChange,
  busy = false,
  addOnBlur = false,
  max = 12,
}: {
  names: string[];
  onChange: (names: string[]) => void;
  busy?: boolean;
  addOnBlur?: boolean;
  max?: number;
}) {
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  function add() {
    const found = text.split(",").map((n) => n.trim()).filter(Boolean);
    if (found.length === 0) return;
    const next = [...names];
    for (const name of found) {
      if (!next.some((n) => n.toLowerCase() === name.toLowerCase()) && name.toLowerCase() !== "you") next.push(name);
    }
    if (next.length > max) {
      setProblem(`At most ${max} people on a trip`);
      return;
    }
    setProblem(null);
    setText("");
    if (next.length !== names.length) onChange(next);
  }

  return (
    <div className="name-chips-wrap">
      <ul className="name-chips" aria-label="Who's going">
        <li className="name-chip name-chip-you">You</li>
        {names.map((n) => (
          <li key={n} className="name-chip">
            <span className="wrap">{n}</span>
            <button type="button" className="chip-x" disabled={busy} aria-label={`Remove ${n}`} onClick={() => onChange(names.filter((x) => x !== n))}>
              <span aria-hidden="true">×</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="name-add">
        <label className="field">
          Add a traveller
          <input
            className="input"
            value={text}
            maxLength={100}
            disabled={busy}
            placeholder="A name"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                add();
              }
            }}
            onBlur={() => addOnBlur && add()}
          />
        </label>
        {!addOnBlur && (
          <Button variant="secondary" disabled={busy || text.trim() === ""} onClick={add}>
            Add
          </Button>
        )}
      </div>
      {problem && (
        <p className="error-text" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}

/** Who's going, saved with the trip as people are added or removed, and whether costs are
 * offered for an even split. */
export function TravellersPanel({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(work: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      await work();
      onChange();
    } catch (e) {
      setError(failure(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  const save = (companions: string[]) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}`, { method: "PUT", body: tripBody(trip, { companions }) });
    }, "Couldn't save that");

  const setEvenly = (on: boolean) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}/split-evenly`, { method: "PUT", body: { on } });
    }, "Couldn't change that");

  return (
    <>
      <p className="money-note">Add the people going to split costs and settle up with them</p>
      <NameChips names={trip.companions} busy={busy} onChange={(names) => void save(names)} />
      {trip.companions.length > 0 && (
        <div className="money-switch">
          <button
            type="button"
            role="switch"
            aria-checked={trip.split_evenly}
            aria-describedby="trip-split-note"
            className="switch-row"
            disabled={busy}
            onClick={() => void setEvenly(!trip.split_evenly)}
          >
            <span>Split costs evenly</span>
            <span className="switch-track" aria-hidden="true">
              <span className="switch-thumb" />
            </span>
          </button>
          <p className="money-note" id="trip-split-note">
            {trip.split_evenly
              ? "Costs on this trip are offered for an even split. Nothing changes until you split them."
              : "Off: costs aren't offered for splitting here. You can still split a bill in chat."}
          </p>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

const today = () => new Date().toLocaleDateString("en-CA");

/** Someone else paid for something and the user shares it: who, how much, what, when and who
 * shares it. Adds a payment, or changes ``payment``. */
export function PaidForm({ trip, home, payment, onChange, onDone }: { trip: Trip; home: string; payment?: PaidByOther; onChange: () => void; onDone: () => void }) {
  const travellers = payment && !trip.companions.includes(payment.person) ? [payment.person, ...trip.companions] : trip.companions;
  const [who, setWho] = useState(payment?.person ?? trip.companions[0] ?? "");
  const [value, setValue] = useState(payment ? String(Number(payment.amount.amount)) : "");
  const [currency, setCurrency] = useState(payment?.amount.currency ?? home);
  const [note, setNote] = useState(payment?.note ?? "");
  const [paidOn, setPaidOn] = useState(payment?.paid_on ?? today());
  const sharers = travellers.filter((n) => n !== who);
  // Everyone shares by default; these are the ones taken out.
  const [without, setWithout] = useState<string[]>(payment ? travellers.filter((n) => n !== payment.person && !payment.split_with.includes(n)) : []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = who !== "" && Number(value.replace(/,/g, "")) > 0 && /^[A-Za-z]{3}$/.test(currency.trim());

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    const body: PaidByOtherBody = {
      person: who,
      amount: value.replace(/,/g, "").trim(),
      currency: currency.trim().toUpperCase(),
      note: note.trim() || null,
      paid_on: paidOn || null,
      split_with: sharers.filter((n) => !without.includes(n)),
    };
    try {
      await api(`/travel/trips/${trip.id}/paid-by-others${payment ? `/${payment.id}` : ""}`, { method: payment ? "PUT" : "POST", body });
      onChange();
      onDone();
    } catch (e) {
      setError(failure(e, "Couldn't save that"));
      setBusy(false);
    }
  }

  const label = payment ? `Change what ${payment.person} paid` : "Someone else paid";
  return (
    <form className="paid-form" onSubmit={(e) => void submit(e)} aria-label={label}>
      <div className="paid-grid">
        <label className="field">
          Who paid
          <select className="input" value={who} onChange={(e) => setWho(e.target.value)} autoFocus>
            {travellers.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Amount
          <input className="input" value={value} inputMode="decimal" onChange={(e) => setValue(e.target.value)} placeholder="0" />
        </label>
        <label className="field">
          Currency
          <input className="input" value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
        </label>
        <label className="field">
          What it was for
          <input className="input" value={note} maxLength={100} onChange={(e) => setNote(e.target.value)} placeholder="Ryokan, taxi, dinner…" />
        </label>
        <label className="field">
          Date
          <input className="input" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </label>
      </div>
      {sharers.length > 0 && (
        <fieldset className="field-group">
          <legend>Split with (you're in it too)</legend>
          <div className="check-list">
            {sharers.map((n) => (
              <label key={n} className="check-row">
                <input
                  type="checkbox"
                  checked={!without.includes(n)}
                  onChange={(e) => setWithout(e.target.checked ? without.filter((x) => x !== n) : [...without, n])}
                />
                {n}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <div className="people-actions">
        <Button type="submit" variant="primary" disabled={!ready || busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
        <Button onClick={onDone} disabled={busy}>
          Cancel
        </Button>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}


export function BalanceParts({ b, id }: { b: Balance; id: string }) {
  const line = (p: BalancePart, fallback: string) => (
    <li key={`${p.kind}-${p.id}`} className="peek-row">
      <span className="caption peek-day">{p.on ? day(p.on) : ""}</span>
      <span className="wrap">{p.label ?? fallback}</span>
      <span className="num">{formatWithHome(p.amount, p.home)}</span>
    </li>
  );
  return (
    <div className="peek todo-parts" id={id}>
      {b.owes_you.length > 0 && (
        <>
          <h3 className="caption">{b.person} owes you</h3>
          <ul className="peek-list" aria-label={`What ${b.person} owes you`}>
            {b.owes_you.map((p) => line(p, "Shared bill"))}
          </ul>
        </>
      )}
      {b.you_owe.length > 0 && (
        <>
          <h3 className="caption">You owe {b.person}</h3>
          <ul className="peek-list" aria-label={`What you owe ${b.person}`}>
            {b.you_owe.map((p) => line(p, `Paid by ${b.person}`))}
          </ul>
        </>
      )}
    </div>
  );
}

/** One person to settle with: where you stand, Settle up (confirmed in place first), and the items behind it. */
export function SettleRow({ trip, b, onSettled }: { trip: Trip; b: Balance; onSettled: (result: SettleResult) => void }) {
  const key = b.person.replace(/\W+/g, "-");
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [log, setLog] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasParts = b.owes_you.length + b.you_owe.length > 0;
  const hasShare = b.you_owe.length > 0;

  async function settle() {
    setBusy(true);
    setError(null);
    try {
      const result = await api<SettleResult>(`/travel/trips/${trip.id}/settle`, {
        method: "POST",
        body: { person: b.person, log: hasShare && log },
      });
      onSettled(result);
    } catch (e) {
      setError(failure(e, "Couldn't mark that settled"));
      setBusy(false);
    }
  }

  return (
    <li className="todo-item">
      <div className="todo-row">
        <span className="todo-avatar" aria-hidden="true">
          {b.person.trim().charAt(0).toUpperCase()}
        </span>
        <div className="todo-text">
          <span className="todo-title">{balanceWords(b)}</span>
          {b.net === null && b.net_by_currency.length > 0 && (
            <span className="todo-sub">Some of this is in other currencies with no exchange rate yet, so it isn't added into one amount.</span>
          )}
        </div>
        {hasParts && !confirming && (
          <Button variant="secondary" aria-label={`Settle up with ${b.person}`} onClick={() => setConfirming(true)}>
            Settle up
          </Button>
        )}
      </div>
      {hasParts && (
        <Button variant="text" size="sm" className="todo-more" aria-expanded={open} aria-controls={`settle-parts-${key}`} onClick={() => setOpen(!open)}>
          Details
          <Icon name="chevron" size={16} className="money-chev" />
        </Button>
      )}
      {open && <BalanceParts b={b} id={`settle-parts-${key}`} />}
      {confirming && (
        <div className="confirm-box" role="group" aria-label={`Settle up with ${b.person}`}>
          <p>{settleConfirmText(b, hasShare && log)}</p>
          {hasShare && (
            <label className="check-row">
              <input type="checkbox" checked={log} disabled={busy} onChange={(e) => setLog(e.target.checked)} />
              Also record my share as spent
            </label>
          )}
          <div className="people-actions">
            <Button variant="primary" disabled={busy} onClick={() => void settle()}>
              {busy ? "Recording…" : "Mark settled"}
            </Button>
            <Button variant="text" disabled={busy} onClick={() => setConfirming(false)}>
              Not now
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** What fellow travellers paid for, each with a way to change or remove it. Settled ones stay, muted. */
export function PaidByOthersPanel({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const { trip, paid_by_others: payments } = detail;
  const home = detail.spending?.spent.currency ?? detail.trip.currency; // spending is null only for a member, who never sees this
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove(p: PaidByOther) {
    setBusy(true);
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}/paid-by-others/${p.id}`, { method: "DELETE" });
      setRemoving(null);
      onChange();
    } catch (e) {
      setError(failure(e, "Couldn't remove that"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="money-note">Your share is what you owe them</p>
      <RowList aria-label="Paid by others">
        {payments.map((p) => {
          const what = `${p.person}${p.note ? `, ${p.note}` : ""}`;
          if (editing === p.id) {
            return (
              <li key={p.id}>
                <PaidForm trip={trip} home={home} payment={p} onChange={onChange} onDone={() => setEditing(null)} />
              </li>
            );
          }
          return (
            <Row
              key={p.id}
              className={p.settled ? "is-settled" : undefined}
              title={`${p.person} paid${p.note ? ` for ${p.note}` : ""}`}
              sub={`${day(p.paid_on)} · split with you${p.split_with.length > 0 ? `, ${joinNames(p.split_with)}` : ""}${p.settled ? " · settled" : ""}`}
              trailing={
                <>
                  <span>{formatMoney(p.amount)}</span>
                  <span className="row-sub">your share {formatMoney(p.my_share)}</span>
                </>
              }
              actions={
                !p.settled && removing !== p.id ? (
                  <>
                    <Button variant="text" size="sm" aria-label={`Change what ${what} paid`} onClick={() => setEditing(p.id)}>
                      <Icon name="edit" size={16} />
                      Edit
                    </Button>
                    <Button variant="danger" size="sm" aria-label={`Remove what ${what} paid`} onClick={() => setRemoving(p.id)}>
                      Remove
                    </Button>
                  </>
                ) : undefined
              }
            >
              {removing === p.id && (
                <div className="confirm-box" role="group" aria-label={`Remove what ${what} paid`}>
                  <p>Remove this? It won't count towards what you owe {p.person}.</p>
                  <div className="people-actions">
                    <Button variant="danger" disabled={busy} onClick={() => void remove(p)}>
                      Remove
                    </Button>
                    <Button disabled={busy} onClick={() => setRemoving(null)}>
                      Keep
                    </Button>
                  </div>
                </div>
              )}
            </Row>
          );
        })}
      </RowList>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
