import { describe, expect, it } from "vitest";

import type { Booking } from "../api";
import { EMPTY, type EntryForm, bodyOf, dayName, formOf, hasExtras, tripDays } from "./TripEntry";

// Made-up bookings and places.
const booking = (over: Partial<Booking>): Booking => ({
  id: "b1", trip_id: "t1", kind: "activity", title: "", provider: null, starts: "2026-11-11T00:00:00Z", ends: null, segments: [],
  hotel: null, address: null, check_in: null, check_out: null, name: null, day: null, at: null, note: null, reference: null,
  booked_via: null, category: null, place_id: null, scheduled: false, cost: null, logged: false, manual: true, ...over,
});
const form = (over: Partial<EntryForm>): EntryForm => ({ ...EMPTY, ...over });

describe("bodyOf", () => {
  it("saves a ticket as a plan on its day and time, with where it was booked", () => {
    const body = bodyOf(form({ kind: "ticket", name: "Lantern Museum", day: "2026-11-12", at: "10:30", bookedVia: "Klook", reference: "LM-204" }), "SGD");
    expect(body).toMatchObject({ kind: "activity", name: "Lantern Museum", day: "2026-11-12", at: "10:30", booked_via: "Klook", reference: "LM-204" });
  });

  it("keeps a plan's end time only while it has a start time", () => {
    expect(bodyOf(form({ kind: "activity", name: "Ramen", day: "2026-11-12", at: "19:00", ends: "20:30" }), "SGD")).toMatchObject({ at: "19:00", ends_at: "20:30" });
    expect(bodyOf(form({ kind: "activity", name: "Ramen", day: "2026-11-12", at: "", ends: "20:30" }), "SGD")).toMatchObject({ at: null, ends_at: null });
  });

  it("saves an idea as a plan without a day or time, filed under its list", () => {
    const body = bodyOf(form({ kind: "place", name: "Fish market", list: "Eat", category: "Food" }), "SGD");
    expect(body).toMatchObject({ kind: "activity", name: "Fish market", day: null, at: null, list_name: "Eat", category: "Food" });
  });

  it("saves a stay's dates and a flight's one leg", () => {
    expect(bodyOf(form({ kind: "hotel", name: "Hotel Ume", day: "2026-11-13", until: "2026-11-15" }), "SGD")).toMatchObject({
      kind: "hotel", hotel: "Hotel Ume", check_in: "2026-11-13", check_out: "2026-11-15",
    });
    const flight = bodyOf(form({ kind: "flight", number: "XY12", origin: "SIN", destination: "NRT", departs: "2026-11-10T08:25", provider: "Example Air" }), "SGD");
    expect(flight).toMatchObject({ kind: "flight", provider: "Example Air" });
    expect((flight as { segments: unknown[] }).segments).toEqual([{ number: "XY12", origin: "SIN", destination: "NRT", departs: "2026-11-10T08:25", arrives: null }]);
  });

  it("takes the home currency for a cost with none, and none without a cost", () => {
    expect(bodyOf(form({ kind: "activity", name: "Tour", day: "2026-11-12", cost: "40" }), "SGD")).toMatchObject({ cost: "40", currency: "SGD" });
    expect(bodyOf(form({ kind: "activity", name: "Tour", day: "2026-11-12", cost: "40", currency: "jpy" }), "SGD")).toMatchObject({ currency: "jpy" });
    expect(bodyOf(form({ kind: "activity", name: "Tour", day: "2026-11-12", currency: "JPY" }), "SGD")).toMatchObject({ cost: null, currency: null });
  });
});

describe("formOf", () => {
  it("opens an activity without a day as an idea, and one with a day as a plan", () => {
    expect(formOf(booking({ name: "Fish market", list_name: "Eat" }))).toMatchObject({ kind: "place", name: "Fish market", list: "Eat" });
    expect(formOf(booking({ name: "Ramen", day: "2026-11-12", at: "19:00", scheduled: true }))).toMatchObject({ kind: "activity", day: "2026-11-12", at: "19:00" });
  });

  it("opens a stay by its hotel and check-in", () => {
    expect(formOf(booking({ kind: "hotel", hotel: "Hotel Ume", check_in: "2026-11-13", check_out: "2026-11-15" }))).toMatchObject({
      kind: "hotel", name: "Hotel Ume", day: "2026-11-13", until: "2026-11-15",
    });
  });

  it("brings a ticket back as a plan with its booking details to show", () => {
    const saved = bodyOf(form({ kind: "ticket", name: "Lantern Museum", day: "2026-11-12", at: "10:30", bookedVia: "Klook", reference: "LM-204" }), "SGD");
    const back = formOf(booking({ kind: "activity", name: "Lantern Museum", day: "2026-11-12", at: "10:30", booked_via: "Klook", reference: "LM-204", scheduled: true }));
    expect(back).toMatchObject({ kind: "activity", name: "Lantern Museum", day: "2026-11-12", at: "10:30", bookedVia: "Klook", reference: "LM-204" });
    expect(hasExtras(back)).toBe(true);
    expect(bodyOf(back, "SGD")).toEqual(saved);
  });

  it("round-trips a flight", () => {
    const leg = { number: "XY12", origin: "SIN", destination: "NRT", departs: "2026-11-10T08:25", arrives: "2026-11-10T16:00" };
    const b = booking({ kind: "flight", provider: "Example Air", segments: [leg], scheduled: true });
    expect(bodyOf(formOf(b), "SGD")).toMatchObject({ kind: "flight", provider: "Example Air", segments: [leg] });
  });
});

describe("hasExtras", () => {
  it("is true only when a field under More details has something in it", () => {
    expect(hasExtras(form({ kind: "activity", name: "Ramen", day: "2026-11-12", at: "19:00" }))).toBe(false);
    expect(hasExtras(form({ kind: "activity", note: "  " }))).toBe(false);
    expect(hasExtras(form({ kind: "activity", address: "1 Example-ro" }))).toBe(true);
    expect(hasExtras(form({ kind: "place", link: "https://example.com" }))).toBe(true);
    expect(hasExtras(form({ kind: "flight", provider: "Example Air" }))).toBe(true);
    expect(hasExtras(form({ kind: "hotel", cost: "120" }))).toBe(true);
  });
});

describe("the trip's days", () => {
  it("lists each date from the first to the last", () => {
    expect(tripDays({ start: "2026-11-10", end: "2026-11-13" })).toEqual(["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]);
    expect(tripDays({ start: "2026-02-27", end: "2026-03-02" })).toHaveLength(4);
    expect(tripDays({ start: "2026-11-10", end: "2026-11-10" })).toEqual(["2026-11-10"]);
    expect(tripDays({ start: "2026-11-10", end: "2026-11-01" })).toEqual(["2026-11-10"]);
  });

  it("names a day by its weekday, date and month", () => {
    expect(dayName("2026-04-04")).toMatch(/Sat/);
    expect(dayName("2026-04-04")).toMatch(/4/);
  });
});
