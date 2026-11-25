import { type ReactNode, useEffect, useState } from "react";

import { api, type Cover, type TripDetail } from "../api";
import { Icon } from "../components/Icon";
import { formatMoney, formatWithHome } from "../format";
import { CountUp } from "../motion";
import { day } from "./TripBits";
import { KIND_LABEL, LogAction, LogConfirm, useCoverLog } from "./TripPrepParts";
import { stageOf } from "./TripStage";
import { Button, Row, RowList, Section } from "../components/ui";
import { amount, failure, joinNames, moneyOf, plannedAhead, plural, positive } from "./tripMoneyText";
import { PaidByOthersPanel, PaidForm, TravellersPanel } from "./TripMoneyPeople";
import { PlannedPanel, SetAside, TodoCard, WhereItGoes } from "./TripMoneyPlan";

export { NameChips } from "./TripMoneyPeople";
export { SpendingRow } from "./TripMoneyPlan";
export { balanceWords, joinNames, partsTotal, plannedAhead, setAsideText, settleConfirmText, settledText, splitAskText, splitConfirmText, sumByCurrency, toSplitSub, totalOf } from "./tripMoneyText";



/** The + on the Money tab, once someone else is going: a planned cost, or a cost someone else paid. */
function AddChoice({ onPick, onCancel }: { onPick: (kind: "planned" | "paid") => void; onCancel: () => void }) {
  return (
    <Section id="add-choice" title="What are you adding?">
      <div className="people-actions choice-actions">
        <Button variant="secondary" onClick={() => onPick("planned")}>
          A planned cost
        </Button>
        <Button variant="secondary" onClick={() => onPick("paid")}>
          Someone else paid
        </Button>
        <Button variant="text" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Section>
  );
}

/** How an expense stands with the people going, from what the trip already says: still to
 * split, kept as just mine, or (once costs are offered and it isn't either) split. */
function expenseTag(detail: TripDetail, id: string): { text: string; split: boolean } | null {
  const { trip } = detail;
  if (trip.companions.length === 0) return null;
  if (detail.just_mine.includes(id)) return { text: "Just mine", split: false };
  if (!trip.split_evenly) return null;
  if (detail.to_split.some((c) => c.transaction_id === id)) return { text: "To split", split: true };
  return { text: `Split with ${joinNames(trip.companions)}`, split: false };
}

