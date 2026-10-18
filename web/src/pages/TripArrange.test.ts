import { describe, expect, it } from "vitest";

import type { Booking, LinkedPlace, TripDetail } from "../api";
import { PLACES, afterFor, arrivalText, daySpot, dayZones, duration, gapsFor, ideaHint, nearbyOf, pickerDays, pointOf, spotsOf, withMove } from "./TripArrange";
import { listColors } from "./TripIdeas";

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

describe("the day picker", () => {
  const trip = { start: "2026-11-10", end: "2026-11-13", day_labels: { "2026-11-12": "Temples" } };
  const detail = {
    trip, bookings, places_order: ["sooner", "later"],
    days: [{ day: "2026-11-11", order: ["market", "flight", "temple"], notes: [] }],
  } as unknown as Parameters<typeof pickerDays>[0];

  it("lists every trip day with its number, label and how much is on it", () => {
    const { days } = pickerDays(detail, later, null);
    expect(days.map((d) => [d.iso, d.number, d.label, d.plans])).toEqual([
      ["2026-11-10", 1, "Free day", 0],
      ["2026-11-11", 2, "", 3],
      ["2026-11-12", 3, "Temples", 0],
      ["2026-11-13", 4, "Free day", 0],
    ]);
  });

  it("sends an idea to the end of a day, and a free day takes it first", () => {
    const { days } = pickerDays(detail, later, null);
    expect(days.map((d) => d.last)).toEqual([null, "temple", null, null]);
  });

  it("puts the viewed day first, only if it is a trip day", () => {
    expect(pickerDays(detail, later, "2026-11-12").viewing?.number).toBe(3);
    expect(pickerDays(detail, later, "2026-12-25").viewing).toBeNull();
    expect(pickerDays(detail, later, null).viewing).toBeNull();
  });

  it("marks the day a plan is on, and leaves it out of that day's count and end", () => {
    const picker = pickerDays(detail, market, null);
    expect(picker.here?.iso).toBe("2026-11-11");
    expect(picker.days[1]).toMatchObject({ here: true, plans: 2, last: "temple" });
    expect(picker.days.filter((d) => d.here)).toHaveLength(1);
    expect(pickerDays(detail, later, null).here).toBeNull();
  });

  it("knows where the end of Ideas is, not counting the idea itself", () => {
    expect(pickerDays(detail, market, null).lastIdea).toBe("later");
    expect(pickerDays(detail, later, null).lastIdea).toBe("sooner");
  });
});

