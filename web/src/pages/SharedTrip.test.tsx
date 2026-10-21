import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SharedBooking, SharedTrip } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { SharedTripPage, emptyDayText, stopNames } from "./SharedTrip";

describe("what an empty day on the shared page says", () => {
  it("calls a day a hidden booking falls on a travel day", () => {
    expect(emptyDayText("2027-03-02", ["2027-03-02", "2027-03-09"])).toBe("Travel day");
  });

  it("keeps the plain wording for other days, and when nothing is hidden", () => {
    expect(emptyDayText("2027-03-03", ["2027-03-02"])).toBe("Free day");
    expect(emptyDayText("2027-03-02", [])).toBe("Free day");
  });
});

describe("stopNames", () => {
  const names = (...n: string[]) => n.map((name) => ({ name }));
  it("lists the places in order, once each", () => {
    expect(stopNames(names("Tokyo", "Kyoto", "Osaka"), "Japan")).toBe("Tokyo, Kyoto and Osaka");
    expect(stopNames(names("Tokyo", "Kyoto", "Tokyo"), "Japan")).toBe("Tokyo and Kyoto");
  });
  it("is empty with no stops, or only the destination again", () => {
    expect(stopNames([], "Tokyo")).toBe("");
    expect(stopNames(names("tokyo"), "Tokyo")).toBe("");
    expect(stopNames(names("Kyoto"), "Tokyo")).toBe("Kyoto");
  });
});

// A made-up trip, far enough ahead that none of its days is today.
const booking = (extra: Partial<SharedBooking>): SharedBooking => ({
  kind: "activity",
  title: "",
  provider: null,
  starts: "2027-03-03",
  ends: "2027-03-03",
  segments: [],
  hotel: null,
  address: null,
  check_in: null,
  check_out: null,
  day: "2027-03-03",
  at: null,
  category: null,
  ...extra,
});

const trip = (extra: Partial<SharedTrip> = {}): SharedTrip => ({
  destination: "Japan",
  start: "2027-03-02",
  end: "2027-03-05",
  days: 4,
  status: "upcoming",
  days_until: 90,
  day_number: null,
  day_labels: { "2027-03-03": "Market morning" },
  photo: null,
  stops: [
    { name: "Tokyo", start: "2027-03-02", end: "2027-03-04" },
    { name: "Kyoto", start: "2027-03-04", end: "2027-03-05" },
  ],
  bookings: [booking({ title: "Fish market breakfast", at: "07:30", address: "4-5 Market St" })],
  show_bookings: true,
  hidden_days: [],
  ...extra,
});

async function open(t: SharedTrip) {
  mockApi({ "GET /shared/trips/": () => t });
  renderWithProviders(<SharedTripPage />);
  await screen.findByRole("heading", { level: 1, name: "Japan" });
}

describe("the shared page", () => {
  it("shows the cover's chip, and under the title the dates and the stops", async () => {
    await open(trip());
    expect(screen.getByText("Shared with you · read only")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("accent-serif");
    expect(document.querySelector(".trip-hero-meta")).toHaveTextContent(/ – .* · Tokyo and Kyoto/);
    expect(screen.getByText("Shared from Nexus. No money, booking references, notes or travellers are shown.")).toBeInTheDocument();
  });

  it("leaves the stops out when it has none", async () => {
    await open(trip({ stops: [] }));
    expect(document.querySelector(".trip-hero-meta")).not.toHaveTextContent("·");
  });

  it("makes each day a card: a grey meta line, the day's name or stop in the serif, then its plans with their times", async () => {
    await open(trip());
    const plan = screen.getByRole("region", { name: "The plan" });
    const named = within(plan).getByRole("heading", { name: /^Day 2 · .* Market morning$/ });
    expect(named.querySelector(".shared-day-meta")).toHaveTextContent(/^Day 2 · /);
    expect(named.querySelector(".shared-day-title")).toHaveClass("accent-serif");
    expect(named.querySelector(".shared-day-title")).toHaveTextContent("Market morning");
    // A day with no name of its own takes its stop: the one that starts on a travel day.
    expect(within(plan).getByRole("heading", { name: /^Day 1 · .* Tokyo$/ })).toBeInTheDocument();
    expect(within(plan).getByRole("heading", { name: /^Day 3 · .* Kyoto$/ })).toBeInTheDocument();
    const row = within(named.closest(".shared-day") as HTMLElement).getByRole("listitem");
    expect(row.querySelector(".shared-time")).toHaveTextContent("07:30");
    expect(row).toHaveTextContent("Fish market breakfast");
    expect(within(row).getByRole("link", { name: "Open Fish market breakfast in Google Maps" })).toBeInTheDocument();
    // Days with nothing on them say so.
    expect(within(plan).getAllByText("Free day")).toHaveLength(3);
  });

  it("gives a booking its line icon, not a time", async () => {
    await open(
      trip({
        bookings: [booking({ kind: "hotel", title: "Hotel Kumo, 2 nights", hotel: "Hotel Kumo", starts: "2027-03-02", check_in: "2027-03-02", check_out: "2027-03-04" })],
      }),
    );
    const plan = screen.getByRole("region", { name: "The plan" });
    expect(plan).toHaveTextContent("Staying at Hotel Kumo");
    const row = within(plan).getAllByRole("listitem")[0];
    expect(row.querySelector(".shared-lead svg")).not.toBeNull();
    expect(row).toHaveTextContent("Check in");
  });

  it("puts a hotel's address on its own line under the check-out day, and drops both on that day", async () => {
    const hotel = booking({ kind: "hotel", title: "Hotel Kumo, 2 nights", hotel: "Hotel Kumo", address: "4-5-6 Asakusa", starts: "2027-03-02", check_in: "2027-03-02", check_out: "2027-03-04" });
    await open(trip({ bookings: [hotel] }));
    const days = screen.getAllByRole("listitem").map((li) => li.querySelector(".shared-main"));
    const [checkIn, checkOut] = days as HTMLElement[];
    const lines = Array.from(checkIn.querySelectorAll(".caption")).map((c) => c.textContent);
    expect(lines).toEqual([expect.stringMatching(/^Until /), "4-5-6 Asakusa"]);
    expect(checkIn).not.toHaveTextContent("·");
    // On the check-out day it is just the name and the badge.
    expect(checkOut.querySelector(".caption")).toBeNull();
  });

  it("notes hidden bookings, and calls the days they fall on travel days", async () => {
    await open(trip({ show_bookings: false, hidden_days: ["2027-03-02"], bookings: [] }));
    expect(screen.getByRole("note")).toHaveTextContent("Bookings aren't shown on this link.");
    const plan = screen.getByRole("region", { name: "The plan" });
    expect(within(plan).getAllByText("Travel day")).toHaveLength(1);
    expect(within(plan).getAllByText("Free day")).toHaveLength(3);
  });
});
