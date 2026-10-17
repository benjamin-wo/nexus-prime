import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Link } from "react-router-dom";

import {
  api,
  type Budget,
  type Iou,
  type Me,
  type Money,
  type Page,
  type Summary,
  type Wallet,
} from "../api";
import { Block } from "../components/Block";
import { CategoryBars } from "../components/CategoryBars";
import { Icon } from "../components/Icon";
import { StatTile } from "../components/StatTile";
import {
  formatChange,
  formatDate,
  formatMoney,
  formatShortDate,
  moveLabel,
} from "../format";
import { AccentTitle } from "../motion";

type Total = Summary["totals"][number];

function list(amounts: Money[]): string {
  return amounts.map(formatMoney).join(", ");
}

/** What went into a converted total, in words: foreign amounts included, and any left out. */
export function conversionNote(total: Total | undefined): string | undefined {
  if (!total) return undefined;
  const parts = [];
  if (total.converted.length)
    parts.push(`Includes ${list(total.converted)}, converted`);
  if (total.unconverted.length)
    parts.push(`${list(total.unconverted)} left out: no rate`);
  return parts.length ? parts.join(". ") : undefined;
}

/** Days left in this month after today, in the user's timezone. */
function daysLeft(timezone: string): number {
  const [y, m, d] = new Intl.DateTimeFormat("en-CA", { timeZone: timezone })
    .format(new Date())
    .split("-")
    .map(Number);
  return new Date(Date.UTC(y, m, 0)).getUTCDate() - d;
}

/** One line from Nexus about the budget closest to running out, with questions
 * worth one tap; without budgets, an offer to set one. */
function Nudge({
  budgets,
  timezone,
  onAsk,
}: {
  budgets?: Budget[];
  timezone: string;
  onAsk: (text: string) => void;
}) {
  if (!budgets) return null;
  const tightest = [...budgets].sort((a, b) => b.percent - a.percent)[0];
  const left = daysLeft(timezone);
  const what = tightest
    ? tightest.category_id === null
      ? "your overall budget"
      : tightest.name
    : "";
  return (
    <section className="nudge" aria-label="From Nexus">
      <span className="assistant-mark" aria-hidden="true">
        <Icon name="sparkle" size={18} />
      </span>
      {tightest ? (
        <p>
          You've used <span className="hl">{tightest.percent}%</span> of {what}{" "}
          with {left} {left === 1 ? "day" : "days"} to go. Want me to look at
          where it went?
        </p>
      ) : (
        <p>Set a monthly budget and I'll tell you when it's getting tight.</p>
      )}
      <div className="chips">
        {tightest ? (
          <>
            <button
              type="button"
              className="ask-chip"
              onClick={() =>
                onAsk(
                  tightest.category_id === null
                    ? "Where did my money go this month?"
                    : `Where did my ${tightest.name} money go this month?`,
                )
              }
            >
              Show me
            </button>
            <Link className="ask-chip" to="/accounting/plan">
              Change budgets
            </Link>
          </>
        ) : (
          <Link className="ask-chip" to="/accounting/plan">
            Set a budget
          </Link>
        )}
      </div>
    </section>
  );
}

