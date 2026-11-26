import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { calm, CHECK_IN_TEXT, consented, signposts, day, hiddenDay, hiddenWeight, weight } from "./bodyFixtures";
import { HealthHome } from "./HealthHome";
import { HealthWeight } from "./HealthWeight";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const base = { "GET /health/consent": () => consented, "GET /health/preferences": () => ({ unit: "kg" }) };

describe("Weight", () => {
  it("shows the trend as a chart with dots and a line, the rate sentence and the words", async () => {
    mockApi({ ...base, "GET /health/weight": () => weight() });
    renderWithProviders(<HealthWeight />);
    const chart = await screen.findByRole("img", { name: "Weight trend over 3 days" });
    expect(chart.querySelectorAll("circle.dot.scale")).toHaveLength(2);
    expect(chart.querySelectorAll("path.line")).toHaveLength(1);
    expect(screen.getByText("slowly down")).toBeInTheDocument();
    expect(screen.getByText("about 0.3 kg a week down over the last 2 weeks")).toBeInTheDocument();
  });

  it("shows the trend in pounds when that is the unit", async () => {
    mockApi({ ...base, "GET /health/preferences": () => ({ unit: "lb" }), "GET /health/weight": () => weight() });
    renderWithProviders(<HealthWeight />);
    expect((await screen.findAllByText("181.7 lb")).length).toBeGreaterThan(0);
  });

  it("shows only the words in numbers-free mode: no chart, no figures", async () => {
    mockApi({ ...base, "GET /health/weight": () => hiddenWeight() });
    renderWithProviders(<HealthWeight />);
    expect(await screen.findByText("slowly down")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.body.textContent).not.toMatch(/\d\s?(kg|lb)/);
  });

  it("logs a weight in the person's unit and says what was saved", async () => {
    const calls = mockApi({ ...base, "GET /health/weight": () => weight(), "POST /health/samples": () => ({ id: "s", kind: "weight", value: "82.1", unit: "kg", value_kg: "82.10", start_at: "" }) });
    renderWithProviders(<HealthWeight />);
    await userEvent.click(await screen.findByRole("button", { name: "Log weight" }));
    const sheet = await screen.findByRole("dialog", { name: "Log weight" });
    expect(within(sheet).getByRole("button", { name: "Save weight" })).toBeDisabled();
    await userEvent.type(within(sheet).getByLabelText("Weight (kg)"), "82.1");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save weight" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved 82.1 kg");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ kind: "weight", value: "82.1", unit: "kg" });
  });

  it("says only Saved in numbers-free mode", async () => {
    mockApi({ ...base, "GET /health/weight": () => hiddenWeight(), "POST /health/samples": () => ({}) });
    renderWithProviders(<HealthWeight />);
    await userEvent.click(await screen.findByRole("button", { name: "Log weight" }));
    const sheet = await screen.findByRole("dialog", { name: "Log weight" });
    await userEvent.type(within(sheet).getByLabelText("Weight (kg)"), "82.1");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save weight" }));
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/^Saved$/);
  });
});

describe("Health today", () => {
  const home = (over: Record<string, () => unknown> = {}) =>
    mockApi({
      ...base,
      "GET /health/today": () => ({ routine: { id: "r", name: "Push day", slots: [{}, {}], created_at: "", updated_at: "" }, in_progress: null }),
      "GET /health/day": () => day(),
      "GET /health/weight": () => weight(),
      ...over,
    });

  it("brings the workout, food so far and the weight trend onto one page", async () => {
    home();
    renderWithProviders(<HealthHome />);
    const workout = await screen.findByRole("link", { name: /Push day/ });
    expect(workout).toHaveAttribute("href", "/health/gym");
    expect(await screen.findByText("about 600–750 kcal", { selector: ".row-item:first-child span" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log food" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log weight" })).toBeInTheDocument();
    expect(await screen.findByText("Slowly down")).toBeInTheDocument();
  });

  it("offers Resume when a workout is open", async () => {
    home({ "GET /health/today": () => ({ routine: null, in_progress: { id: "w" } }) });
    renderWithProviders(<HealthHome />);
    expect(await screen.findByRole("link", { name: /Workout in progress/ })).toHaveTextContent("Resume");
  });

  it("hides the numbers in numbers-free mode", async () => {
    home({ "GET /health/day": () => hiddenDay(), "GET /health/weight": () => hiddenWeight() });
    renderWithProviders(<HealthHome />);
    expect(await screen.findByText("Slowly down")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("list", { name: "Meals today" })).toBeInTheDocument());
    expect(document.body.textContent).not.toMatch(/kcal|\d\s?kg/);
  });

  it("shows the check-in from the day it reads", async () => {
    home({ "GET /health/day": () => day({ safety: { ...calm, new_signals: ["a"], check_in: CHECK_IN_TEXT, signposts } }) });
    renderWithProviders(<HealthHome />);
    expect(await screen.findByRole("dialog", { name: "Checking in" })).toHaveTextContent(CHECK_IN_TEXT);
  });
});
