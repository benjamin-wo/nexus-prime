import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { HealthSettings } from "./HealthSettings";

afterEach(() => vi.restoreAllMocks());

describe("Settings > Health data", () => {
  it("withdraws consent after asking", async () => {
    const calls = mockApi({
      "GET /health/consent": () => ({ consented_at: "2026-11-20T08:00:00Z" }),
      "DELETE /health/consent": () => null,
    });
    renderWithProviders(<HealthSettings />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn off Health" }));
    const box = screen.getByRole("group", { name: "Turn off Health" });
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(within(box).getByRole("button", { name: "Turn off Health" }));
    expect(await screen.findByText(/Health is off/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });

  it("says Health is off when there is no consent", async () => {
    mockApi({ "GET /health/consent": () => ({ consented_at: null }) });
    renderWithProviders(<HealthSettings />);
    expect(await screen.findByRole("link", { name: "Turn it on" })).toHaveAttribute("href", "/health");
  });
});
