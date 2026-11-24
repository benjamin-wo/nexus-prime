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

  it("chooses the weight unit", async () => {
    let unit = "kg";
    const calls = mockApi({
      "GET /health/consent": () => ({ consented_at: null }),
      "GET /health/preferences": () => ({ unit }),
      "PUT /health/preferences": (b) => {
        unit = (b as { unit: string }).unit;
        return { unit };
      },
    });
    renderWithProviders(<HealthSettings />);
    const lb = await screen.findByRole("button", { name: "lb" });
    expect(screen.getByRole("button", { name: "kg" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(lb);
    expect(await screen.findByRole("button", { name: "lb" })).toHaveAttribute("aria-pressed", "true");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
  });
});
