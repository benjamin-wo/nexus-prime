import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "../api";
import type { Costs } from "../costs";
import { mockApi, renderWithProviders } from "../testing";
import { CostsPage } from "./Costs";
import { Settings } from "./Settings";

const me = (role: Me["user"]["role"]): Me => ({
  user: { telegram_user_id: 1, role, home_currency: "SGD", timezone: "Asia/Singapore", home_timezone: "Asia/Singapore", timezone_source: "home", timezone_set_at: null },
  csrf_token: "c",
});

const costs: Costs = {
  currency: "USD",
  month: { start: "2026-10-01", spent: "12.3456", projected: "18.20", days_elapsed: 28, days_in_month: 31 },
  days: [
    { day: "2026-10-27", cost: "0.4123", calls: 52 },
    { day: "2026-10-28", cost: "0", calls: 0 },
  ],
  by_feature: [{ feature: "voice", cost: "2.40", calls: 210, share: 0.2 }],
  by_user: [{ user_id: "u1", name: "Ben", cost: "9.00", calls: 1000 }],
  by_model: [{ model: "deepseek/deepseek-v4.1-flash", cost: "8.00", calls: 1200, input_tokens: 3_400_000, output_tokens: 220_000 }],
  per_active_user_month: "3.10",
};

describe("Model costs", () => {
  it("shows the figures with friendly feature names and money in cents", async () => {
    const calls = mockApi({ "GET /ops/costs": () => costs });
    renderWithProviders(<CostsPage me={me("owner")} />);
    expect(await screen.findByRole("region", { name: "This month so far" })).toHaveTextContent("US$12.35");
    expect(screen.getByRole("region", { name: "Projected for the month" })).toHaveTextContent("US$18.20");
    expect(screen.getByRole("region", { name: "By feature" })).toHaveTextContent("Voice notes");
    expect(screen.getByRole("region", { name: "By model" })).toHaveTextContent("3.4M in · 220k out");
    expect(screen.getByRole("list", { name: "Cost per day" }).querySelectorAll("button")).toHaveLength(2);
    expect(calls.map((c) => c.path)).toEqual(["/ops/costs"]);
  });

  it("asks again for the range picked", async () => {
    const calls = mockApi({ "GET /ops/costs": () => costs });
    const fetched = () => vi.mocked(globalThis.fetch).mock.calls.map((c) => String(c[0]));
    renderWithProviders(<CostsPage me={me("owner")} />);
    await screen.findByRole("region", { name: "By user" });
    await userEvent.click(screen.getByRole("button", { name: "90 days" }));
    await screen.findByRole("heading", { name: "Last 90 days" });
    expect(fetched()).toEqual(["/api/ops/costs?days=30", "/api/ops/costs?days=90"]);
    expect(calls).toHaveLength(2);
  });

  it("is not available to a member, who never asks", () => {
    const calls = mockApi({ "GET /ops/costs": () => costs });
    renderWithProviders(<CostsPage me={me("member")} />);
    expect(screen.getByText("Model costs aren't available.")).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("says the same when the server answers 404", async () => {
    mockApi({ "GET /ops/costs": () => new Response(JSON.stringify({ detail: "Not found" }), { status: 404 }) });
    renderWithProviders(<CostsPage me={me("owner")} />);
    expect(await screen.findByText("Model costs aren't available.")).toBeInTheDocument();
  });
});

describe("Settings and Model costs", () => {
  it("links the owner to the page", async () => {
    mockApi({});
    renderWithProviders(<Settings me={me("owner")} />);
    const card = screen.getByRole("region", { name: "Model costs" });
    expect(within(card).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/settings/costs");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Settings", level: 1 })).toBeInTheDocument());
  });

  it("shows no link to anyone else", () => {
    mockApi({});
    renderWithProviders(<Settings me={me("member")} />);
    expect(screen.queryByRole("region", { name: "Model costs" })).toBeNull();
    expect(screen.queryByRole("link", { name: /costs/i })).toBeNull();
  });
});
