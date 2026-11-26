import { type FormEvent, useEffect, useState } from "react";

import { api, type SplitBody, type SplitResult, type Trip, type TripDetail, type TripSpending } from "../api";
import { Icon } from "../components/Icon";
import { formatMoney, formatWithHome } from "../format";
import { day } from "./TripBits";
import { tripBody } from "./TripEntry";
import { Button, Row, RowList, Section } from "../components/ui";
import { amount, failure, joinNames, moneyList, moneyOf, plural, positive, sameName, setAsideText, settledText, splitAskText, sumByCurrency, toSplitSub } from "./tripMoneyText";
import { SettleRow } from "./TripMoneyPeople";

type TripCategory = TripSpending["categories"][number];

/** One category's bar; tapping it lists the trip's expenses in it. */
export function SpendingRow({ category: c, biggest, items }: { category: TripCategory; biggest: number; items: TripDetail["items"] }) {
  const [open, setOpen] = useState(false);
  const id = `trip-cat-${c.name.replace(/\W+/g, "-")}`;
  const row = (
    <>
      <span className="wrap">{c.name}</span>
      <span className="bar-track">
        <span className="bar" style={{ width: `${(Number(c.spent.amount) / biggest) * 100}%` }} />
      </span>
      <span className="num">
        {formatMoney(c.spent)}
        {c.planned && <span className="caption"> of {formatMoney(c.planned)}</span>}
      </span>
    </>
  );
  if (items.length === 0) {
    return <li className="bar-row">{row}</li>;
  }
  return (
    <li className="bar-item">
      <button
        type="button"
        className="bar-row bar-toggle"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`${c.name}: ${formatMoney(c.spent)}${c.planned ? ` of ${formatMoney(c.planned)}` : ""}, ${items.length} ${items.length === 1 ? "expense" : "expenses"}`}
        onClick={() => setOpen(!open)}
      >
        {row}
        <span className="chevron" aria-hidden="true" />
      </button>
      {open && (
        <div className="peek" id={id}>
          <ul className="peek-list" aria-label={`${c.name} expenses`}>
            {items.map((i) => (
              <li key={i.transaction_id} className="peek-row">
                <span className="caption peek-day">{day(i.day)}</span>
                <span className="wrap">{i.counterparty ?? "Expense"}</span>
                <span className="num">
                  {formatWithHome(i.amount, i.home)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

/** Spending by category (each opening to its expenses), and after the trip planned against actual. */
export function WhereItGoes({ detail }: { detail: TripDetail }) {
  const { trip, spending: s } = detail;
  if (!s) return null; // a member of the trip gets no money
  const biggest = Math.max(1, ...s.categories.map((c) => Number(c.spent.amount)));
  const planned = s.categories.filter((c) => c.planned);
  const compare = trip.status === "finished" && (trip.budget !== null || planned.length > 0);
  const notes = [
    Number(s.before.amount) > 0 && `${formatMoney(s.before)} was spent before the trip.`,
    s.per_day && Number(s.per_day.amount) > 0 && `An average of ${formatMoney(s.per_day)} a day.`,
  ].filter(Boolean);
  return (
    <>
      <p className="money-note">Your share, in {s.spent.currency} at each day's rate</p>
      {s.categories.length > 0 && (
        <ul className="bars" aria-label="Biggest categories">
          {s.categories.slice(0, trip.status === "finished" ? undefined : 5).map((c) => (
            <SpendingRow
              key={c.name}
              category={c}
              biggest={biggest}
              items={detail.items.filter((i) => (i.category ?? "Uncategorised") === c.name)}
            />
          ))}
        </ul>
      )}
      {detail.items.length === 0 && (
        <p className="money-note">
          Nothing spent yet. Expenses in {trip.currency} between {day(trip.start)} and {day(trip.end)} count by themselves.
        </p>
      )}
      {notes.length > 0 && <p className="money-note">{notes.join(" ")}</p>}
      {s.unconverted > 0 && <p className="money-note">{s.unconverted} expenses have no exchange rate yet and aren't counted.</p>}
      {compare && (
        <div className="table-wrap">
          <table className="holdings" aria-label="Planned against actual">
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
              {trip.budget && (
                <tr>
                  <td>Whole trip</td>
                  <td className="num">{formatMoney(trip.budget)}</td>
                  <td className="num">{formatMoney(s.spent)}</td>
                </tr>
              )}
              {planned.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  <td className="num">{c.planned && formatMoney(c.planned)}</td>
                  <td className="num">{formatMoney(c.spent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function SetAside({ detail }: { detail: TripDetail }) {
  const a = detail.saving;
  if (!a) return null;
  return !a.pay_schedule ? (
    <p className="muted">Set your pay schedule (Money, Budgets) and Nexus can plan an amount to put aside each payday.</p>
  ) : positive(a.per_payday) ? (
    <>
      <p>{setAsideText(a, a.next_payday ? day(a.next_payday) : null)}</p>
      {a.covers_budget === false && positive(a.suggested) && (
        <p className="budget-state-warn">That's short of the budget: {formatMoney(a.suggested)} each payday would cover it.</p>
      )}
      {a.covers_budget && <p className="budget-state-ok-strong">That covers the budget.</p>}
      {a.fits === false && <p className="budget-state-over">With it, the cash-flow forecast to the trip goes below zero.</p>}
      {a.fits && <p className="money-note">It fits the cash-flow forecast, where it shows on each payday.</p>}
    </>
  ) : positive(a.suggested) ? (
    <p className="muted">
      Put aside about {formatMoney(a.suggested)} on each of the {a.paydays_left} paydays before the trip to cover the budget. Edit the trip to plan it.
    </p>
  ) : (
    <p className="muted">Add a budget, or an amount to set aside, and Nexus plans it into your paydays.</p>
  );
}

/** What needs doing with the people going: costs to split and people to settle up with. Only
 * there when someone else is going (or something was just done); otherwise nothing. */
export function TodoCard({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const { trip, balances } = detail;
  const home = detail.spending?.spent.currency ?? trip.currency; // spending is null only for a member, who never sees this
  const others = trip.companions;
  const items = detail.to_split;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [seeing, setSeeing] = useState(false);
  const [outcome, setOutcome] = useState<{ result: SplitResult; names: Map<string, string> } | null>(null);
  const [done, setDone] = useState<string[]>([]);
  useEffect(() => {
    if (items.length === 0) {
      setConfirming(false);
      setSeeing(false);
    }
  }, [items.length]);
  if (others.length === 0 && balances.length === 0 && !outcome && done.length === 0) return null;

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

  const split = (body: SplitBody) =>
    run(async () => {
      const names = new Map(items.map((i) => [i.transaction_id, i.counterparty ?? "Expense"]));
      const result = await api<SplitResult>(`/travel/trips/${trip.id}/split`, { method: "POST", body });
      setConfirming(false);
      setOutcome({ result, names });
    }, "Couldn't split that");

  const keepMine = (ids: string[]) =>
    run(async () => {
      await api(`/travel/trips/${trip.id}/keep-mine`, { method: "POST", body: { transaction_ids: ids, keep: true } });
      setOutcome(null);
    }, "Couldn't change that");

  return (
    <Section id="money-todo" title="To do" className="money-todo">
      {balances.length > 0 && <p className="money-note">Nexus records what you say happened. It doesn't move money.</p>}
      {outcome && (
        <div className="split-outcome" role="status">
          {outcome.result.done.length > 0 && (
            <p>
              Split {plural(outcome.result.done.length, "cost")} evenly with {joinNames(outcome.result.with_people)}. Your share is{" "}
              {moneyList(sumByCurrency(outcome.result.done.map((d) => d.own_share)))}.
            </p>
          )}
          {outcome.result.skipped.length > 0 && (
            <>
              <p>Left alone:</p>
              <ul>
                {outcome.result.skipped.map((s) => (
                  <li key={s.transaction_id}>
                    {outcome.names.get(s.transaction_id) ?? "Expense"}: {s.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {done.length > 0 && (
        <div className="split-outcome" role="status">
          {done.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      )}
      {(items.length > 0 || balances.length > 0) && (
        <ul className="todo-list">
          {items.length > 0 && (
            <li className="todo-item">
              <div className="todo-row">
                <div className="todo-text">
                  <span className="todo-title">{plural(items.length, "cost")} to split</span>
                  <span className="todo-sub">{toSplitSub(items, home)}</span>
                </div>
                {!confirming && (
                  <Button variant="secondary" disabled={busy} aria-label="Split all evenly" onClick={() => setConfirming(true)}>
                    Split
                  </Button>
                )}
              </div>
              {confirming && (
                <div className="confirm-box" role="group" aria-label="Confirm splitting all">
                  <p>{splitAskText(items, others, home)}</p>
                  <div className="people-actions">
                    <Button variant="primary" disabled={busy} onClick={() => void split({ all: true })}>
                      {busy ? "Splitting…" : "Split evenly"}
                    </Button>
                    <Button variant="text" disabled={busy} onClick={() => setConfirming(false)}>
                      Not now
                    </Button>
                  </div>
                </div>
              )}
              <Button variant="text" size="sm" className="todo-more" aria-expanded={seeing} aria-controls="todo-costs" onClick={() => setSeeing(!seeing)}>
                See costs
                <Icon name="chevron" size={16} className="money-chev" />
              </Button>
              {seeing && (
                <RowList id="todo-costs" aria-label="To split">
                  {items.map((i) => {
                    const name = i.counterparty ?? "this cost";
                    return (
                      <Row
                        key={i.transaction_id}
                        title={i.counterparty ?? "Expense"}
                        sub={day(i.day)}
                        trailing={formatWithHome(i.amount, i.home)}
                        actions={
                          <>
                            <Button variant="secondary" size="sm" disabled={busy} aria-label={`Split ${name} evenly`} onClick={() => void split({ transaction_ids: [i.transaction_id] })}>
                              Split
                            </Button>
                            <Button variant="secondary" size="sm" disabled={busy} aria-label={`Keep ${name} as just mine`} onClick={() => void keepMine([i.transaction_id])}>
                              Just mine
                            </Button>
                          </>
                        }
                      />
                    );
                  })}
                </RowList>
              )}
            </li>
          )}
          {balances.map((b) => (
            <SettleRow
              key={b.person}
              trip={trip}
              b={b}
              onSettled={(result) => {
                setDone((was) => [...was, settledText(result)]);
                onChange();
              }}
            />
          ))}
        </ul>
      )}
      {others.length > 0 && items.length === 0 && balances.length === 0 && <p className="todo-quiet">All split and settled with {joinNames(others)}.</p>}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Section>
  );
}

/** The costs planned for the trip, by name, in the home currency. A planned cost is part
 * of the trip itself, so changing one resends the trip as the trip form would. */
async function savePlanned(trip: Trip, planned: Record<string, string>) {
  await api(`/travel/trips/${trip.id}`, { method: "PUT", body: tripBody(trip, { planned }) });
}

/** One planned cost, a name and an amount. */
export function PlannedForm({ trip, currency, onChange, onDone }: { trip: Trip; currency: string; onChange: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = name.trim() !== "" && Number(value) > 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await savePlanned(trip, { ...tripBody(trip).planned, [name.trim()]: String(Number(value)) });
      onChange();
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
      setBusy(false);
    }
  }

  return (
    <div className="money-form">
      <p className="money-note">Something you expect to pay for, like flights or a tour</p>
      <form className="budget-add planned-form" onSubmit={(e) => void submit(e)} aria-label="Add a planned cost">
        <label className="field">
          Name
          <input className="input" value={name} maxLength={60} autoFocus onChange={(e) => setName(e.target.value)} placeholder="Flights, Tour, Visa…" />
        </label>
        <label className="field">
          Amount ({currency})
          <input className="input" value={value} inputMode="decimal" onChange={(e) => setValue(e.target.value)} placeholder="0" />
        </label>
        <Button type="submit" variant="primary" disabled={!ready || busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
        <Button onClick={onDone} disabled={busy}>
          Cancel
        </Button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** What's planned to be paid for, each with a way to drop it, and where one is added. */
export function PlannedPanel({
  detail,
  onChange,
  adding,
  onAdd,
  onAddDone,
}: {
  detail: TripDetail;
  onChange: () => void;
  adding: boolean;
  onAdd: () => void;
  onAddDone: () => void;
}) {
  const { trip } = detail;
  const home = detail.spending?.spent.currency ?? trip.currency; // spending is null only for a member, who never sees this
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const entries = Object.entries(trip.planned);

  async function remove(name: string) {
    const { [name]: _gone, ...rest } = tripBody(trip).planned;
    setBusy(name);
    setError(null);
    try {
      await savePlanned(trip, rest);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove that");
    } finally {
      setBusy(null);
    }
  }

  const spentIn = (name: string) =>
    (detail.spending?.categories ?? []).filter((c) => sameName(c.name, name)).reduce((t, c) => t + amount(c.spent), 0);

  return (
    <>
      <p className="money-note">Counted against the budget once they're spent</p>
      {entries.length === 0 ? (
        <p className="money-note">None yet.</p>
      ) : (
        <RowList aria-label="Planned costs">
          {entries.map(([name, cost]) => {
            const spent = spentIn(name);
            return (
              <Row
                key={name}
                title={name}
                sub={spent > 0 ? `${formatMoney(moneyOf(spent, home))} spent so far` : "Nothing spent yet"}
                trailing={formatMoney(cost)}
                actions={
                  <Button variant="danger" size="sm" disabled={busy !== null} onClick={() => void remove(name)} aria-label={`Remove planned cost ${name}`}>
                    Remove
                  </Button>
                }
              />
            );
          })}
        </RowList>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {adding ? (
        <PlannedForm trip={trip} currency={home} onChange={onChange} onDone={onAddDone} />
      ) : (
        <Button variant="text" className="money-add" onClick={onAdd}>
          <Icon name="plus" size={16} />
          Add a planned cost
        </Button>
      )}
    </>
  );
}
