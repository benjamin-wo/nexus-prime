import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Research } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { ResearchPage, addedText, budgetLine, changeText, clipDates, planStop, stopsWith } from "./Research";

// A made-up trip and made-up research dates.
const trip = { start: "2027-01-10", end: "2027-01-17" };

describe("clipDates", () => {
  it("keeps dates already inside the trip", () => {
    expect(clipDates("2027-01-12", "2027-01-14", trip)).toEqual({ start: "2027-01-12", end: "2027-01-14" });
  });
  it("cuts dates that run past either end", () => {
    expect(clipDates("2027-01-08", "2027-01-12", trip)).toEqual({ start: "2027-01-10", end: "2027-01-12" });
    expect(clipDates("2027-01-15", "2027-01-20", trip)).toEqual({ start: "2027-01-15", end: "2027-01-17" });
  });
  it("is null when none of the dates are in the trip", () => {
    expect(clipDates("2027-02-01", "2027-02-05", trip)).toBeNull();
    expect(clipDates("2026-12-01", "2027-01-09", trip)).toBeNull();
  });
  it("keeps a single shared day", () => {
    expect(clipDates("2027-01-17", "2027-01-20", trip)).toEqual({ start: "2027-01-17", end: "2027-01-17" });
  });
});

describe("planStop", () => {
  const whole = { name: "Tokyo", start: "2027-01-10", end: "2027-01-17" };
  const plan = (current: { name: string; start: string; end: string }[], dates: { start: string; end: string }) => planStop(current, " Osaka ", dates, trip);

  it("trims a whole-trip stop that the new stop reaches the end of", () => {
    const got = plan([whole], { start: "2027-01-14", end: "2027-01-25" });
    expect(got?.stops).toEqual([
      { name: "Tokyo", start: "2027-01-10", end: "2027-01-14" },
      { name: "Osaka", start: "2027-01-14", end: "2027-01-17" },
    ]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "ends", on: "2027-01-14" }]);
  });

  it("puts a stop at the trip end after the one before, sharing the travel day", () => {
    const current = [
      { name: "Tokyo", start: "2027-01-10", end: "2027-01-14" },
      { name: "Kyoto", start: "2027-01-14", end: "2027-01-17" },
    ];
    const got = plan(current, { start: "2027-01-16", end: "2027-01-17" });
    expect(got?.stops.map((x) => [x.name, x.start, x.end])).toEqual([
      ["Tokyo", "2027-01-10", "2027-01-14"],
      ["Kyoto", "2027-01-14", "2027-01-16"],
      ["Osaka", "2027-01-16", "2027-01-17"],
    ]);
  });

  it("trims the start of a stop that the new stop runs into from before", () => {
    const got = plan([whole], { start: "2027-01-08", end: "2027-01-12" });
    expect(got?.stops).toEqual([
      { name: "Osaka", start: "2027-01-10", end: "2027-01-12" },
      { name: "Tokyo", start: "2027-01-12", end: "2027-01-17" },
    ]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "starts", on: "2027-01-12" }]);
  });

  it("splits a stop around a new stop in the middle", () => {
    const got = plan([whole], { start: "2027-01-12", end: "2027-01-14" });
    expect(got?.stops).toEqual([
      { name: "Tokyo", start: "2027-01-10", end: "2027-01-12" },
      { name: "Osaka", start: "2027-01-12", end: "2027-01-14" },
      { name: "Tokyo", start: "2027-01-14", end: "2027-01-17" },
    ]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "splits", endsOn: "2027-01-12", startsOn: "2027-01-14" }]);
  });

  it("replaces a stop the new stop covers exactly, or lies inside", () => {
    const got = plan([whole], { start: "2027-01-10", end: "2027-01-17" });
    expect(got?.stops).toEqual([{ name: "Osaka", start: "2027-01-10", end: "2027-01-17" }]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "goes" }]);
    const inside = plan(
      [{ name: "Tokyo", start: "2027-01-10", end: "2027-01-12" }, { name: "Nara", start: "2027-01-12", end: "2027-01-13" }, { name: "Kyoto", start: "2027-01-13", end: "2027-01-17" }],
      { start: "2027-01-12", end: "2027-01-13" },
    );
    expect(inside?.stops.map((x) => x.name)).toEqual(["Tokyo", "Osaka", "Kyoto"]);
  });

  it("leaves stops alone that only share the travel day", () => {
    const current = [{ name: "Tokyo", start: "2027-01-10", end: "2027-01-14" }];
    const got = plan(current, { start: "2027-01-14", end: "2027-01-17" });
    expect(got?.changes).toEqual([]);
    expect(got?.stops[0]).toEqual(current[0]);
  });

  it("clips the new stop to the trip and does not change the stops it was given", () => {
    const current = [whole];
    const got = plan(current, { start: "2027-01-15", end: "2027-03-01" });
    expect(got?.stops[1]).toEqual({ name: "Osaka", start: "2027-01-15", end: "2027-01-17" });
    expect(current).toEqual([whole]);
  });

  it("is null when the dates don't fit the trip", () => {
    expect(plan([whole], { start: "2027-03-01", end: "2027-03-04" })).toBeNull();
  });

  it("is null when the result would break the stops rules", () => {
    // A one-day stop in the middle of a stop would start on the same day as the rest of it.
    expect(plan([whole], { start: "2027-01-12", end: "2027-01-12" })).toBeNull();
    // Eleven stops is one too many.
    const long = { start: "2027-01-01", end: "2027-01-31" };
    const iso = (d: number) => `2027-01-${String(d).padStart(2, "0")}`;
    const ten = Array.from({ length: 10 }, (_, n) => ({ name: `Stop ${n}`, start: iso(1 + n), end: iso(2 + n) }));
    expect(planStop(ten, "Osaka", { start: iso(20), end: iso(22) }, long)).toBeNull();
    expect(planStop(ten.slice(1), "Osaka", { start: iso(20), end: iso(22) }, long)?.stops).toHaveLength(10);
  });
});

