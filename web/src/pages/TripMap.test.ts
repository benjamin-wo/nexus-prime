import { describe, expect, it } from "vitest";

import type { Booking, LinkedPlace } from "../api";
import { DAY_COLORS, NO_DAY, dayColor, dayPath, distance, mapPins } from "./TripMap";

// A made-up trip: every place, hotel and coordinate here is invented.
const trip = { start: "2026-11-10", end: "2026-11-13" } as const;

function entry(id: string, fields: Partial<Booking>): Booking {
  return {
    id, trip_id: "t1", kind: "activity", title: id, provider: null, starts: "2026-11-11", ends: null, segments: [],
    hotel: null, address: null, check_in: null, check_out: null, reference: null, booked_via: null, category: null,
    scheduled: true, cost: null, logged: false, manual: true, at: null, ...fields,
  } as Booking;
}

function linked(id: string, lat: number | null, lng: number | null): [string, LinkedPlace] {
  const place = { id: `place-${id}`, name: id, lat, lng } as LinkedPlace["place"];
  return [id, { booking_id: id, place, warning: null }];
}

const inn = entry("inn", { kind: "hotel", hotel: "Harbour Inn", starts: "2026-11-10", check_in: "2026-11-10", check_out: "2026-11-12" });
const temple = entry("temple", { title: "Old Temple", starts: "2026-11-11", at: "09:00" });
const unplaced = entry("walk", { title: "A walk", starts: "2026-11-11", at: "08:00" });
const lunch = entry("lunch", { title: "Noodle lunch", starts: "2026-11-11", at: "12:00" });
const later = entry("later", { title: "Someday", scheduled: false, starts: "2026-09-28" });
const unknown = entry("nowhere", { title: "Not on the map", starts: "2026-11-11", at: "15:00" });

const places = new Map([
  linked("inn", 37.56, 126.97),
  linked("temple", 37.57, 126.98),
  linked("lunch", 37.565, 126.99),
  linked("later", 37.55, 126.96),
  linked("nowhere", null, null),
]);

describe("the trip map", () => {
  const pins = mapPins({ trip: trip as never, bookings: [inn, temple, unplaced, lunch, later, unknown] }, places);

  it("pins only places with coordinates, numbered as on their day", () => {
    expect(pins.map((p) => [p.id, p.label, p.kind])).toEqual([
      ["inn", "H", "hotel"],
      ["temple", "2", "plan"], // the unplaced 08:00 walk is plan 1 on the itinerary
      ["lunch", "3", "plan"],
      ["later", "", "place"],
    ]);
    expect(pins.find((p) => p.id === "inn")?.days).toEqual(["2026-11-10", "2026-11-11", "2026-11-12"]);
  });

  it("colours each day, places with no day grey", () => {
    expect(dayColor(trip, "2026-11-10")).toBe(DAY_COLORS[0]);
    expect(dayColor(trip, "2026-11-18")).toBe(DAY_COLORS[0]); // day 9 wraps round
    expect(dayColor(trip, null)).toBe(NO_DAY);
    expect(pins.find((p) => p.id === "lunch")?.color).toBe(DAY_COLORS[1]);
  });

  it("draws a day from last night's hotel through its plans and back", () => {
    expect(dayPath(pins, "2026-11-11").map((p) => p.id)).toEqual(["inn", "temple", "lunch", "inn"]);
    // Check-out day: the morning at the inn, and no night there.
    expect(dayPath(pins, "2026-11-12").map((p) => p.id)).toEqual(["inn"]);
  });

  it("numbers and draws a day in the itinerary's order once it's been rearranged", () => {
    const days = [{ day: "2026-11-11", order: ["lunch", "walk", "temple", "nowhere"], notes: [] }];
    const moved = mapPins({ trip: trip as never, bookings: [inn, temple, unplaced, lunch, later, unknown], days }, places);
    expect(moved.filter((p) => p.kind === "plan").map((p) => [p.id, p.label])).toEqual([
      ["temple", "3"],
      ["lunch", "1"],
    ]);
    expect(dayPath(moved, "2026-11-11").map((p) => p.id)).toEqual(["inn", "lunch", "temple", "inn"]);
  });

  it("says distances the way people do", () => {
    expect(distance(944)).toBe("940 m");
    expect(distance(1450)).toBe("1.4 km");
  });
});
