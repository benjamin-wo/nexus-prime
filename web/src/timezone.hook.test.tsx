import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "./testing";
import { useReportTimeZone, type ZoneState } from "./timezone";

function Probe({ user }: { user: ZoneState }) {
  useReportTimeZone(user);
  return null;
}

function mount(user: ZoneState, client = new QueryClient()) {
  const ui = (u: ZoneState) => (
    <QueryClientProvider client={client}>
      <Probe user={u} />
    </QueryClientProvider>
  );
  const view = render(ui(user));
  return { client, rerender: (u: ZoneState) => view.rerender(ui(u)) };
}

const home: ZoneState = { timezone: "Asia/Singapore", home_timezone: "Asia/Singapore", timezone_source: "home", timezone_set_at: null };

afterEach(() => vi.restoreAllMocks());

function phoneIn(zone: string) {
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({ timeZone: zone } as Intl.ResolvedDateTimeFormatOptions);
}

describe("useReportTimeZone", () => {
  it("sends the browser's zone as the phone's, once, and refreshes me and today", async () => {
    phoneIn("Europe/Madrid");
    const calls = mockApi({ "POST /me/timezone": () => ({ user: { ...home, timezone: "Europe/Madrid", timezone_source: "phone" }, csrf_token: "c", changed: true }) });
    const { client, rerender } = mount(home);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["home"] });
    rerender({ ...home, timezone: "Europe/Madrid", timezone_source: "phone" });
    expect(calls.filter((c) => c.method === "POST")).toEqual([{ method: "POST", path: "/me/timezone", body: { timezone: "Europe/Madrid", source: "phone" } }]);
  });

  it("sends nothing when the phone is already the source and the zones match", async () => {
    phoneIn("Asia/Singapore");
    const calls = mockApi({});
    mount({ ...home, timezone_source: "phone", timezone_set_at: new Date().toISOString() });
    await Promise.resolve();
    expect(calls).toEqual([]);
  });

  it("does not override a zone the person chose in the last day", async () => {
    phoneIn("Europe/Madrid");
    const calls = mockApi({});
    mount({ ...home, timezone: "Asia/Tokyo", timezone_source: "chat", timezone_set_at: new Date(Date.now() - 3600_000).toISOString() });
    await Promise.resolve();
    expect(calls).toEqual([]);
  });

  it("drops a failure without a word", async () => {
    phoneIn("Europe/Madrid");
    const calls = mockApi({ "POST /me/timezone": () => new Response(JSON.stringify({ detail: "no" }), { status: 500 }) });
    const { client } = mount(home);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await waitFor(() => expect(calls).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 10));
    expect(invalidate).not.toHaveBeenCalled();
  });
});
