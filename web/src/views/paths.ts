// Where each view's page lives in the web app, and how a card's params reach it. The catalogue in
// `agent/views.py` is the source of truth for the kinds; `paths.test.ts` keeps this list to its nine live ones.

type Params = Record<string, unknown>;

const text = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);

function withQuery(path: string, query: Record<string, string | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value !== null) search.set(key, value);
  const q = search.toString();
  return q ? `${path}?${q}` : path;
}

/** The page behind a card: its route and the params that route reads from the address. Null for a kind
 * this app has no page for (the card then has no Open). */
export function viewPath(kind: string, params: Params): string | null {
  switch (kind) {
    case "finance.month_outlook":
      return withQuery("/accounting", { month: text(params.month) });
    case "finance.spending":
      return withQuery("/accounting", { month: text(params.month) });
    case "finance.budgets":
      return withQuery("/accounting/budgets", { month: text(params.month) });
    case "travel.trip_budget": {
      const id = text(params.trip_id);
      return id ? withQuery(`/travel/trips/${encodeURIComponent(id)}`, { tab: "money" }) : "/travel";
    }
    case "travel.trips":
      return "/travel";
    case "invest.portfolio":
      return "/investment";
    case "health.today":
      return withQuery("/health", { day: text(params.day) });
    case "health.weight_trend":
      return withQuery("/health", { weight: "trend" });
    case "health.workout":
      return "/health/gym";
    case "health.records":
      return "/health/gym/history";
    default:
      return null;
  }
}

/** What a card is called before its caption arrives (a stored ref has none). */
export const KIND_LABEL: Record<string, string> = {
  "finance.month_outlook": "Your month",
  "finance.budgets": "Your budgets",
  "finance.spending": "Where your money went",
  "travel.trip_budget": "Your trip's budget",
  "travel.trips": "Your trips",
  "invest.portfolio": "Your portfolio",
  "health.today": "Your day",
  "health.weight_trend": "Your weight trend",
  "health.workout": "Your workout",
  "health.records": "Your records",
};
