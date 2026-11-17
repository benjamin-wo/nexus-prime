import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId } from "react";
import { Link } from "react-router-dom";

import { api, type Category, type Me } from "../api";
import { formatClock } from "../format";
import { BudgetsHeadline, BudgetsPanel } from "../panels/BudgetsPanel";
import { MonthOutlookHeadline, MonthOutlookPanel } from "../panels/MonthOutlookPanel";
import { openLabel, PANEL_TITLES, queryWords, tabLink } from "../panels/links";
import type { PanelEntry } from "../panels/stageReducer";
import { TransactionsHeadline, TransactionsPanel } from "../panels/TransactionsPanel";
import { TripBudgetHeadline, TripBudgetPanel, useTripDetail } from "../panels/TripBudgetPanel";
import type { PanelStage } from "../panels/usePanelStage";
import type { PanelEvent } from "../panels/types";

/** The user's own time zone, once /me is known (the stage only shows for a signed-in user). */
export function useTimezone(): string | undefined {
  return useQueryClient().getQueryData<Me | null>(["me"])?.user.timezone;
}

/** The query in plain words: "Transactions: money out, in Dining, 1 Oct to 31 Oct". Names a category or a
 * trip once their own queries (the ones the tabs make) have answered. */
function QueryLine({ event }: { event: PanelEvent }) {
  const categoryId = event.kind === "finance.transactions" ? event.params.category_id : undefined;
  const categories = useQuery({ queryKey: ["categories", "all"], queryFn: () => api<Category[]>("/categories"), enabled: Boolean(categoryId) });
  const trip = useTripDetail(event.kind === "travel.trip_budget" ? event.params.trip_id : "", event.kind === "travel.trip_budget");
  return (
    <>
      {queryWords(event, {
        categoryName: categories.data?.find((c) => c.id === categoryId)?.name,
        destination: trip.data?.trip.destination,
      })}
    </>
  );
}

function Body({ event, timezone }: { event: PanelEvent; timezone?: string }) {
  switch (event.kind) {
    case "finance.month_outlook":
      return <MonthOutlookPanel event={event} />;
    case "finance.budgets":
      return <BudgetsPanel event={event} timezone={timezone} />;
    case "finance.transactions":
      return <TransactionsPanel event={event} timezone={timezone} />;
    case "travel.trip_budget":
      return <TripBudgetPanel event={event} />;
  }
}

function Headline({ event }: { event: PanelEvent }) {
  switch (event.kind) {
    case "finance.month_outlook":
      return <MonthOutlookHeadline event={event} />;
    case "finance.budgets":
      return <BudgetsHeadline event={event} />;
    case "finance.transactions":
      return <TransactionsHeadline event={event} />;
    case "travel.trip_budget":
      return <TripBudgetHeadline event={event} />;
  }
}

/** One panel on the stage: why it opened, what it asks and when it was read, the buttons to pin, fold
 * and close it, and its read-only body. Working in the body marks it touched, so Prime stops replacing it. */
export function PanelCard({ entry, stage, timezone }: { entry: PanelEntry; stage: PanelStage; timezone?: string }) {
  const { event } = entry;
  const title = PANEL_TITLES[event.kind];
  const titleId = useId();
  const pinned = entry.status === "pinned";
  const touch = () => {
    if (!entry.touched) stage.touch(entry.id);
  };
  return (
    <article
      className={`panel-card${entry.expanded ? " panel-expanded" : " panel-compact"}${pinned ? " panel-pinned" : ""}`}
      aria-labelledby={titleId}
    >
      <header className="panel-head">
        <div className="panel-titles">
          <h3 id={titleId}>{title}</h3>
          <p className="caption panel-why">Opened because you asked about {event.topic}</p>
          {entry.expanded && (
            <p className="caption panel-query">
              <QueryLine event={event} /> · as of {formatClock(event.as_of, timezone)}
            </p>
          )}
        </div>
        <div className="panel-actions" role="group" aria-label={`${title} actions`}>
          <button
            type="button"
            className="btn btn-small btn-ghost"
            aria-pressed={pinned}
            aria-label={pinned ? `Unpin ${title}` : `Pin ${title}`}
            onClick={() => (pinned ? stage.unpin(entry.id) : stage.pin(entry.id))}
          >
            {pinned ? "Unpin" : "Pin"}
          </button>
          <button
            type="button"
            className="btn btn-small btn-ghost"
            aria-expanded={entry.expanded}
            aria-label={entry.expanded ? `Collapse ${title}` : `Expand ${title}`}
            onClick={() => (entry.expanded ? stage.collapse(entry.id) : stage.expand(entry.id))}
          >
            {entry.expanded ? "Collapse" : "Expand"}
          </button>
          <button type="button" className="btn btn-small btn-ghost" aria-label={`Dismiss ${title}`} onClick={() => stage.dismiss(entry.id)}>
            Dismiss
          </button>
        </div>
      </header>
      {entry.expanded ? (
        <div className="panel-body" onClickCapture={touch} onKeyDownCapture={touch}>
          <Body event={event} timezone={timezone} />
          <p className="panel-foot">
            <Link className="panel-link" to={tabLink(event)}>
              {openLabel(event)}
            </Link>
          </p>
        </div>
      ) : (
        <div className="panel-glance">
          <Headline event={event} />
        </div>
      )}
    </article>
  );
}
