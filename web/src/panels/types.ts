// The panel events the server sends beside a chat turn (SSE event `panel.upsert`). The wire contract
// is fixed by docs/adr/0001-prime-opens-domain-panels.md; this file reads it defensively: anything
// that is not exactly a known kind at a known version is dropped, never half-shown.

export const PANEL_VERSION = 1;

export const KNOWN_KINDS = ["finance.month_outlook", "finance.budgets", "finance.transactions", "travel.trip_budget"] as const;

export type PanelKind = (typeof KNOWN_KINDS)[number];

/** What each kind's `params` hold. `month` is "YYYY-MM"; transactions is a filter of string values. */
export type PanelParams = {
  "finance.month_outlook": { month: string };
  "finance.budgets": { month: string };
  "finance.transactions": Record<string, string>;
  "travel.trip_budget": { trip_id: string | number };
};

type PanelEventBase = {
  /** Stable per slot: "finance.month_outlook", "finance.budgets", "finance.transactions" or "travel.trip_budget:<id>". */
  panel_id: string;
  version: typeof PANEL_VERSION;
  /** What the person asked about, in plain words ("Opened because you asked about ..."). */
  topic: string;
  /** ISO time the figures are as of. */
  as_of: string;
  /** The chat message that caused the panel. */
  message_id: string;
};

export type PanelEvent = { [K in PanelKind]: PanelEventBase & { kind: K; params: PanelParams[K] } }[PanelKind];

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

function parseParams(kind: PanelKind, params: Record<string, unknown>): PanelParams[PanelKind] | null {
  switch (kind) {
    case "finance.month_outlook":
    case "finance.budgets":
      return typeof params.month === "string" && MONTH.test(params.month) ? { month: params.month } : null;
    case "finance.transactions": {
      const filter: Record<string, string> = {};
      for (const [key, value] of Object.entries(params)) {
        if (typeof value !== "string") return null;
        filter[key] = value;
      }
      return filter;
    }
    case "travel.trip_budget": {
      const id = params.trip_id;
      return (typeof id === "string" && id !== "") || (typeof id === "number" && Number.isFinite(id)) ? { trip_id: id } : null;
    }
  }
}

/** The event if `raw` is a well-formed `panel.upsert` payload of a known kind and version; else null. */
export function parsePanelEvent(raw: unknown): PanelEvent | null {
  if (!isRecord(raw)) return null;
  const { panel_id, kind, version, params, topic, as_of, message_id } = raw;
  if (version !== PANEL_VERSION) return null;
  if (typeof kind !== "string" || !(KNOWN_KINDS as readonly string[]).includes(kind)) return null;
  if (typeof panel_id !== "string" || panel_id === "") return null;
  if (typeof topic !== "string" || typeof message_id !== "string") return null;
  if (typeof as_of !== "string" || Number.isNaN(Date.parse(as_of))) return null;
  if (!isRecord(params)) return null;
  const parsed = parseParams(kind as PanelKind, params);
  if (!parsed) return null;
  return { panel_id, kind, version: PANEL_VERSION, params: parsed, topic, as_of, message_id } as PanelEvent;
}