// A made-up two-stop trip: Tokyo-ish pins around 10N 20E, Kyoto-ish pins around 11N 21E.
// A hundredth of a degree of latitude is about 1.1 km.
describe("the day picker, ranked by distance", () => {
  const trip = {
    id: "t1", start: "2026-11-10", end: "2026-11-15", day_labels: { "2026-11-11": "Market day" },
    stops: [] as { name: string; start: string; end: string }[],
  };
  const stops = [
    { name: "Tokyo", start: "2026-11-10", end: "2026-11-13" },
    { name: "Kyoto", start: "2026-11-13", end: "2026-11-15" },
  ];
  const pinned = (id: string, day: string, lat: number, lng: number) => entry(id, { day, starts: day, lat, lng });
  const day1 = pinned("a1", "2026-11-10", 10.0, 20.0);
  const day2 = pinned("a2", "2026-11-11", 10.01, 20.0);
  const day5 = pinned("k1", "2026-11-14", 11.0, 21.0);
  const idea = (id: string, fields: Partial<Booking> = {}) => entry(id, { scheduled: false, day: null, starts: "2026-09-28", ...fields });
  const detailOf = (...extra: Booking[]) =>
    ({ trip: { ...trip, stops }, suggested_stops: [], bookings: [day1, day2, day5, ...extra], places_order: [], days: [] }) as unknown as TripDetail;
  const nearOf = (detail: TripDetail, linked = new Map<string, LinkedPlace>()) => nearbyOf(detail, linked);

  it("ranks the days with places nearby, nearest first, with how far", () => {
    const cafe = idea("cafe", { lat: 10.012, lng: 20.0 });
    const detail = detailOf(cafe);
    const { ranked, closest, home } = pickerDays(detail, cafe, null, nearOf(detail));
    expect(ranked).toBe(true);
    expect(closest.map((d) => d.iso)).toEqual(["2026-11-11", "2026-11-10"]);
    expect(closest.map((d) => Math.round(d.metres! / 100) / 10)).toEqual([0.2, 1.3]);
    // Kyoto's day is some 150 km away: not close.
    expect(closest.map((d) => d.iso)).not.toContain("2026-11-14");
    expect(home).toBe("Tokyo");
  });

  it("then the free days in the same stop, then the other stops' days", () => {
    const cafe = idea("cafe", { lat: 10.012, lng: 20.0 });
    const detail = detailOf(cafe);
    const { free, other } = pickerDays(detail, cafe, null, nearOf(detail));
    // Tokyo's free day only: the 13th is Kyoto's (the travel day belongs to where it ends).
    expect(free.map((d) => d.iso)).toEqual(["2026-11-12"]);
    expect(other.map((o) => [o.name, o.days.map((d) => d.iso)])).toEqual([["Kyoto", ["2026-11-13", "2026-11-14", "2026-11-15"]]]);
  });

  it("follows the idea to Kyoto when that's where it is", () => {
    const tea = idea("tea", { lat: 11.0005, lng: 21.0 });
    const detail = detailOf(tea);
    const { closest, free, other, home } = pickerDays(detail, tea, "2026-11-10", nearOf(detail));
    expect(closest.map((d) => d.iso)).toEqual(["2026-11-14"]);
    expect(home).toBe("Kyoto");
    expect(free.map((d) => d.iso)).toEqual(["2026-11-13", "2026-11-15"]);
    expect(other.map((o) => o.name)).toEqual(["Tokyo"]);
  });

  it("takes the place Google Maps found over nothing, and an own pin without one", () => {
    const linked = new Map<string, LinkedPlace>([["found", { booking_id: "found", warning: null, place: { id: "p", name: "Found", lat: 10.0, lng: 20.001 } as LinkedPlace["place"] }]]);
    const found = idea("found");
    const detail = detailOf(found);
    expect(pointOf(found, linked)).toEqual({ lat: 10.0, lng: 20.001 });
    expect(pickerDays(detail, found, null, nearOf(detail, linked)).closest[0]).toMatchObject({ iso: "2026-11-10" });
    expect(pointOf(found, new Map())).toBeNull();
    expect(pointOf(idea("own", { lat: 1, lng: 2 }), new Map())).toEqual({ lat: 1, lng: 2 });
  });

  it("keeps today's order without coordinates", () => {
    const vague = idea("vague");
    const detail = detailOf(vague);
    const picker = pickerDays(detail, vague, "2026-11-12", nearOf(detail));
    expect(picker.ranked).toBe(false);
    expect(picker.closest).toEqual([]);
    expect(picker.days.map((d) => d.iso)).toEqual(["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"]);
    expect(picker.viewing?.iso).toBe("2026-11-12");
    // And with no nearby info at all, as before.
    expect(pickerDays(detail, vague, null).ranked).toBe(false);
  });

  it("names a day by its own label, else a free day", () => {
    const cafe = idea("cafe", { lat: 10.012, lng: 20.0 });
    const detail = detailOf(cafe);
    const { days } = pickerDays(detail, cafe, null, nearOf(detail));
    expect(days.find((d) => d.iso === "2026-11-11")?.label).toBe("Market day");
    expect(days.find((d) => d.iso === "2026-11-12")?.label).toBe("Free day");
  });

  it("puts each day's circle at the middle of its places", () => {
    const both = pinned("both", "2026-11-10", 10.02, 20.0);
    const zones = dayZones({ trip, bookings: [day1, both, day2, day5, idea("ignored", { lat: 5, lng: 5 })] } as unknown as Parameters<typeof dayZones>[0], new Map());
    expect([...zones.keys()]).toEqual(["2026-11-10", "2026-11-11", "2026-11-14"]);
    expect(zones.get("2026-11-10")).toMatchObject({ lat: 10.01, lng: 20.0 });
    // Two places 2.2 km apart: 1.1 km out each way, a little wider; one place: the least.
    expect(zones.get("2026-11-10")!.radius).toBeGreaterThan(1100);
    expect(zones.get("2026-11-11")!.radius).toBe(400);
  });

  it("says what a row fits: on a day, near one, or a free day", () => {
    const near = idea("near", { lat: 10.012, lng: 20.0 });
    const far = idea("far", { lat: 10.5, lng: 20.0 });
    const detail = detailOf(near, far);
    const around = nearOf(detail);
    expect(ideaHint(detail, near, around)).toBe("Near Day 2 · 220 m");
    // 55 km from anything: no day is near, so the stop's empty day.
    expect(ideaHint(detail, far, around)).toBe("Fits free Day 3");
    expect(ideaHint(detail, day2, around)).toBe("On Day 2");
  });
});

describe("idea list colours", () => {
  it("go by sorted name, so a list keeps its colour", () => {
    const colors = listColors(["Sights", "Food", "Food", "Cafes"]);
    expect([...colors.keys()]).toEqual(["Cafes", "Food", "Sights"]);
    expect(new Set(colors.values()).size).toBe(3);
  });

  it("repeat after the palette runs out", () => {
    const colors = listColors(["a", "b", "c", "d", "e"]);
    expect(colors.get("e")).toBe(colors.get("a"));
  });
});