describe("stopsWith", () => {
  it("is the stops of the plan, or null", () => {
    const tokyo = { name: "Tokyo", start: "2027-01-10", end: "2027-01-17" };
    expect(stopsWith([tokyo], "Osaka", { start: "2027-01-14", end: "2027-01-17" }, trip)?.map((x) => x.name)).toEqual(["Tokyo", "Osaka"]);
    expect(stopsWith([tokyo], "Osaka", { start: "2027-03-01", end: "2027-03-04" }, trip)).toBeNull();
  });
});

describe("changeText", () => {
  it("says what happens to a stop", () => {
    expect(changeText({ name: "Tokyo", kind: "goes" })).toBe("Tokyo would be replaced");
    expect(changeText({ name: "Tokyo", kind: "ends", on: "2027-01-14" })).toMatch(/^Tokyo would end on .*14/);
    expect(changeText({ name: "Tokyo", kind: "starts", on: "2027-01-14" })).toMatch(/^Tokyo would start on .*14/);
    expect(changeText({ name: "Tokyo", kind: "splits", endsOn: "2027-01-12", startsOn: "2027-01-14" })).toMatch(/end on .*12 and start again on .*14/);
  });
});

describe("addedText", () => {
  it("says how many were added and how many were already there", () => {
    expect(addedText({ added: 9, skipped: 2 }, "Japan in spring")).toBe("Added 9 ideas to Japan in spring (2 were already there)");
  });
  it("uses the singular and leaves out nothing skipped", () => {
    expect(addedText({ added: 1, skipped: 0 }, "Japan in spring")).toBe("Added 1 idea to Japan in spring");
    expect(addedText({ added: 0, skipped: 1 }, "Japan in spring")).toBe("Added 0 ideas to Japan in spring (1 was already there)");
  });
});

