import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { MemorySection } from "./Memory";

const sister = { id: "m1", kind: "fact", text: "Ann is my sister", happened_on: null, updated_at: "2026-10-01T00:00:00Z" };

afterEach(() => vi.restoreAllMocks());

describe("what Nexus remembers", () => {
  it("asks before forgetting one memory, and forgets it when told to", async () => {
    let list = [sister];
    const calls = mockApi({
      "GET /memories": () => list,
      "DELETE /memories/m1": () => {
        list = [];
        return undefined;
      },
    });
    renderWithProviders(<MemorySection />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Forget: Ann is my sister" }));
    const ask = screen.getByRole("group", { name: "Forget: Ann is my sister" });
    await user.click(within(ask).getByRole("button", { name: "Keep" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Forget: Ann is my sister" }));
    await user.click(within(screen.getByRole("group", { name: "Forget: Ann is my sister" })).getByRole("button", { name: "Forget" }));
    await waitFor(() => expect(screen.queryByText("Ann is my sister")).toBeNull());
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });

  it("says so, and keeps the memory, when forgetting fails", async () => {
    mockApi({
      "GET /memories": () => [sister],
      "DELETE /memories/m1": () => new Response(JSON.stringify({ detail: "Nexus is busy" }), { status: 500 }),
    });
    renderWithProviders(<MemorySection />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Forget: Ann is my sister" }));
    await user.click(within(screen.getByRole("group", { name: "Forget: Ann is my sister" })).getByRole("button", { name: "Forget" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Ann is my sister")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Forget: Ann is my sister" })).toBeInTheDocument();
  });

  it("says so when forgetting everything fails", async () => {
    mockApi({
      "GET /memories": () => [sister],
      "DELETE /memories": () => new Response(JSON.stringify({ detail: "Nexus is busy" }), { status: 500 }),
    });
    renderWithProviders(<MemorySection />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Forget everything" }));
    await user.click(screen.getByRole("button", { name: "Forget all" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Ann is my sister")).toBeInTheDocument();
  });
});
