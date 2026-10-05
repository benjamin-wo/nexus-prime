import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type CashDay, type CashFlow, type Money } from "../api";
import { formatMoney } from "../format";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function monthKey(date: Date): string {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(key: string, by: number): string {
  const [year, month] = key.split("-").map(Number);
  return monthKey(new Date(Date.UTC(year, month - 1 + by, 1)));
}

function monthLabel(key: string): string {
  const [year, month] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(year, month - 1, 1)),
  );
}

/** A compact signed figure for a calendar cell: "+4,200" or "-51". */
function compact(money: Money): string {
  const value = Number(money.amount);
  const shown = new Intl.NumberFormat(undefined, { maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 2 }).format(
    Math.abs(value),
  );
  return `${value > 0 ? "+" : "-"}${shown}`;
}

function isZero(money: Money): boolean {
  return Number(money.amount) === 0;
}

function DayCell({
  day,
  today,
  selected,
  onSelect,
}: {
  day: CashDay;
  today: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const past = day.day <= today;
  const date = Number(day.day.slice(8, 10));
  const label = `${day.day}${past && !isZero(day.net) ? `, net ${formatMoney(day.net)}` : ""}${
    day.expected.length ? `, ${day.expected.length} expected` : ""
  }`;
  return (
    <button
      type="button"
      className={`cal-day${day.day === today ? " is-today" : ""}`}
      aria-pressed={selected}
      aria-label={label}
      onClick={onSelect}
    >
      <span className="cal-date">{date}</span>
      {past && !isZero(day.net) && (
        <span className={`cal-amount ${Number(day.net.amount) > 0 ? "in" : "out"}`}>{compact(day.net)}</span>
      )}
      {day.expected.length > 0 && !isZero(day.expected_net) && (
        <span className={`cal-amount expected ${Number(day.expected_net.amount) > 0 ? "in" : "out"}`}>
          {compact(day.expected_net)}
        </span>
      )}
      {day.expected.length > 0 && isZero(day.expected_net) && <span className="cal-dot" aria-hidden="true" />}
    </button>
  );
}

function DayDetail({ day, today }: { day: CashDay; today: string }) {
  const heading = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(`${day.day}T00:00:00Z`));
  const past = day.day <= today;
  return (
    <section className="card" aria-labelledby="day-detail">
      <div className="card-head">
        <h2 id="day-detail">{heading}</h2>
      </div>
      {past && (
        <p className="secondary">
          Logged: in {formatMoney(day.money_in)}, out {formatMoney(day.money_out)}, net {formatMoney(day.net)}
        </p>
      )}
      {day.expected.length > 0 ? (
        <ul className="budgets" aria-label="Expected">
          {day.expected.map((e, n) => (
            <li key={n} className="budget">
              <div className="budget-head">
                <h3 className="wrap">{e.name}</h3>
                <span className={`num cal-amount ${e.direction}`}>
                  {e.amount ? `${e.direction === "in" ? "+" : "-"}${formatMoney(e.amount)}` : "Amount not set"}
                </span>
              </div>
              <p className="caption">
                {e.kind === "bill" ? "Bill" : e.kind === "subscription" ? "Subscription" : e.kind === "trip" ? "Trip" : "Payday"}
                {e.amount && e.home && e.amount.currency !== e.home.currency ? ` · about ${formatMoney(e.home)}` : ""}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        !past && <p className="state">Nothing expected.</p>
      )}
    </section>
  );
}

/** Net money movement per day: what was logged so far, and what's expected ahead. Never a balance. */
export function CashFlowPage() {
  const [month, setMonth] = useState<string | null>(null);
  const flow = useQuery({
    queryKey: ["cashflow", month],
    queryFn: () => api<CashFlow>(month ? `/cashflow?month=${month}` : "/cashflow"),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const data = flow.data;
  const key = month ?? (data ? data.start.slice(0, 7) : null);
  const lead = data ? (new Date(`${data.start}T00:00:00Z`).getUTCDay() + 6) % 7 : 0;
  const chosen = data?.days.find((d) => d.day === (selected ?? data.today)) ?? null;

  function go(by: number) {
    if (!key) return;
    setSelected(null);
    setMonth(shiftMonth(key, by));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Cash flow</h1>
          <p className="muted">
            What came in and went out each day, and what bills, subscriptions and payday will bring. Movement only, not
            a balance.
          </p>
        </div>
      </div>
      <section className="card" aria-labelledby="month">
        <div className="card-head">
          <h2 id="month">{key ? monthLabel(key) : "This month"}</h2>
          <span className="month-nav">
            <button type="button" className="btn btn-ghost" onClick={() => go(-1)} aria-label="Previous month">
              ‹
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => go(1)} aria-label="Next month">
              ›
            </button>
          </span>
        </div>
        {flow.isLoading && <p className="state">Loading…</p>}
        {flow.isError && <p className="state error-text">Couldn't load cash flow.</p>}
        {data && (
          <>
            <div className="flow-totals">
              <div>
                <p className="caption">Logged in / out</p>
                <p className="num">
                  {formatMoney(data.logged_in)} / {formatMoney(data.logged_out)}
                </p>
              </div>
              <div>
                <p className="caption">Expected in / out</p>
                <p className="num">
                  {formatMoney(data.expected_in)} / {formatMoney(data.expected_out)}
                </p>
              </div>
            </div>
            <div className="cal" role="group" aria-label="Days">
              {WEEKDAYS.map((w) => (
                <span key={w} className="caption cal-head" aria-hidden="true">
                  {w}
                </span>
              ))}
              {Array.from({ length: lead }, (_, n) => (
                <span key={`e${n}`} className="cal-day is-empty" aria-hidden="true" />
              ))}
              {data.days.map((d) => (
                <DayCell
                  key={d.day}
                  day={d}
                  today={data.today}
                  selected={chosen?.day === d.day}
                  onSelect={() => setSelected(d.day)}
                />
              ))}
            </div>
            {data.unknown_amounts > 0 && (
              <p className="caption">
                {data.unknown_amounts} expected item{data.unknown_amounts === 1 ? " has" : "s have"} no amount set, so{" "}
                {data.unknown_amounts === 1 ? "it isn't" : "they aren't"} counted.
              </p>
            )}
            {data.unconverted.length > 0 && (
              <p className="caption">
                Not included, for want of an exchange rate: {data.unconverted.map(formatMoney).join(", ")}
              </p>
            )}
          </>
        )}
      </section>
      {chosen && data && <DayDetail day={chosen} today={data.today} />}
    </>
  );
}
