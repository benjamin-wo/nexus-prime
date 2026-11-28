import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import type { Meal } from "./bodyApi";
import { calm, CHECK_IN_TEXT, consented, day, hiddenDay, hiddenWeight, lunch, signposts, weight } from "./bodyFixtures";
import { HealthHome } from "./HealthHome";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const estimate: Meal = {
  ...lunch,
  id: "m2",
  meal: "dinner",
  items: [{ ...lunch.items[0], id: "i2", food_id: null, source_detail: "ai_estimate", name: "Laksa", kind: "estimated" }],
};
const base = { "GET /health/consent": () => consented, "GET /health/preferences": () => ({ unit: "kg" }) };
const home = (over: Record<string, (body: unknown, url: URL) => unknown> = {}) =>
  mockApi({
    ...base,
    "GET /health/today": () => ({ routine: { id: "r", name: "Push day", slots: [{}, {}], created_at: "", updated_at: "" }, in_progress: null }),
    "GET /health/day": () => day({ meals: [lunch, estimate] }),
    "GET /health/weight": () => weight(),
    ...over,
  });

describe("Today", () => {
  it("is a daily log: the hint, meals with their figures, the day line, the workout and one weight line", async () => {
    home();
    const chat = vi.fn();
    renderWithProviders(<HealthHome onOpenChat={chat} />);
    await userEvent.click(await screen.findByRole("button", { name: "Open chat" }));
    expect(chat).toHaveBeenCalledOnce();
    const meals = await screen.findByRole("list", { name: "Meals today" });
    const first = within(meals).getByRole("button", { name: "Open Lunch" });
    expect(first).toHaveTextContent("Lunch · Chicken rice");
    expect(first).toHaveTextContent("about 600–750 kcal · about 30–40 g protein");
    expect(first).not.toHaveTextContent("rough guide");
    expect(within(meals).getByRole("button", { name: "Open Dinner" })).toHaveTextContent("Dinner · Laksa");
    expect(within(meals).getByRole("button", { name: "Open Dinner" })).toHaveTextContent("rough guide");
    expect(screen.getByText(/so far. A rough guide./)).toHaveTextContent("About 600–750 kcal · about 30–40 g protein so far. A rough guide.");
    expect(screen.getByRole("link", { name: /Push day/ })).toHaveAttribute("href", "/health/gym");
    expect(await screen.findByText("82.4 kg, slowly down")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log weight" })).toBeInTheDocument();
    expect(screen.queryByText("Before you start")).toBeNull();
    expect(screen.queryByRole("button", { name: /profile/i })).toBeNull();
  });

  it("offers Resume when a workout is open, and Ask Nexus when none is planned", async () => {
    home({ "GET /health/today": () => ({ routine: null, in_progress: { id: "w" } }) });
    const first = renderWithProviders(<HealthHome />);
    expect(await screen.findByRole("link", { name: /Workout in progress/ })).toHaveTextContent("Resume");
    first.unmount();
    vi.restoreAllMocks();
    home({ "GET /health/today": () => ({ routine: null, in_progress: null }) });
    const chat = vi.fn();
    renderWithProviders(<HealthHome onOpenChat={chat} />);
    await userEvent.click(await screen.findByRole("button", { name: "Ask Nexus for a workout" }));
    expect(chat).toHaveBeenCalledOnce();
  });

  it("hides every number in numbers-free mode", async () => {
    home({ "GET /health/day": () => hiddenDay(), "GET /health/weight": () => hiddenWeight() });
    renderWithProviders(<HealthHome />);
    expect(await screen.findByText("Slowly down")).toBeInTheDocument();
    await screen.findByRole("list", { name: "Meals today" });
    expect(document.body.textContent).not.toMatch(/kcal|\d\s?kg|protein/);
  });

  it("says targets are paused, with links to help, when they are suspended", async () => {
    home({ "GET /health/day": () => day({ targets_kcal: null, remaining: null, safety: { ...calm, suspended: true, signposts } }) });
    renderWithProviders(<HealthHome />);
    const note = await screen.findByLabelText("Targets are paused");
    expect(within(note).getByRole("link", { name: "1767, or WhatsApp 9151 1767" })).toHaveAttribute("href", "tel:1767");
    expect(screen.queryByText(/left of about/)).toBeNull();
  });

  it("shows what is left of a target when there is one", async () => {
    home();
    renderWithProviders(<HealthHome />);
    expect(await screen.findByText("About 1,225 kcal left of about 1,900 today.")).toBeInTheDocument();
  });

  it("shows the soft check-in from the day it reads", async () => {
    home({ "GET /health/day": () => day({ safety: { ...calm, new_signals: ["a"], check_in: CHECK_IN_TEXT, signposts } }) });
    renderWithProviders(<HealthHome />);
    expect(await screen.findByRole("dialog", { name: "Checking in" })).toHaveTextContent(CHECK_IN_TEXT);
  });

  it("opens a meal's edit sheet from ?meal=<id>", async () => {
    home();
    renderWithProviders(<HealthHome />, "/health?meal=m2");
    const sheet = await screen.findByRole("dialog", { name: "Edit meal" });
    expect(within(sheet).getByRole("list", { name: "Foods in this meal" })).toHaveTextContent("Laksa");
  });

  it("deletes a meal after asking, and Undo puts it back", async () => {
    let meals = [lunch];
    const calls = home({
      "GET /health/day": () => day({ meals }),
      [`DELETE /health/meals/${lunch.id}`]: () => {
        meals = [];
        return null;
      },
      "POST /health/meals": () => {
        meals = [lunch];
        return lunch;
      },
    });
    renderWithProviders(<HealthHome />);
    await userEvent.click(await screen.findByRole("button", { name: "Open Lunch" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit meal" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete meal" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(within(within(sheet).getByRole("group", { name: "Delete meal" })).getByRole("button", { name: "Delete meal" }));
    expect(await screen.findByText("Meal deleted.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/health/meals")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ meal: "lunch", eaten_at: lunch.eaten_at, items: [{ food_id: "rice-1", grams: "350" }] });
  });

  it("puts a deleted AI-estimate meal back with its own figures, not a food id", async () => {
    let meals = [estimate];
    const calls = home({
      "GET /health/day": () => day({ meals }),
      [`DELETE /health/meals/${estimate.id}`]: () => {
        meals = [];
        return null;
      },
      "POST /health/meals": () => {
        meals = [estimate];
        return estimate;
      },
    });
    renderWithProviders(<HealthHome />);
    await userEvent.click(await screen.findByRole("button", { name: "Open Dinner" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit meal" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete meal" }));
    await userEvent.click(within(within(sheet).getByRole("group", { name: "Delete meal" })).getByRole("button", { name: "Delete meal" }));
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/health/meals")).toBe(true));
    const item = (calls.find((c) => c.method === "POST")?.body as { items: Record<string, unknown>[] }).items[0];
    expect(item).toMatchObject({ food_id: null, name: "Laksa", grams: "350", estimate: { kcal: "675", protein_g: "10", carbs_g: "50", fat_g: "10" } });
  });

  it("logs a weight from the line, and shows the full trend behind See trend", async () => {
    const calls = home({ "POST /health/samples": () => ({ id: "s", kind: "weight", value: "82.1", unit: "kg", value_kg: "82.10", start_at: "" }) });
    renderWithProviders(<HealthHome />);
    await userEvent.click(await screen.findByRole("button", { name: "See trend" }));
    const trend = await screen.findByRole("dialog", { name: "Weight trend" });
    expect(await within(trend).findByRole("img", { name: "Weight trend over 3 days" })).toBeInTheDocument();
    await userEvent.click(within(trend).getByRole("button", { name: "Done" }));
    await userEvent.click(screen.getByRole("button", { name: "Log weight" }));
    const sheet = await screen.findByRole("dialog", { name: "Log weight" });
    await userEvent.type(within(sheet).getByLabelText("Weight (kg)"), "82.1");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save weight" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved 82.1 kg");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ kind: "weight", value: "82.1", unit: "kg" });
  });
});

describe("opened from a card in the chat", () => {
  it("shows the day in the address, asking for that day's food", async () => {
    const calls = home();
    renderWithProviders(<HealthHome />, "/health?day=2026-11-20");
    expect(await screen.findByText("Food on 20 Nov 2026")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/health/day")).toBeDefined();
    await waitFor(() => expect(calls.some((c) => c.path === "/health/day")).toBe(true));
  });

  it("reads a day that isn't a date as today", async () => {
    home();
    renderWithProviders(<HealthHome />, "/health?day=nonsense");
    expect(await screen.findByText("Today's food")).toBeInTheDocument();
  });

  it("opens the weight trend with ?weight=trend", async () => {
    home({ "GET /health/weight": () => weight() });
    renderWithProviders(<HealthHome />, "/health?weight=trend");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