// Intl puts a no-break space after the currency code.
const plain = (text: string | null) => (text ?? "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();

const research = (extra: Partial<Research> = {}): Research => ({
  destination: "Tokyo",
  start: "2027-01-10",
  end: "2027-01-17",
  nights: 7,
  travellers: 2,
  currency: "JPY",
  home_currency: "SGD",
  when_summary: "January is cold and dry.",
  when: [{ text: "Days are cold but clear.", source: 1 }],
  prices: [{ label: "Daily spending", low: "8000", high: "15000", currency: "JPY", per: "day", source: 1, home_low: "72", home_high: "135" }],
  areas: [{ name: "Shinjuku", why: "Close to everything.", things: ["Omoide Yokocho"], source: 1 }],
  getting_around: "An IC card covers city trains.",
  getting_around_source: 1,
  sources: [
    { id: 1, url: "https://guide.example.com/tokyo", title: "Tokyo guide", checked_on: "2026-09-28" },
    { id: 2, url: "https://flights.example.com/s", title: "Google Flights", checked_on: "2026-09-28" },
  ],
  estimate_low: "4602",
  estimate_high: "6760",
  estimate_lines: ["Return flights: SGD 2,400-3,200"],
  budget: "6800",
  paydays_left: 3,
  set_aside: "2267",
  fits: true,
  trip_id: null,
  ...extra,
});

async function open(r: Research) {
  mockApi({ "GET /travel/research/": () => r });
  renderWithProviders(<ResearchPage />);
  await screen.findByRole("heading", { level: 1, name: "Tokyo" });
  return screen.getByRole("region", { name: "Estimated cost" });
}

describe("budgetLine", () => {
  const base = { estimate_low: "4602", estimate_high: "6760", home_currency: "SGD" };
  it("fits when the top of the range is within the budget", () => {
    expect(plain(budgetLine({ ...base, budget: "6800" })?.text ?? null)).toBe("Fits your budget of SGD 6,800");
  });
  it("is over, by how much, when even the low end is past it", () => {
    expect(budgetLine({ ...base, budget: "3000" })).toMatchObject({ kind: "over" });
    expect(plain(budgetLine({ ...base, budget: "3000" })?.text ?? null)).toBe("Over your budget of SGD 3,000 by about SGD 1,602");
  });
  it("says it could go over when only the top of the range is past it", () => {
    expect(plain(budgetLine({ ...base, budget: "5000" })?.text ?? null)).toBe("Could go over your budget of SGD 5,000 by up to SGD 1,760");
  });
  it("is nothing without a budget or an estimate", () => {
    expect(budgetLine({ ...base, budget: null })).toBeNull();
    expect(budgetLine({ ...base, estimate_low: null, budget: "5000" })).toBeNull();
  });
});

describe("the research page", () => {
  it("heads the page with a Trips link, the title and one primary action", async () => {
    await open(research());
    expect(screen.getByRole("link", { name: "Trips" })).toHaveAttribute("href", "/travel");
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("accent-serif");
    expect(screen.getByRole("button", { name: "Make it a trip" })).toHaveClass("btn-primary");
    expect(screen.queryByRole("link", { name: "Open the trip" })).toBeNull();
  });

  it("offers Open the trip, softly, once it is made", async () => {
    await open(research({ trip_id: "t1" }));
    expect(screen.getByRole("link", { name: "Open the trip" })).toHaveClass("btn-soft");
    expect(screen.queryByRole("button", { name: "Make it a trip" })).toBeNull();
  });

  it("leads with the estimated cost that fits the budget", async () => {
    const card = await open(research());
    expect(plain(card.textContent)).toContain("SGD 4,602–6,760");
    expect(plain(card.textContent)).toContain("for 7 nights, 2 travellers");
    expect(plain(card.textContent)).toContain("Fits your budget of SGD 6,800");
    expect(card).toHaveTextContent("It fits your cash flow.");
    expect(card).toHaveTextContent("Return flights: SGD 2,400-3,200");
  });

  it("says by how much the estimate is over the budget", async () => {
    const card = await open(research({ budget: "3000", set_aside: null }));
    expect(plain(card.textContent)).toContain("Over your budget of SGD 3,000 by about SGD 1,602");
  });

  it("shows only the estimate when there is no budget", async () => {
    const card = await open(research({ budget: null, set_aside: null, fits: null }));
    expect(plain(card.textContent)).toContain("SGD 4,602–6,760");
    expect(card.textContent).not.toMatch(/budget/i);
  });

  it("says so when there are too few prices to estimate", async () => {
    const card = await open(research({ estimate_low: null, estimate_high: null, estimate_lines: [] }));
    expect(card).toHaveTextContent("Not enough sourced prices to estimate the whole trip.");
  });

  it("lists costs as rows with the amount, its sub line and its source marker", async () => {
    await open(research());
    const costs = screen.getByRole("region", { name: "Costs" });
    const row = within(costs).getByRole("listitem");
    expect(row).toHaveTextContent("Daily spending");
    expect(row).toHaveTextContent("per day");
    expect(plain(row.textContent)).toContain("JPY 8,000–15,000 · SGD 72–135");
    expect(within(row).getByRole("link", { name: "[1]" })).toHaveAttribute("href", "https://guide.example.com/tokyo");
  });

  it("keeps the sources folded until asked", async () => {
    await open(research());
    const toggle = screen.getByRole("button", { name: "Sources · 2" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Tokyo guide" })).toBeNull();
    const user = userEvent.setup();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Tokyo guide" })).toHaveAttribute("rel", expect.stringContaining("noopener"));
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Tokyo guide" })).toBeNull();
  });

  it("keeps the tick boxes for saving an area's ideas", async () => {
    await open(research());
    const box = screen.getByRole("checkbox", { name: "Save its ideas from Shinjuku" });
    expect(box).toBeChecked();
    await userEvent.setup().click(box);
    expect(box).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Add to a trip…" })).toBeDisabled();
  });
});
