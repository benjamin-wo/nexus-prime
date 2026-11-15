// The panel stage's state, as a pure reducer. Prime opens panels (upsert); the person pins, touches,
// dismisses and restores them. Rules (docs/plans/domain-panels.md, step 2.2):
//  - the same slot (panel_id) updates an open, unpinned, untouched panel in place, keeping its position;
//  - a pinned or touched panel is never changed by Prime: the new one opens beside it as `<panel_id>#2`, `#3`...;
//  - a slot the person dismissed is not reopened by an upsert (the newest data is kept in history);
//    only `restore` reopens it;
//  - budget: at most one expanded and at most four visible panels. The newest upsert is the expanded one
//    unless the expanded one is pinned; past four, the oldest unpinned panel goes to history. A panel
//    pushed out by the budget (not dismissed) is reopened by a later upsert of its slot.

import type { PanelEvent } from "./types";

export type PanelStatus = "open" | "pinned" | "dismissed";

export type PanelEntry = {
  /** Unique on the stage: the event's panel_id, or `<panel_id>#n` for a panel opened beside a pinned or touched one. */
  id: string;
  event: PanelEvent;
  status: PanelStatus;
  expanded: boolean;
  /** ms; when it opened (or was last restored). Decides which panel the budget pushes out first. */
  openedAt: number;
  /** ms; when Prime last changed its figures. */
  updatedAt: number;
  /** The person has worked in it: Prime no longer updates it in place. */
  touched: boolean;
  /** Set once it is in history: by the person ("user") or by the budget ("budget"). */
  closedBy?: "user" | "budget";
};

export type StageState = {
  /** Visible panels (open or pinned), in the order they opened. */
  panels: PanelEntry[];
  /** Closed panels, newest first. */
  history: PanelEntry[];
};

export const MAX_VISIBLE = 4;
export const MAX_HISTORY = 20;

export const initialStageState: StageState = { panels: [], history: [] };

export type StageAction =
  | { type: "upsert"; event: PanelEvent; now: number }
  | { type: "pin"; id: string }
  | { type: "unpin"; id: string }
  | { type: "dismiss"; id: string }
  | { type: "restore"; id: string; now: number }
  | { type: "expand"; id: string }
  | { type: "collapse"; id: string }
  | { type: "touch"; id: string }
  | { type: "reset" };

const slotOf = (entry: PanelEntry) => entry.event.panel_id;
const isUpdatable = (entry: PanelEntry) => entry.status === "open" && !entry.touched;

function withHistory(history: PanelEntry[], entry: PanelEntry): PanelEntry[] {
  return [entry, ...history.filter((h) => h.id !== entry.id)].slice(0, MAX_HISTORY);
}

function close(entry: PanelEntry, by: "user" | "budget"): PanelEntry {
  return { ...entry, status: "dismissed", expanded: false, closedBy: by };
}

/** Make `id` the expanded panel, unless a different, pinned panel is expanded (then `id` stays compact). */
function promote(panels: PanelEntry[], id: string): PanelEntry[] {
  const pinnedExpanded = panels.some((p) => p.expanded && p.status === "pinned" && p.id !== id);
  return panels.map((p) => (p.id === id ? { ...p, expanded: !pinnedExpanded } : pinnedExpanded ? p : { ...p, expanded: false }));
}

/** Push the oldest unpinned panels to history until at most MAX_VISIBLE are left. */
function enforceBudget(state: StageState): StageState {
  let { panels, history } = state;
  while (panels.length > MAX_VISIBLE) {
    let oldest = -1;
    panels.forEach((p, i) => {
      if (p.status !== "pinned" && (oldest === -1 || p.openedAt < panels[oldest].openedAt)) oldest = i;
    });
    if (oldest === -1) break; // all pinned: nothing may be pushed out
    history = withHistory(history, close(panels[oldest], "budget"));
    panels = panels.filter((_, i) => i !== oldest);
  }
  return { panels, history };
}

