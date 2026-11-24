import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { calm, CHECK_IN_TEXT, consented, day, hiddenDay, lunch, rice, signposts, signpostsUnder18, totals } from "./bodyFixtures";
import { HealthFood } from "./HealthFood";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const base = { "GET /health/consent": () => consented };

describe("Food", () => {
  it("shows meals with a range, never a single number, and what is left of the target", async () => {
    mockApi({ ...base, "GET /health/day": () => day() });
    renderWithProviders(<HealthFood />);
    const meals = await screen.findByRole("list", { name: "Meals" });
    expect(within(meals).getByText("Lunch")).toBeInTheDocument();
    expect(within(meals).getByText("Chicken rice")).toBeInTheDocument();
    expect(within(meals).getByText("about 600–750 kcal")).toBeInTheDocument();
    expect(screen.queryByText(/675/)).toBeNull();
    expect(screen.getByRole("list", { name: "Day totals" })).toHaveTextContent("about 600–750 kcal");
    expect(screen.getByRole("list", { name: "Against your target" })).toHaveTextContent("about 1,225 kcal");
  });

  it("hides every number in numbers-free mode", async () => {
    mockApi({ ...base, "GET /health/day": () => hiddenDay() });
    renderWithProviders(<HealthFood />);
    const meals = await screen.findByRole("list", { name: "Meals" });
    expect(within(meals).getByText("Chicken rice")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/kcal/);
    expect(screen.queryByText("The day so far")).toBeNull();
  });

  it("says targets are paused, with links to help, when they are suspended", async () => {
    mockApi({ ...base, "GET /health/day": () => day({ targets_kcal: null, remaining: null, safety: { ...calm, suspended: true, signposts } }) });
    renderWithProviders(<HealthFood />);
    const note = await screen.findByLabelText("Targets are paused");
    expect(note).toHaveTextContent("Targets are paused for now");
    expect(within(note).getByRole("link", { name: "1767, or WhatsApp 9151 1767" })).toHaveAttribute("href", "tel:1767");
    expect(within(note).getByRole("link", { name: "eatingdisorders@sgh.com.sg" })).toHaveAttribute("href", "mailto:eatingdisorders@sgh.com.sg");
    expect(note).not.toHaveAttribute("role", "alert");
    expect(screen.queryByRole("list", { name: "Against your target" })).toBeNull();
  });

  it("shows the soft check-in once", async () => {
    const check = { ...calm, suspended: true, signposts: signpostsUnder18, new_signals: ["restriction"], check_in: CHECK_IN_TEXT };
    mockApi({ ...base, "GET /health/day": () => day({ safety: check }) });
    const first = renderWithProviders(<HealthFood />);
    const sheet = await screen.findByRole("dialog", { name: "Checking in" });
    expect(sheet).toHaveTextContent(CHECK_IN_TEXT);
    expect(within(sheet).getByRole("link", { name: "1767, or WhatsApp 9151 1767" })).toHaveAttribute("href", "tel:1767");
    expect(within(sheet).getByRole("link", { name: "6294 4050" })).toHaveAttribute("href", "tel:62944050");
    expect(within(sheet).getByRole("link", { name: "eatingdisorders@sgh.com.sg" })).toHaveAttribute("href", "mailto:eatingdisorders@sgh.com.sg");
    expect(within(sheet).getByText("Appointments for under-18s.")).toBeInTheDocument();
    await userEvent.click(within(sheet).getAllByRole("button", { name: "Close" }).at(-1)!); // the footer button; the corner X does the same
    expect(screen.queryByRole("dialog", { name: "Checking in" })).toBeNull();
    first.unmount();
    renderWithProviders(<HealthFood />);
    await screen.findByRole("list", { name: "Meals" });
    expect(screen.queryByRole("dialog", { name: "Checking in" })).toBeNull();
  });

  it("logs a food: search, a portion, a cooking style, a slot, and shows the server's range", async () => {
    const calls = mockApi({
      ...base,
      "GET /health/day": () => day({ meals: [], totals: null, remaining: null }),
      "GET /health/foods": () => [rice],
      "POST /health/meals": () => lunch,
    });
    renderWithProviders(<HealthFood />);
    await userEvent.click(await screen.findByRole("button", { name: "Log food" }));
    const sheet = await screen.findByRole("dialog", { name: "Log food" });
    await userEvent.click(within(sheet).getByRole("radio", { name: "Lunch" }));
    await userEvent.type(within(sheet).getByRole("searchbox", { name: "Search foods" }), "chicken");
    await userEvent.click(await within(sheet).findByRole("button", { name: "Choose Chicken rice" }));
    expect(within(sheet).getByLabelText("Portion")).toHaveValue("0");
    await userEvent.click(within(sheet).getByRole("radio", { name: "Stir-fried" }));
    await userEvent.click(within(sheet).getByRole("button", { name: "Add to meal" }));
    expect(within(sheet).getByRole("list", { name: "Foods in this meal" })).toHaveTextContent("1 plate · Stir-fried");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save meal" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/health/meals");
    expect(post?.body).toEqual({ meal: "lunch", items: [{ food_id: "rice-1", grams: "350", label: "1 plate", kind: "portion", cooking: "stir-fried", note: null }] });
    expect(await screen.findByRole("status")).toHaveTextContent("Lunch saved: about 600–750 kcal.");
  });

  it("takes grams for a food, and will not add a zero", async () => {
    const calls = mockApi({ ...base, "GET /health/day": () => day({ meals: [], totals: null, remaining: null }), "GET /health/foods": () => [rice], "POST /health/meals": () => lunch });
    renderWithProviders(<HealthFood />);
    await userEvent.click(await screen.findByRole("button", { name: "Log food" }));
    const sheet = await screen.findByRole("dialog", { name: "Log food" });
    await userEvent.type(within(sheet).getByRole("searchbox", { name: "Search foods" }), "chicken");
    await userEvent.click(await within(sheet).findByRole("button", { name: "Choose Chicken rice" }));
    await userEvent.selectOptions(within(sheet).getByLabelText("Portion"), "grams");
    expect(within(sheet).getByRole("button", { name: "Add to meal" })).toBeDisabled();
    await userEvent.type(within(sheet).getByLabelText("Grams"), "120");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add to meal" }));
    await userEvent.click(within(sheet).getByRole("button", { name: "Save meal" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ items: [{ grams: "120", label: "120 g", kind: "weighed", cooking: null }] }));
  });

  it("deletes a meal after asking, and Undo puts it back", async () => {
    let meals = [lunch];
    const calls = mockApi({
      ...base,
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
    renderWithProviders(<HealthFood />);
    await userEvent.click(await screen.findByRole("button", { name: "Open Lunch" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit meal" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete meal" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(within(within(sheet).getByRole("group", { name: "Delete meal" })).getByRole("button", { name: "Delete meal" }));
    const toast = await screen.findByText("Meal deleted.");
    expect(toast).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/health/meals")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ meal: "lunch", eaten_at: lunch.eaten_at, items: [{ food_id: "rice-1", grams: "350" }] });
    expect(totals.low.kcal).toBe("600");
  });

  it("goes to the day before", async () => {
    const calls = mockApi({ ...base, "GET /health/day": (_b, url) => day({ date: url.searchParams.get("date") ?? day().date, meals: [], totals: null, remaining: null }) });
    renderWithProviders(<HealthFood />);
    await userEvent.click(await screen.findByRole("button", { name: "Previous day" }));
    expect(await screen.findByRole("heading", { name: "Yesterday" })).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/health/day")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Next day" })).toBeEnabled();
  });
});
