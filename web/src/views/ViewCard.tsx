import { useId, useRef } from "react";

import { LoadError } from "../components/LoadError";
import { Button, Section } from "../components/ui";
import { useInView, useViewFigures } from "./hooks";
import {
  BudgetsCard,
  OutlookCard,
  PortfolioCard,
  RecordsCard,
  SpendingCard,
  TodayCard,
  TripBudgetCard,
  TripsCard,
  WeightCard,
  WorkoutCard,
} from "./kinds";
import { KIND_LABEL, viewPath } from "./paths";
import type * as T from "./types";
import type { CardView } from "./types";

import "./views.css";

/** The card for a kind, from the figures the server sent for it. Null for a kind this app has no card for. */
function Body({ view, summary, open }: { view: CardView; summary: unknown; open: () => void }) {
  const p = { focus: view.focus, open };
  switch (view.kind) {
    case "finance.month_outlook":
      return <OutlookCard {...p} figures={summary as T.OutlookFigures} />;
    case "finance.budgets":
      return <BudgetsCard {...p} figures={summary as T.BudgetsFigures} />;
    case "finance.spending":
      return <SpendingCard {...p} figures={summary as T.SpendingFigures} />;
    case "travel.trip_budget":
      return <TripBudgetCard {...p} figures={summary as T.TripFigures} />;
    case "travel.trips":
      return <TripsCard open={open} />;
    case "invest.portfolio":
      return <PortfolioCard {...p} figures={summary as T.PortfolioFigures} />;
    case "health.today":
      return <TodayCard {...p} figures={summary as T.TodayFigures} />;
    case "health.weight_trend":
      return <WeightCard {...p} figures={summary as T.WeightFigures} />;
    case "health.workout":
      return <WorkoutCard {...p} figures={summary as T.WorkoutFigures} />;
    case "health.records":
      return <RecordsCard {...p} figures={summary as T.RecordsFigures} />;
    default:
      return null;
  }
}

/** A view in the chat: a compact, read-only card. Its caption comes from the frame (or, for a line from the
 * history, from the figures when they arrive); its figures are fetched fresh, the frame's summary standing in
 * while they load. `onOpen` is given the page's path. A history card (`lazy`) fetches once it is scrolled to. */
export function ViewCard({ view, lazy = false, onOpen }: { view: CardView; lazy?: boolean; onOpen: (path: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, !lazy);
  const figures = useViewFigures(view, seen);
  const id = useId();
  const path = viewPath(view.kind, view.params);
  const caption = figures.data?.caption || view.caption || KIND_LABEL[view.kind] || "Details";
  const open = () => {
    if (path) onOpen(path);
  };
  return (
    <div ref={ref} className="view-card" data-focus={view.focus ? "true" : "false"} data-kind={view.kind}>
      <Section
        id={id}
        title={caption}
        action={
          path ? (
            <Button variant="text" aria-label={`Open ${caption}`} onClick={open}>
              Open
            </Button>
          ) : undefined
        }
      >
        {figures.isError ? (
          <LoadError message="Couldn't load this view." query={figures} />
        ) : !figures.data ? (
          <p className="state" aria-busy={seen}>
            Loading…
          </p>
        ) : (
          <Body view={view} summary={figures.data.summary} open={open} />
        )}
      </Section>
    </div>
  );
}

/** The views under one of Prime's lines, in order. */
export function ViewCards({ views, lazy, onOpen }: { views: CardView[]; lazy?: boolean; onOpen: (path: string) => void }) {
  if (views.length === 0) return null;
  return (
    <div className="msg-views">
      {views.map((v) => (
        <ViewCard key={v.view_id ?? `${v.kind}:${JSON.stringify(v.params)}`} view={v} lazy={lazy} onOpen={onOpen} />
      ))}
    </div>
  );
}
