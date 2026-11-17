// The stage's state as a React hook, plus a small context so the chat can push panel events and a
// stage can render them. No persistence: a reload starts with an empty stage (prototype).

import { createContext, createElement, useContext, useMemo, useReducer, type ReactNode } from "react";

import { initialStageState, stageReducer, type StageState } from "./stageReducer";
import type { PanelEvent } from "./types";

export type PanelStage = {
  state: StageState;
  /** A panel.upsert from the chat. */
  upsert: (event: PanelEvent) => void;
  pin: (id: string) => void;
  unpin: (id: string) => void;
  dismiss: (id: string) => void;
  /** The person reopens a panel from history. */
  restore: (id: string) => void;
  expand: (id: string) => void;
  collapse: (id: string) => void;
  /** The person worked in a panel: Prime stops updating it in place. */
  touch: (id: string) => void;
  reset: () => void;
};

export function usePanelStage(): PanelStage {
  const [state, dispatch] = useReducer(stageReducer, initialStageState);
  // The actions never change, so a handler that holds one (the chat's stream callback) stays valid.
  const actions = useMemo(
    () => ({
      upsert: (event: PanelEvent) => dispatch({ type: "upsert", event, now: Date.now() }),
      pin: (id: string) => dispatch({ type: "pin", id }),
      unpin: (id: string) => dispatch({ type: "unpin", id }),
      dismiss: (id: string) => dispatch({ type: "dismiss", id }),
      restore: (id: string) => dispatch({ type: "restore", id, now: Date.now() }),
      expand: (id: string) => dispatch({ type: "expand", id }),
      collapse: (id: string) => dispatch({ type: "collapse", id }),
      touch: (id: string) => dispatch({ type: "touch", id }),
      reset: () => dispatch({ type: "reset" }),
    }),
    [],
  );
  return useMemo(() => ({ state, ...actions }), [state, actions]);
}

const PanelStageContext = createContext<PanelStage | null>(null);

export function PanelStageProvider({ children }: { children: ReactNode }) {
  const stage = usePanelStage();
  return createElement(PanelStageContext.Provider, { value: stage }, children);
}

/** The stage of the nearest PanelStageProvider; throws outside one. */
export function usePanelStageContext(): PanelStage {
  const stage = useContext(PanelStageContext);
  if (!stage) throw new Error("usePanelStageContext needs a PanelStageProvider");
  return stage;
}

/** The same, or null outside a provider: for the chat, which works with or without a stage beside it. */
export function useOptionalPanelStage(): PanelStage | null {
  return useContext(PanelStageContext);
}
