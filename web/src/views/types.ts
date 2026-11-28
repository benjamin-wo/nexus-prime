import type { Money } from "../api";

/** A view Prime shows as a card: what the stream frame or a stored reply line carries. The caption and the
 * summary are only on a live frame; a stored ref has just the kind, the params and the focus. */
export type CardView = {
  kind: string;
  params: Record<string, unknown>;
  focus: boolean;
  caption?: string;
  summary?: Record<string, unknown> | null;
  view_id?: string;
};

// The figures `GET /api/views/{kind}` sends for each kind (views_api.py); money is as the web API sends it.
export type OutlookFigures = {
  status: string;
  received: Money | null;
  spent: Money | null;
  overall: Money | null;
  headroom: Money | null;
  shortfall: Money | null;
};
export type BudgetsFigures = {
  count: number;
  over: number;
  budgets: { name: string; spent: Money | null; limit: Money | null; percent: number }[];
};
export type SpendingFigures = { spent: Money | null; count: number; categories: { name: string; total: Money | null }[] };
export type TripFigures = {
  budget: Money | null;
  spent: Money | null;
  left: Money | null;
  percent: number | null;
  to_spend: Money | null;
};
export type PortfolioFigures = {
  holdings: number;
  value: Money | null;
  cost: Money | null;
  gain: Money | null;
  day_change: Money | null;
  as_of: string | null;
};
export type WorkoutFigures = {
  state: "suggested" | "open" | "planned" | "rest";
  focus?: string | null;
  routine?: string | null;
  exercises?: number | null;
  minutes?: number | null;
  started_at?: string | null;
};
export type TodayFigures = {
  day: string;
  meals: number;
  kcal?: string | null;
  protein_g?: string | null;
  kcal_target?: string | null;
  workout?: WorkoutFigures | null;
};
export type WeightFigures = {
  hidden: boolean;
  trend_words: string;
  trend_kg?: string | null;
  kg_a_week?: string | null;
  weigh_ins?: number | null;
};
export type RecordsFigures = {
  records: { exercise: string; heaviest_kg: string | null; e1rm_kg: string | null; sessions: number }[];
};

export type ViewAnswer = { view_id: string; kind: string; params: Record<string, unknown>; caption: string; summary: unknown };
