import { describe, expect, it } from "vitest";

import type { Booking, TripDetail } from "../api";
import { dayIsFree, nextUp } from "./TripStage";

// Made-up trips and bookings, with only the fields the rules read.
const booking = (extra: Partial<Booking>): Booking =>
  ({
    id: "b1",
    kind: "activity",
    title: "Plan",
    starts: "2027-04-03",
    scheduled: true,
    segments: [],
    hotel: null,
    check_in: null,
    check_out: null,
    at: null,
    ...extra,
  }) as Booking;

const detail = (extra: { trip?: Record<string, unknown>; bookings?: Booking[]; ready?: Record<string, unknown>; owed?: TripDetail["owed"] } = {}): TripDetail =>
  ({
    trip: { start: "2027-04-02", end: "2027-04-05", days: 4, status: "upcoming", days_until: 30, packing: [], ...extra.trip },
    bookings: extra.bookings ?? [],
    ready: { nights_without_stay: [], has_transport: true, has_budget: true, ...extra.ready },
    owed: extra.owed ?? [],
  }) as unknown as TripDetail;

const ideas = (n: number) => () => n;

describe("a day with nothing on it", () => {
  const stay = booking({ id: "h", kind: "hotel", starts: "2027-04-02", check_in: "2027-04-02", check_out: "2027-04-04", hotel: "Hotel Ume" });
  it("is free in the middle of a stay, busy on check-in and check-out", () => {
    const d = detail({ bookings: [stay] });
    expect(dayIsFree(d, "2027-04-02")).toBe(false);
    expect(dayIsFree(d, "2027-04-03")).toBe(true);
    expect(dayIsFree(d, "2027-04-04")).toBe(false);
  });

  it("counts a flight that lands on the day, and plans not yet on a day don't count", () => {
    const flight = booking({ id: "f", kind: "flight", starts: "2027-04-02", segments: [{ number: "ZZ12", origin: "SIN", destination: "NRT", departs: "2027-04-02T23:10", arrives: "2027-04-03T07:00" }] });
    expect(dayIsFree(detail({ bookings: [flight] }), "2027-04-03")).toBe(false);
    expect(dayIsFree(detail({ bookings: [booking({ scheduled: false })] }), "2027-04-03")).toBe(true);
  });
});

describe("next up while planning", () => {
  it("asks for the first thing still to sort", () => {
    const d = detail({ ready: { nights_without_stay: ["2027-04-03"], has_transport: false } });
    const next = nextUp(d, ideas(2));
    expect(next?.text).toMatch(/^1 night without a place to stay/);
    expect(next).toMatchObject({ action: "Add", go: { fix: { kind: "hotel", day: "2027-04-03" } } });
  });

  it("points at the first free day and how many ideas could fill it", () => {
    const d = detail({ bookings: [booking({ starts: "2027-04-02" })] });
    expect(nextUp(d, ideas(3))).toEqual({ text: "Day 2 is still free. 3 of your ideas could fill it.", action: "Find ideas", go: { tab: "ideas", day: "2027-04-03" } });
  });

  it("leaves out the ideas when there are none", () => {
    expect(nextUp(detail(), ideas(0))?.text).toBe("Day 1 is still free.");
  });

  it("says nothing when every day has something", () => {
    const days = ["2027-04-02", "2027-04-03", "2027-04-04", "2027-04-05"];
    expect(nextUp(detail({ bookings: days.map((starts, i) => booking({ id: `p${i}`, starts })) }), ideas(3))).toBeNull();
  });
});

describe("next up in the last week", () => {
  const soon = { status: "upcoming", days_until: 3 };
  const now = new Date(2027, 3, 1, 12, 0);

  it("names the next booking with its day and time", () => {
    const flight = booking({ id: "f", kind: "flight", title: "SIN to NRT", starts: "2027-04-02", segments: [{ number: "SQ 638", origin: "SIN", destination: "NRT", departs: "2027-04-02T07:40", arrives: "2027-04-02T15:30" }] });
    const later = booking({ id: "d", title: "Dinner at Sushi Ten", starts: "2027-04-03", at: "19:00" });
    expect(nextUp(detail({ trip: soon, bookings: [later, flight] }), ideas(0), now)).toEqual({
      text: "Next: SQ 638 on Fri 2 Apr at 07:40",
      action: "Open day",
      go: { tab: "plan", day: "2027-04-02" },
    });
  });

  it("falls back to what's left to pack", () => {
    const packing = [{ text: "Charger", done: true }, { text: "Passport", done: false }, { text: "Hat", done: false }];
    expect(nextUp(detail({ trip: { ...soon, packing } }), ideas(0), now)).toMatchObject({ text: "2 things left to pack", go: { tab: "prep" } });
    expect(nextUp(detail({ trip: { ...soon, packing: [{ text: "Charger", done: true }] } }), ideas(0), now)).toBeNull();
  });
});

describe("next up during the trip", () => {
  const trip = { status: "ongoing", days_until: 0 };
  const lunch = booking({ id: "l", title: "Lunch at Hanok Noodle Bar", starts: "2027-04-03", at: "12:30" });
  const dinner = booking({ id: "d", title: "Dinner at Sushi Ten", starts: "2027-04-03", at: "19:00" });

  it("is the next timed entry today after now", () => {
    expect(nextUp(detail({ trip, bookings: [dinner, lunch] }), ideas(0), new Date(2027, 3, 3, 13, 0))).toEqual({
      text: "Next: Dinner at Sushi Ten at 19:00",
      action: "Open today",
      go: { tab: "plan", day: "2027-04-03" },
    });
  });

  it("is nothing once today's entries are done", () => {
    expect(nextUp(detail({ trip, bookings: [dinner, lunch] }), ideas(0), new Date(2027, 3, 3, 21, 0))).toBeNull();
  });
});

describe("next up after the trip", () => {
  const trip = { status: "finished" };
  const owes = (name: string) => ({ name, amounts: [{ amount: "120", currency: "SGD" }], home: { amount: "120", currency: "SGD" } });

  it("says who still owes you", () => {
    const text = nextUp(detail({ trip, owed: [owes("Alex")] }), ideas(0))?.text;
    expect(text).toMatch(/^Alex still owes you .*120/);
  });

  it("counts people when several owe you", () => {
    expect(nextUp(detail({ trip, owed: [owes("Alex"), owes("Sam")] }), ideas(0))).toMatchObject({ text: "2 people still owe you", go: { tab: "money" } });
  });

  it("is nothing when nobody does", () => {
    expect(nextUp(detail({ trip }), ideas(0))).toBeNull();
  });
});