/** Every expense on the trip, each tagged and with a way to take it off; and where someone else's payment is added. */
function ExpensesPanel({
  detail,
  onTakeOff,
  onChange,
  paying,
  onPay,
  onPayDone,
}: {
  detail: TripDetail;
  onTakeOff: (transactionId: string) => void;
  onChange: () => void;
  paying: boolean;
  onPay: () => void;
  onPayDone: () => void;
}) {
  const { trip } = detail;
  const home = detail.spending?.spent.currency ?? trip.currency; // spending is null only for a member, who never sees this
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function offerAgain(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}/keep-mine`, { method: "POST", body: { transaction_ids: [id], keep: false } });
      onChange();
    } catch (e) {
      setError(failure(e, "Couldn't change that"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="money-note">To count something else, like flights paid earlier, tell Nexus "add it to {trip.destination}"</p>
      {detail.items.length === 0 ? (
        <p className="money-note">None yet.</p>
      ) : (
        <RowList aria-label="Trip expenses">
          {detail.items.map((i) => {
            const tag = expenseTag(detail, i.transaction_id);
            const name = i.counterparty ?? "this cost";
            return (
              <Row
                key={i.transaction_id}
                title={i.counterparty ?? "Expense"}
                sub={
                  <>
                    {day(i.day)}
                    {i.category && ` · ${i.category}`}
                    {i.linked && " · added by hand"}
                    {tag && (
                      <>
                        {" · "}
                        <span className={`money-tag${tag.split ? " money-tag-split" : ""}`}>{tag.text}</span>
                      </>
                    )}
                  </>
                }
                trailing={formatWithHome(i.amount, i.home)}
                actions={
                  <>
                    {tag?.text === "Just mine" && trip.split_evenly && (
                      <Button variant="text" size="sm" disabled={busy} aria-label={`Offer ${name} for splitting again`} onClick={() => void offerAgain(i.transaction_id)}>
                        Offer again
                      </Button>
                    )}
                    <Button variant="text" size="sm" onClick={() => onTakeOff(i.transaction_id)} aria-label={`Take ${i.counterparty ?? "this expense"} off the trip`}>
                      Take off
                    </Button>
                  </>
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
      {trip.companions.length > 0 &&
        (paying ? (
          <div className="money-form">
            <p className="money-note">Your share is what you owe them. Nothing is added to your spending until you settle up.</p>
            <PaidForm trip={trip} home={home} onChange={onChange} onDone={onPayDone} />
          </div>
        ) : (
          <Button variant="text" className="money-add" onClick={onPay}>
            <Icon name="plus" size={16} />
            Someone else paid
          </Button>
        ))}
    </>
  );
}


/** A cover or document with a cost, listed with the bookings: "Logged", or Log it (asked first, in place). */
function CoverPaid({ cover, tripId, onChange }: { cover: Cover; tripId: string; onChange: () => void }) {
  const log = useCoverLog(tripId, cover, () => onChange());
  return (
    <Row
      title={cover.name}
      sub={`${KIND_LABEL[cover.kind]} · from Prep`}
      trailing={cover.cost && formatMoney(cover.cost)}
      actions={<LogAction cover={cover} log={log} />}
    >
      {log.confirming && <LogConfirm cover={cover} log={log} />}
    </Row>
  );
}

/** The bookings on the trip that carry a cost, and how much of it isn't logged as an expense yet.
 * Covers and documents from Prep that cost something are listed after them. */
function BookingsPanel({ detail, onChange }: { detail: TripDetail; onChange: () => void }) {
  const costed = bookingsPaid(detail);
  const covers = coversPaid(detail);
  const unlogged = detail.booked_unlogged;
  return (
    <>
      {positive(unlogged) && <p className="money-note">{formatMoney(unlogged)} not logged as an expense yet</p>}
      <RowList aria-label="Bookings paid">
        {costed.map((b) => (
          <Row
            key={b.id}
            title={b.title}
            sub={`${day(b.starts)} · ${b.logged ? "Logged as an expense" : "Not logged yet"}`}
            trailing={b.cost && formatMoney(b.cost)}
          />
        ))}
        {covers.map((c) => (
          <CoverPaid key={c.id} cover={c} tripId={detail.trip.id} onChange={onChange} />
        ))}
      </RowList>
    </>
  );
}

/** The trip's bookings that carry a cost (a place to visit with no day isn't booked yet). */
const bookingsPaid = (detail: TripDetail) => detail.bookings.filter((b) => b.cost !== null && b.scheduled);
/** The covers and documents from Prep that carry a cost (the owner's: a member never has one). */
const coversPaid = (detail: TripDetail) => (detail.covers ?? []).filter((c) => c.cost !== null);

type SectionId = "where" | "planned" | "aside" | "bookings" | "expenses" | "paid" | "travellers";

/** One row of the Details accordion: a 56px header button, and its content when open. */
function DetailRow({ id, title, summary, open, onToggle, children }: { id: SectionId; title: string; summary: string; open: boolean; onToggle: () => void; children: ReactNode }) {
  const base = `money-sec-${id}`;
  return (
    <div className="money-sec">
      <h3 className="money-sec-h">
        <button type="button" className="money-sec-btn" aria-expanded={open} aria-controls={`${base}-panel`} onClick={onToggle}>
          <span className="money-sec-title" id={`${base}-title`}>
            {title}
          </span>
          <span className="money-sec-sum">{summary}</span>
          <Icon name="chevron" size={16} className="money-chev" />
        </button>
      </h3>
      <div className="money-sec-panel" id={`${base}-panel`} role="region" aria-labelledby={`${base}-title`} hidden={!open}>
        {open && children}
      </div>
    </div>
  );
}

/** The one card at the top of the Money tab. Before the trip: spent and booked against the
 * budget, with what's planned still to come. While it's on: spent so far. After: what it cost. */
export function MoneySummary({ detail }: { detail: TripDetail }) {
  const s = detail.spending;
  if (!s) return null; // a member of the trip gets no money
  const t = detail.trip;
  const stage = stageOf(detail);
  const after = stage === "after";
  const cur = s.spent.currency;
  const budget = t.budget ? Number(t.budget.amount) : null;
  const spent = amount(s.spent);
  const booked = after ? 0 : Math.max(0, amount(detail.booked_unlogged));
  const planned = after ? 0 : Math.max(0, plannedAhead(detail));
  const committed = spent + booked + planned;
  const headline = stage === "planning" || stage === "soon" ? spent + booked : spent;
  const label = after ? "The trip cost" : stage === "during" ? "Spent so far" : "Spent and booked";
  const parts = [
    { key: "spent", text: "Spent", value: spent },
    { key: "booked", text: "Booked", value: booked },
    { key: "planned", text: "Planned", value: planned },
  ].filter((p) => p.value > 0);
  const scale = budget !== null ? Math.max(budget, committed) : committed;
  const left = budget !== null ? budget - committed : null;
  const over = left !== null && left < 0;
  const diff = after && budget ? Math.round(((spent - budget) / budget) * 100) : null;
  const daysLeft = Math.max(t.days - (t.day_number ?? 1) + 1, 1);
  const local = detail.items.filter((i) => i.amount.currency === t.currency).reduce((sum, i) => sum + Number(i.amount.amount), 0);
  const nowLine = [
    positive(s.per_day_left) && `${formatMoney(s.per_day_left)} a day left for ${plural(daysLeft, "day")}`,
    positive(s.today) && `${formatMoney(s.today)} today`,
    local > 0 && t.currency !== cur && `${formatMoney(moneyOf(local, t.currency))} spent in ${t.currency}`,
  ].filter(Boolean);
  const barLabel = `${parts.map((p) => `${p.text.toLowerCase()} ${formatMoney(moneyOf(p.value, cur))}`).join(", ") || "nothing yet"}${t.budget ? ` of ${formatMoney(t.budget)}` : ""}`;

  return (
    <Section id="money-summary" title={label} className="money-summary">
      <p className="money-figure">
        <CountUp value={formatMoney(moneyOf(headline, cur))} />
        {t.budget && <> <span className="money-of">of {formatMoney(t.budget)}</span></>}
      </p>
      {budget !== null && scale > 0 && (
        <div className={`money-track${over || (diff !== null && diff > 0) ? " is-over" : ""}`} role="img" aria-label={barLabel}>
          {(after ? [{ key: "spent", text: "Spent", value: spent }] : parts).map((p) => (
            <span key={p.key} className={`money-seg money-seg-${p.key}`} style={{ width: `${(p.value / scale) * 100}%` }} />
          ))}
        </div>
      )}
      {!after && parts.length > 0 && (
        <p className="money-legend">
          {parts.map((p, n) => (
            <span key={p.key}>
              {n > 0 && <span aria-hidden="true"> · </span>}
              <span className={`money-key money-seg-${p.key}`} aria-hidden="true" />
              {p.text} {formatMoney(moneyOf(p.value, cur))}
            </span>
          ))}
        </p>
      )}
      {!after && left !== null && (
        <p className={`money-left${over ? " money-over" : ""}`}>
          {over ? "Over by " : "Left after planned costs "}
          <span className="num">{formatMoney(moneyOf(Math.abs(left), cur))}</span>
        </p>
      )}
      {stage === "during" && nowLine.length > 0 && <p className="money-note">{nowLine.join(" · ")}</p>}
      {stage === "during" && <p className="money-note">Log what you spend on Telegram: "ramen 1200 yen".</p>}
      {after && diff !== null && (
        <p className={`money-left${diff > 0 ? " money-over" : ""}`}>{diff === 0 ? "On budget" : `${Math.abs(diff)}% ${diff > 0 ? "over" : "under"} budget`}</p>
      )}
      {after && t.companions.length > 0 && <p className="money-note">Your share, with {joinNames(t.companions)}</p>}
    </Section>
  );
}

/** The Money tab: one summary, what needs doing, then the details one section at a time.
 * ``adding``: the tab's + was pressed: a planned cost, or (with other travellers) a choice
 * between that and a cost someone else paid. */
export function MoneyTab({ detail, onChange, adding, onAddDone }: { detail: TripDetail; onChange: () => void; adding: boolean; onAddDone: () => void }) {
  const stage = stageOf(detail);
  const { trip } = detail;
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"planned" | "paid" | null>(null);
  const [form, setForm] = useState<"planned" | "paid" | null>(null);
  const [open, setOpen] = useState<SectionId | null>(null);
  const hasOthers = trip.companions.length > 0;
  useEffect(() => {
    if (!adding) setKind(null);
  }, [adding]);
  const adds = adding ? (hasOthers ? kind : "planned") : null;
  // The tab's + opens the section its form lives in.
  useEffect(() => {
    if (adds) setOpen(adds === "planned" ? "planned" : "expenses");
  }, [adds]);
  const showForm = (which: "planned" | "paid") => adds === which || form === which;
  const formDone = () => {
    setForm(null);
    if (adding) onAddDone();
  };

  async function takeOff(transactionId: string) {
    setError(null);
    try {
      await api(`/travel/trips/${trip.id}/expenses/${transactionId}`, { method: "DELETE" });
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't take that off");
    }
  }

  const s = detail.spending;
  const toggle = (id: SectionId) => setOpen(open === id ? null : id);
  const planned = Object.keys(trip.planned).length;
  const costed = bookingsPaid(detail).length + coversPaid(detail).length;
  const payments = detail.paid_by_others;
  const todo = <TodoCard detail={detail} onChange={onChange} />;
  return (
    <>
      {adding && hasOthers && kind === null && <AddChoice onPick={setKind} onCancel={onAddDone} />}
      {/* After the trip, settling up comes first, then what it cost. */}
      {stage === "after" && todo}
      <MoneySummary detail={detail} />
      {stage !== "after" && todo}
      <Section id="money-details" title="Details" className="money-details">
        <div className="money-secs">
          <DetailRow id="where" title="Where it goes" summary={s ? plural(s.categories.length, "category", "categories") : ""} open={open === "where"} onToggle={() => toggle("where")}>
            <WhereItGoes detail={detail} />
          </DetailRow>
          <DetailRow id="planned" title="Planned costs" summary={planned === 0 ? "None yet" : plural(planned, "cost")} open={open === "planned"} onToggle={() => toggle("planned")}>
            <PlannedPanel detail={detail} onChange={onChange} adding={showForm("planned")} onAdd={() => setForm("planned")} onAddDone={formDone} />
          </DetailRow>
          {detail.saving && trip.status === "upcoming" && (
            <DetailRow id="aside" title="Setting money aside" summary={positive(detail.saving.per_payday) ? "Monthly" : "Not set"} open={open === "aside"} onToggle={() => toggle("aside")}>
              <SetAside detail={detail} />
            </DetailRow>
          )}
          {costed > 0 && (
            <DetailRow id="bookings" title="Bookings paid" summary={plural(costed, "booking")} open={open === "bookings"} onToggle={() => toggle("bookings")}>
              <BookingsPanel detail={detail} onChange={onChange} />
            </DetailRow>
          )}
          <DetailRow id="expenses" title="Expenses" summary={detail.items.length === 0 ? "None yet" : `${detail.items.length} so far`} open={open === "expenses"} onToggle={() => toggle("expenses")}>
            <ExpensesPanel detail={detail} onTakeOff={(t) => void takeOff(t)} onChange={onChange} paying={showForm("paid")} onPay={() => setForm("paid")} onPayDone={formDone} />
          </DetailRow>
          {payments.length > 0 && (
            <DetailRow id="paid" title="Paid by others" summary={plural(payments.length, "payment")} open={open === "paid"} onToggle={() => toggle("paid")}>
              <PaidByOthersPanel detail={detail} onChange={onChange} />
            </DetailRow>
          )}
          <DetailRow id="travellers" title="Travellers" summary={joinNames(["You", ...trip.companions])} open={open === "travellers"} onToggle={() => toggle("travellers")}>
            <TravellersPanel trip={trip} onChange={onChange} />
          </DetailRow>
        </div>
      </Section>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
