import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { PanelStageProvider, useOptionalPanelStage, usePanelStage, usePanelStageContext } from "./usePanelStage";
import type { PanelEvent } from "./types";

const event = (month: string): PanelEvent => ({
  panel_id: "finance.budgets",
  kind: "finance.budgets",
  version: 1,
  params: { month },
  topic: "Budgets",
  as_of: "2026-11-15T10:00:00Z",
  message_id: "m1",
});

describe("usePanelStage", () => {
  it("applies actions to the state, and the actions stay the same function", () => {
    const { result } = renderHook(() => usePanelStage());
    const { upsert } = result.current;
    act(() => result.current.upsert(event("2026-11")));
    act(() => result.current.upsert(event("2026-10")));
    expect(result.current.upsert).toBe(upsert);
    expect(result.current.state.panels).toHaveLength(1);
    expect(result.current.state.panels[0].event.params).toEqual({ month: "2026-10" });
    act(() => result.current.dismiss("finance.budgets"));
    expect(result.current.state.history).toHaveLength(1);
    act(() => result.current.restore("finance.budgets"));
    expect(result.current.state.panels).toHaveLength(1);
    act(() => result.current.reset());
    expect(result.current.state).toEqual({ panels: [], history: [] });
  });
});

describe("PanelStageProvider", () => {
  const wrapper = ({ children }: { children: ReactNode }) => <PanelStageProvider>{children}</PanelStageProvider>;

  it("shares one stage with everything inside it", () => {
    const { result } = renderHook(() => ({ chat: usePanelStageContext(), stage: usePanelStageContext() }), { wrapper });
    act(() => result.current.chat.upsert(event("2026-11")));
    expect(result.current.stage.state.panels).toHaveLength(1);
  });

  it("throws outside a provider for the strict hook; the optional one gives null", () => {
    expect(() => renderHook(() => usePanelStageContext())).toThrow();
    const { result } = renderHook(() => useOptionalPanelStage());
    expect(result.current).toBeNull();
  });
});
