import { describe, expect, it } from "vitest";

import type { Booking } from "../api";
import { PLACES, afterFor, daySpot, gapsFor, spotsOf, withMove } from "./TripArrange";

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
