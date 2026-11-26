import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { consented, consents, profile } from "./bodyFixtures";
import { HealthSettings } from "./HealthSettings";

afterEach(() => vi.restoreAllMocks());

describe("Settings > Health data, consents and profile", () => {
  const base = { "GET /health/consent": () => consented, "GET /health/consents": () => consents, "GET /health/profile": () => null };

  it("lists the scopes as switches and names the AI provider and country", async () => {
    mockApi(base);
    renderWithProviders(<HealthSettings />);
    const ai = await screen.findByRole("switch", { name: "Lets Nexus's AI provider (OpenRouter, United States) read your health logs to answer you" });
    expect(ai).not.toBeChecked();
    expect(screen.getByRole("switch", { name: /improve its models/ })).toBeChecked();
  });

  it("grants and withdraws a scope", async () => {
    const calls = mockApi({
      ...base,
      "PUT /health/consents/ai_processing": () => ({ scope: "ai_processing", active: true }),
      "DELETE /health/consents/model_improvement": () => ({ scope: "model_improvement", active: false }),
    });
    renderWithProviders(<HealthSettings />);
    await userEvent.click(await screen.findByRole("switch", { name: /AI provider/ }));
    await userEvent.click(screen.getByRole("switch", { name: /improve its models/ }));
    await vi.waitFor(() => expect(calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.path}`)).toEqual(["PUT /health/consents/ai_processing", "DELETE /health/consents/model_improvement"]));
  });

  it("shows the wellness statement verbatim at the bottom", async () => {
    mockApi(base);
    renderWithProviders(<HealthSettings />);
    expect(await screen.findByText(consents.wellness_statement)).toBeInTheDocument();
  });

  it("shows what the safety rules did in plain sentences, with the signposts", async () => {
    mockApi({ ...base, "GET /health/profile": () => profile });
    renderWithProviders(<HealthSettings />);
    expect(await screen.findByText("A weight-loss goal is off because you told us about an eating-disorder history.")).toBeInTheDocument();
    expect(screen.getByLabelText("Targets are paused")).toBeInTheDocument();
    expect(screen.queryByText("ed_history")).toBeNull();
  });

  it("saves the profile and reports the gate sentences", async () => {
    const calls = mockApi({
      ...base,
      "PUT /health/profile": () => ({ ...profile, goal: "maintain" }),
    });
    renderWithProviders(<HealthSettings />);
    await userEvent.click(await screen.findByRole("button", { name: "Open profile and targets" }));
    const sheet = await screen.findByRole("dialog", { name: "Profile and targets" });
    expect(within(sheet).getByText(/only used for energy estimates/)).toBeInTheDocument();
    await userEvent.type(within(sheet).getByLabelText("Birth year"), "1990");
    await userEvent.type(within(sheet).getByLabelText("Height (cm)"), "172");
    await userEvent.click(within(sheet).getByRole("radio", { name: "Lose weight" }));
    await userEvent.click(within(sheet).getByRole("radio", { name: "0.5 % a week" }));
    await userEvent.click(within(sheet).getByRole("switch", { name: /history of an eating disorder/ }));
    await userEvent.click(within(sheet).getByRole("button", { name: "Save profile" }));
    expect(await screen.findByText("A weight-loss goal is off because you told us about an eating-disorder history.", { selector: "[role=status] p" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ birth_year: 1990, height_cm: "172", goal: "lose", target_rate_pct_per_week: "0.5", ed_history: true, numbers_free: false });
  });
});
