import { describe, expect, it } from "vitest";

import type { Booking } from "../api";
import { PLACES, afterFor, arrivalText, daySpot, duration, gapsFor, spotsOf, withMove } from "./TripArrange";

// A made-up trip: every plan and flight here is invented.
function entry(id: string, fields: Partial<Booking>): Booking {
  return {
    id, trip_id: "t1", kind: "activity", title: id, provider: null, starts: "2026-11-11", ends: null, segments: [],
    hotel: null, address: null, check_in: null, check_out: null, reference: null, booked_via: null, category: null,
    scheduled: true, cost: null, logged: false, manual: true, at: null, day: "2026-11-11", ...fields,
  } as Booking;
}

const flight = entry("flight", { kind: "flight", starts: "2026-11-11", segments: [{ number: "ZZ1", origin: "A", destination: "B", departs: "2026-11-11T07:00", arrives: "2026-11-11T08:00" }] });
const temple = entry("temple", { at: "09:00" });
const market = entry("market", { at: "18:00" });
const later = entry("later", { scheduled: false, day: null, starts: "2026-09-28" });
const sooner = entry("sooner", { scheduled: false, day: null, starts: "2026-09-29" });
const bookings = [flight, temple, market, later, sooner];

describe("arranging a trip", () => {
  it("follows the server's order for each day and for places to visit", () => {
    const spots = spotsOf({ bookings, days: [{ day: "2026-11-11", order: ["market", "flight", "temple"], notes: [] }], places_order: ["sooner", "later"] });
    expect(spots.get(daySpot("2026-11-11"))?.map((b) => b.id)).toEqual(["market", "flight", "temple"]);
    expect(spots.get(PLACES)?.map((b) => b.id)).toEqual(["sooner", "later"]);
  });

  it("falls back to time order when the server sends none", () => {
    const spots = spotsOf({ bookings });
    expect(spots.get(daySpot("2026-11-11"))?.map((b) => b.id)).toEqual(["flight", "temple", "market"]);
  });

  it("drops above an entry after the one before it, below it after itself", () => {
    const day = ["flight", "temple", "market"];
    expect(afterFor(day, "market", "temple", false)).toBe("flight");
    expect(afterFor(day, "market", "flight", false)).toBeNull();
    expect(afterFor(day, "temple", "market", true)).toBe("market");
    // On the day itself: the end.
    expect(afterFor(day, "later", daySpot("2026-11-11"), true)).toBe("market");
  });

  it("shows a move straight away, a place turning into a plan on its day", () => {
    const spots = withMove(spotsOf({ bookings }), later, daySpot("2026-11-11"), "temple");
    expect(spots.get(daySpot("2026-11-11"))?.map((b) => b.id)).toEqual(["flight", "temple", "later", "market"]);
    expect(spots.get(PLACES)?.map((b) => b.id)).toEqual(["sooner"]);
    expect(spots.get(daySpot("2026-11-11"))?.[2]).toMatchObject({ scheduled: true, day: "2026-11-11", starts: "2026-11-11" });
  });

  it("steps the keyboard through every gap, days first, then places to visit", () => {
    const gaps = gapsFor(spotsOf({ bookings }), ["2026-11-10", "2026-11-11"], "temple");
    expect(gaps.map((g) => `${g.spot}@${g.after ?? "first"}`)).toEqual([
      "day:2026-11-10@first",
      "day:2026-11-11@first",
      "day:2026-11-11@flight",
      "day:2026-11-11@market",
      "places@first",
      "places@later",
      "places@sooner",
    ]);
  });
});

describe("arriving", () => {
  const note = {
    kind: "arrival" as const, text: "Land 09:15, check-in at Hill Lodge from 15:00: 5 h 45 min to fill", ids: ["fl", "lodge"], start: "09:15", end: "15:00",
  };
  const hop = (minutes: number | null) => ({
    start_id: "fl", end_id: "lodge", start: "BCN airport", end: "Hill Lodge", mode: "drive" as const, minutes, metres: 120000, tight: false, directions: "",
  });

  it("counts the way from the airport once its time is known", () => {
    expect(arrivalText(note, [hop(90)])).toBe("Arrive around 10:45 (land 09:15, then 1 h 30 min) · check-in from 15:00 · about 4 h 15 min to fill, or ask about checking in early");
    expect(arrivalText(note, [hop(330)])).toBe("Arrive around 14:45 (land 09:15, then 5 h 30 min) · check-in from 15:00 · about right for check-in");
    // Not known yet, or no way found: the server's words.
    expect(arrivalText(note, [])).toBe(note.text);
    expect(arrivalText(note, [hop(null)])).toBe(note.text);
  });

  it("counts from a hire-car desk beside the airport, past the walk to it", () => {
    const desk = { ...hop(null), start_id: "fl", end_id: "car", end: "Car pickup", mode: "walk" as const, metres: 1200, beside_airport: true };
    const drive = { ...hop(105), start_id: "car", start: "Car pickup" };
    expect(arrivalText(note, [desk, drive])).toBe("Arrive around 11:00 (land 09:15, then 1 h 45 min) · check-in from 15:00 · about 4 h to fill, or ask about checking in early");
    // A stop that isn't beside the airport breaks it: the server's words.
    expect(arrivalText(note, [{ ...desk, beside_airport: false }, drive])).toBe(note.text);
  });

  it("says lengths the way people do", () => {
    expect([duration(25), duration(60), duration(95)]).toEqual(["25 min", "1 h", "1 h 35 min"]);
  });
});
