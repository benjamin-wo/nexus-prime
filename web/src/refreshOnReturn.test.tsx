import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEBOUNCE_MS, LONG_PAUSE_MS, useRefreshOnReturn } from "./refreshOnReturn";

type Listener = () => void;

/** A stand-in for Telegram's WebApp with just the events and what `withMiniApp` waits for. */
function fakeTelegram() {
  const listeners = new Map<string, Set<Listener>>();
  window.Telegram = {
    WebApp: {
      ready() {},
      expand() {},
      BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
      onEvent(event: string, cb: Listener) {
        listeners.set(event, (listeners.get(event) ?? new Set()).add(cb));
      },
      offEvent(event: string, cb: Listener) {
        listeners.get(event)?.delete(cb);
      },
    },
  };
  return {
    emit: (event: string) => listeners.get(event)?.forEach((cb) => cb()),
    count: (event: string) => listeners.get(event)?.size ?? 0,
  };
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

let now = 1_000_000;
const pass = (ms: number) => {
  now += ms;
};

const fetched = { money: 0, places: 0 };

function Screen() {
  // Money data, default staleTime; reference data with a long staleTime of its own.
  useQuery({ queryKey: ["transactions", "latest"], queryFn: async () => ++fetched.money, staleTime: 15_000 });
  useQuery({ queryKey: ["trip-places", "t1"], queryFn: async () => ++fetched.places, staleTime: 10 * 60_000 });
  return null;
}

function Harness({ client }: { client: QueryClient }) {
  useRefreshOnReturn(client);
  return (
    <QueryClientProvider client={client}>
      <Screen />
    </QueryClientProvider>
  );
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 15_000 } } });
  render(<Harness client={client} />);
  await waitFor(() => expect(fetched.money).toBe(1));
  await waitFor(() => expect(fetched.places).toBe(1));
  return client;
}

describe("refreshing when the app comes back", () => {
  beforeEach(() => {
    now = 1_000_000;
    fetched.money = 0;
    fetched.places = 0;
    vi.spyOn(Date, "now").mockImplementation(() => now);
  });
  afterEach(() => {
    delete window.Telegram;
    setVisibility("visible");
  });

  it("refetches money data when the page becomes visible again, and leaves fresh reference data alone", async () => {
    await mount();
    act(() => setVisibility("hidden"));
    pass(30_000);
    act(() => setVisibility("visible"));
    await waitFor(() => expect(fetched.money).toBe(2));
    expect(fetched.places).toBe(1);
  });

  it("refetches money data even when it was fetched a moment ago", async () => {
    await mount();
    pass(2_000);
    act(() => setVisibility("hidden"));
    act(() => setVisibility("visible"));
    await waitFor(() => expect(fetched.money).toBe(2));
  });

  it("refetches reference data too once it has gone stale", async () => {
    await mount();
    pass(11 * 60_000); // past its 10 minutes
    act(() => setVisibility("hidden"));
    pass(30_000); // a short pause
    act(() => setVisibility("visible"));
    await waitFor(() => expect(fetched.places).toBe(2));
  });

  it("refetches on Telegram's activated event", async () => {
    const telegram = fakeTelegram();
    await mount();
    await waitFor(() => expect(telegram.count("activated")).toBe(1));
    pass(10_000);
    act(() => telegram.emit("activated"));
    await waitFor(() => expect(fetched.money).toBe(2));
  });

  it("does not break when Telegram is older and has no events", async () => {
    window.Telegram = { WebApp: { ready() {}, expand() {}, BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} } } };
    await mount();
    act(() => setVisibility("visible"));
    await waitFor(() => expect(fetched.money).toBe(2));
  });

  it("refreshes once for the several events of one return", async () => {
    const telegram = fakeTelegram();
    await mount();
    await waitFor(() => expect(telegram.count("activated")).toBe(1));
    pass(10_000);
    act(() => {
      telegram.emit("activated");
      setVisibility("visible");
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    await waitFor(() => expect(fetched.money).toBe(2));
    await new Promise((r) => setTimeout(r, 50));
    expect(fetched.money).toBe(2);
    // A later return is a new refresh.
    pass(DEBOUNCE_MS + 1);
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(fetched.money).toBe(3));
  });

  it("refetches everything on screen after a long pause, fresh or not", async () => {
    await mount();
    act(() => setVisibility("hidden"));
    pass(LONG_PAUSE_MS + 1);
    act(() => setVisibility("visible"));
    await waitFor(() => expect(fetched.places).toBe(2));
    expect(fetched.money).toBe(2);
  });

  it("measures the pause from Telegram's deactivated", async () => {
    const telegram = fakeTelegram();
    await mount();
    await waitFor(() => expect(telegram.count("deactivated")).toBe(1));
    act(() => telegram.emit("deactivated"));
    pass(LONG_PAUSE_MS + 1);
    act(() => telegram.emit("activated"));
    await waitFor(() => expect(fetched.places).toBe(2));
  });

  it("ignores a page restored for the first time and a focus while hidden", async () => {
    await mount();
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false }));
    });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    act(() => window.dispatchEvent(new Event("focus")));
    await new Promise((r) => setTimeout(r, 50));
    expect(fetched.money).toBe(1);
  });

  it("stops listening when unmounted", async () => {
    const telegram = fakeTelegram();
    const client = new QueryClient();
    const view = render(<Harness client={client} />);
    await waitFor(() => expect(telegram.count("activated")).toBe(1));
    view.unmount();
    expect(telegram.count("activated")).toBe(0);
    expect(telegram.count("deactivated")).toBe(0);
  });
});
