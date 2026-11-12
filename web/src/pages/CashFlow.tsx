import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type CashDay, type CashFlow, type Money } from "../api";
import { formatMoney } from "../format";
import { monthLabel, shiftMonth } from "../months";
import { AccentTitle } from "../motion";

const EXPECTED_KINDS: Record<string, string> = {
  bill: "Scheduled payment",
  subscription: "Subscription",
  trip: "Trip",
  salary: "Payday",
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function isZero(money: Money): boolean {
  return Number(money.amount) === 0;
}

function absolute(money: Money): Money {
  return { ...money, amount: String(Math.abs(Number(money.amount))) };
}

/** The largest day's figure this month, logged or expected: what the tallest bar stands for. */
function monthScale(data: CashFlow): number {
  let max = 0;
  for (const d of data.days) {
    if (d.day <= data.today) max = Math.max(max, Math.abs(Number(d.net.amount)));
    if (d.expected.length) max = Math.max(max, Math.abs(Number(d.expected_net.amount)));
  }
  return max;
}

/** A bar's height step, 1 (shortest) to 4. Log scale against the month's largest day, so one big
 * payday or rent doesn't flatten every small day to the same sliver: with a 4,700 top day the
 * steps break near 30, 170 and 1,000; with a 200 top day, near 6, 20 and 70. */
export function barStep(amount: number, max: number): 1 | 2 | 3 | 4 {
  if (max <= 0) return 1;
  const t = Math.log1p(Math.abs(amount)) / Math.log1p(max);
  return t < 0.4 ? 1 : t < 0.6 ? 2 : t < 0.8 ? 3 : 4;
}

function DayCell({
  day,
  today,
  scale,
  selected,
  onSelect,
}: {
  day: CashDay;
  today: string;
  scale: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const past = day.day <= today;
  const date = Number(day.day.slice(8, 10));
  const name = new Intl.DateTimeFormat(undefined, { month: "long", day: "numeric", timeZone: "UTC" }).format(
    new Date(`${day.day}T00:00:00Z`),
  );
  const logged = past && !isZero(day.net) ? day.net : null;
  const expected = day.expected.length > 0 && !isZero(day.expected_net) ? day.expected_net : null;
  const unpriced = day.expected.length > 0 && !expected;
  const parts: string[] = [];
  if (logged) {
    parts.push(`${Number(logged.amount) > 0 ? "money in" : "spent"} ${formatMoney(absolute(logged))}`);
  }
  if (expected) {
    parts.push(`expected ${Number(expected.amount) > 0 ? "in" : "out"} ${formatMoney(absolute(expected))}`);
  }
  if (unpriced) parts.push(`${day.expected.length} expected, no amount set`);
  const label = [name, ...parts].join(", ");
  return (
    <button
      type="button"
      className={`cal-day${day.day === today ? " is-today" : ""}`}
      aria-pressed={selected}
      aria-label={label}
      onClick={onSelect}
    >
      <span className="cal-date">{date}</span>
      <span className="cal-bars" aria-hidden="true">
        {logged && (
          <span
            className={`cal-bar ${Number(logged.amount) > 0 ? "in" : "out"} step-${barStep(Number(logged.amount), scale)}`}
          />
        )}
        {expected && (
          <span
            className={`cal-bar expected ${Number(expected.amount) > 0 ? "in" : "out"} step-${barStep(Number(expected.amount), scale)}`}
          />
        )}
        {unpriced && <span className="cal-dot" />}
      </span>
    </button>
  );
}

function Legend() {
  return (
    <ul className="cal-legend caption" aria-label="Key">
      <li>
        <span className="cal-key cal-bar out" aria-hidden="true" /> Spent
      </li>
      <li>
        <span className="cal-key cal-bar expected out" aria-hidden="true" /> Expected
      </li>
      <li>
        <span className="cal-key cal-bar in" aria-hidden="true" /> Money in
      </li>
      <li>Taller bar = more</li>
    </ul>
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
                <span className={`num cal-item-amount ${e.direction}`}>
                  {e.amount ? `${e.direction === "in" ? "+" : "-"}${formatMoney(e.amount)}` : "Amount not set"}
                </span>
              </div>
              <p className="caption">
                {EXPECTED_KINDS[e.kind] ?? "Payday"}
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
  const scale = data ? monthScale(data) : 0;
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
          <h1>
            <AccentTitle text="Cash flow" />
          </h1>
          <p className="muted">
            Money in and out by day, plus what's coming.
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
                  scale={scale}
                  selected={chosen?.day === d.day}
                  onSelect={() => setSelected(d.day)}
                />
              ))}
            </div>
            <Legend />
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