function nextBesideId(slot: string, state: StageState): string {
  const taken = new Set([...state.panels, ...state.history].map((p) => p.id));
  for (let n = 2; ; n++) if (!taken.has(`${slot}#${n}`)) return `${slot}#${n}`;
}

function upsert(state: StageState, event: PanelEvent, now: number): StageState {
  const slot = event.panel_id;
  const sameSlot = state.panels.filter((p) => slotOf(p) === slot);

  // 1. An open, unpinned, untouched panel of this slot: update in place.
  const target = sameSlot.find(isUpdatable);
  if (target) {
    const panels = state.panels.map((p) => (p.id === target.id ? { ...p, event, updatedAt: now } : p));
    return { ...state, panels: promote(panels, target.id) };
  }

  // 2. Visible, but all pinned or touched: open the new one beside them.
  if (sameSlot.length > 0) {
    const entry: PanelEntry = { id: nextBesideId(slot, state), event, status: "open", expanded: false, openedAt: now, updatedAt: now, touched: false };
    return enforceBudget({ ...state, panels: promote([...state.panels, entry], entry.id) });
  }

  // 3. Not visible. A slot the person dismissed stays closed; its newest data is kept in history.
  const dismissed = state.history.find((h) => slotOf(h) === slot && h.closedBy === "user");
  if (dismissed) {
    return { ...state, history: state.history.map((h) => (h.id === dismissed.id ? { ...h, event, updatedAt: now } : h)) };
  }

  // 4. New, or pushed out earlier by the budget: (re)open it.
  const pushedOut = state.history.find((h) => slotOf(h) === slot && h.closedBy === "budget");
  const history = pushedOut ? state.history.filter((h) => h.id !== pushedOut.id) : state.history;
  const entry: PanelEntry = {
    id: pushedOut?.id ?? slot,
    event,
    status: "open",
    expanded: false,
    openedAt: now,
    updatedAt: now,
    touched: false,
  };
  return enforceBudget({ panels: promote([...state.panels, entry], entry.id), history });
}

const update = (state: StageState, id: string, fn: (p: PanelEntry) => PanelEntry): StageState =>
  state.panels.some((p) => p.id === id) ? { ...state, panels: state.panels.map((p) => (p.id === id ? fn(p) : p)) } : state;

export function stageReducer(state: StageState, action: StageAction): StageState {
  switch (action.type) {
    case "upsert":
      return upsert(state, action.event, action.now);
    case "pin":
      return update(state, action.id, (p) => ({ ...p, status: "pinned" }));
    case "unpin":
      return update(state, action.id, (p) => (p.status === "pinned" ? { ...p, status: "open" } : p));
    case "touch":
      return update(state, action.id, (p) => ({ ...p, touched: true }));
    case "collapse":
      return update(state, action.id, (p) => ({ ...p, expanded: false }));
    case "expand":
      // The person's own choice: it wins over everything, a pinned expanded panel included.
      return state.panels.some((p) => p.id === action.id)
        ? { ...state, panels: state.panels.map((p) => ({ ...p, expanded: p.id === action.id })) }
        : state;
    case "dismiss": {
      const entry = state.panels.find((p) => p.id === action.id);
      if (!entry) return state;
      return { panels: state.panels.filter((p) => p.id !== action.id), history: withHistory(state.history, close(entry, "user")) };
    }
    case "restore": {
      const entry = state.history.find((h) => h.id === action.id);
      if (!entry) return state;
      const { closedBy: _closedBy, ...rest } = entry;
      const reopened: PanelEntry = { ...rest, status: "open", expanded: false, openedAt: action.now };
      const history = state.history.filter((h) => h.id !== action.id);
      const next = enforceBudget({ panels: promote([...state.panels, reopened], reopened.id), history });
      // Four pinned panels already fill the stage: the budget would push the restored one straight back out.
      return next.panels.some((p) => p.id === reopened.id) ? next : state;
    }
    case "reset":
      return initialStageState;
  }
}