function Latest({ page, timezone }: { page?: Page; timezone: string }) {
  return (
    <Block
      id="latest"
      title="Latest"
      action={
        <Link className="btn btn-small" to="/accounting/ledger">
          See all
        </Link>
      }
    >
      {!page ? (
        <p className="state">Loading…</p>
      ) : page.items.length === 0 ? (
        <p className="state">Nothing logged yet.</p>
      ) : (
        <ul className="rows">
          {page.items.map((t) => {
            const move = t.direction === "move";
            const name =
              t.counterparty ??
              (move ? moveLabel(t) : t.direction === "in" ? "Money in" : "Money out");
            // A move is neither spent nor received: shown without a sign or a colour.
            const signed = {
              ...t.amount,
              amount:
                t.direction === "out" ? `-${t.amount.amount}` : t.amount.amount,
            };
            return (
              <li key={t.id} className="row">
                <span
                  className={`row-icon${t.direction === "in" ? " in" : ""}`}
                  aria-hidden="true"
                >
                  {name.slice(0, 1).toUpperCase()}
                </span>
                <span className="row-main">
                  <span className="wrap">{name}</span>
                  <span className="caption">
                    {formatShortDate(t.occurred_at, timezone)}
                    {t.status === "pending" ? " · pending" : ""}
                  </span>
                </span>
                <span className={`num${t.direction === "in" ? " up" : ""}`}>
                  {move ? formatMoney(t.amount) : formatChange(signed)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Block>
  );
}

export function Dashboard({
  me,
  onLog,
  onAsk,
}: {
  me: Me;
  onLog: () => void;
  onAsk: (text: string) => void;
}) {
  const summary = useQuery({
    queryKey: ["summary"],
    queryFn: () => api<Summary>("/summary"),
  });
  const budgets = useQuery({
    queryKey: ["budgets"],
    queryFn: () => api<Budget[]>("/budgets"),
  }).data;
  const latest = useQuery({
    queryKey: ["transactions", "latest"],
    queryFn: () => api<Page>("/transactions?limit=5"),
  }).data;
  const ious = useQuery({
    queryKey: ["ious"],
    queryFn: () => api<Iou[]>("/ious"),
  });
  const wallets = useQuery({
    queryKey: ["wallets"],
    queryFn: () => api<Wallet[]>("/wallets"),
  }).data;
  const client = useQueryClient();
  const [repayError, setRepayError] = useState<string | null>(null);

  async function paidBack(iou: Iou) {
    setRepayError(null);
    try {
      await api(`/ious/${iou.split_id}/repaid`, { method: "POST", body: {} });
      void client.invalidateQueries({ queryKey: ["ious"] });
      void client.invalidateQueries({ queryKey: ["summary"] });
      void client.invalidateQueries({ queryKey: ["transactions"] });
    } catch (e) {
      setRepayError(
        e instanceof Error ? e.message : "Couldn't mark that paid back",
      );
    }
  }

  const home = summary.data?.currency ?? me.user.home_currency;
  const spent = summary.data?.totals.find((t) => t.direction === "out");
  const received = summary.data?.totals.find((t) => t.direction === "in");
  const net =
    spent && received
      ? Number(received.total.amount) - Number(spent.total.amount)
      : null;
  const partial = Boolean(
    spent?.unconverted.length || received?.unconverted.length,
  );
  // Money put away only means something once there is a wallet to put it in.
  const putAway =
    summary.data?.put_away && wallets?.some((w) => w.kind !== "spending")
      ? summary.data.put_away
      : null;
  const savingRate = summary.data?.saving_rate;
  const foreign = Boolean(
    spent?.converted.length || received?.converted.length,
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>
            <AccentTitle text="This month" />
          </h1>
          {summary.data && (
            <p className="muted">
              {formatDate(summary.data.start)} to {formatDate(summary.data.end)}
            </p>
          )}
        </div>
        <div className="quick" aria-label="Quick actions">
          <button type="button" className="btn btn-primary" onClick={onLog}>
            Log expense
          </button>
        </div>
      </div>

      {summary.isError && (
        <p className="error-text">Couldn't load this month's totals.</p>
      )}
      <Nudge budgets={budgets} timezone={me.user.timezone} onAsk={onAsk} />
      <div className="tiles">
        <StatTile
          label="Spent"
          value={spent ? formatMoney(spent.total) : "…"}
          extra={conversionNote(spent)}
        />
        <StatTile
          label="Received"
          value={received ? formatMoney(received.total) : "…"}
          extra={conversionNote(received)}
        />
        <StatTile
          label="Net"
          value={
            net === null
              ? "…"
              : formatMoney({ amount: String(net), currency: home })
          }
          extra={partial ? "Leaves out amounts with no rate" : undefined}
        />
        {putAway && (
          <StatTile
            label="Put away"
            value={formatMoney(putAway)}
            extra={
              savingRate == null
                ? undefined
                : `${Math.round(savingRate * 100)}% of income`
            }
          />
        )}
      </div>

      <div className="pair">
        <Block id="by-category" title="Where it went" action={<span className="caption">In {home}</span>}>
          {summary.isLoading ? (
            <p className="state">Loading…</p>
          ) : (
            <CategoryBars
              rows={summary.data?.by_category ?? []}
              period={summary.data && { start: summary.data.start, end: summary.data.end }}
              timezone={me.user.timezone}
            />
          )}
          {foreign && (
            <p className="muted">
              Foreign amounts are converted to {home} at the European Central
              Bank reference rate for their day (or the last business day before
              it).
            </p>
          )}
        </Block>
        <div className="stack">
          <Latest page={latest} timezone={me.user.timezone} />
          <Block id="owed" title="Who owes you">
            {ious.isLoading && <p className="state">Loading…</p>}
            {ious.data?.length === 0 && (
              <p className="state">Nobody owes you anything.</p>
            )}
            {ious.data?.map((iou) => (
              <div key={iou.split_id} className="iou">
                <span className="wrap">
                  {iou.participant_name}
                  <br />
                  <span className="caption">
                    since{" "}
                    {formatDate(iou.expense_occurred_at, me.user.timezone)}
                  </span>
                </span>
                <span className="iou-end">
                  <span className="num">
                    {formatMoney(iou.outstanding)}
                    <span className="sr-only"> still owed</span>
                  </span>
                  <button
                    type="button"
                    className="btn btn-small"
                    aria-label={`${iou.participant_name} paid back ${formatMoney(iou.outstanding)}`}
                    onClick={() => void paidBack(iou)}
                  >
                    Paid back
                  </button>
                </span>
              </div>
            ))}
            {repayError && <p className="error-text">{repayError}</p>}
          </Block>
        </div>
      </div>
    </>
  );
}
