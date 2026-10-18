import { describe, expect, it } from "vitest";

import type { Booking, LinkedPlace, TripDetail, TripStop } from "../api";
import { onlyNamesDay, repeatsTitle, stopColor, stopOfDay, stopsOf, suggestLabel } from "./TripBits";

// Made-up places and notes.
describe("lines that only repeat what's shown", () => {
  it("drops an address that is the plan's own name, allowing a one-letter slip", () => {
    expect(repeatsTitle("El Cellar", "Girona · Sa Tuna · El Celler")).toBe(true);
    expect(repeatsTitle("Hanok Noodle Bar", "Hanok Noodle Bar")).toBe(true);
    expect(repeatsTitle("Café Lumière", "Cafe Lumiere breakfast")).toBe(true);
    // A real address, or a different place, still shows.
    expect(repeatsTitle("12 Example-ro, Jung-gu", "Hanok Noodle Bar")).toBe(false);
    expect(repeatsTitle("El Born", "Girona · Sa Tuna · El Celler")).toBe(false);
    expect(repeatsTitle("Bar", "Car park tour")).toBe(false); // short words must match exactly
  });

  it("drops a note that only says which day it is", () => {
    expect(onlyNamesDay("Day 3")).toBe(true);
    expect(onlyNamesDay(" day 12. ")).toBe(true);
    expect(onlyNamesDay("Day 3: book ahead")).toBe(false);
    expect(onlyNamesDay("Window seat")).toBe(false);
  });
});

// Made-up places, with only the fields the label rules read.
const entry = (id: string, extra: Partial<Booking> = {}): Booking => ({ id, kind: "activity", category: null, ...extra }) as Booking;
const linkedPlace = (id: string, place: { area?: string | null; kind?: string | null }): [string, LinkedPlace] => [id, { booking_id: id, place, warning: null } as unknown as LinkedPlace];

describe("a suggested day label", () => {
  it("is the commonest area and the two commonest kinds", () => {
    const linked = new Map([
      linkedPlace("a", { area: "Gion", kind: "Buddhist temple" }),
      linkedPlace("b", { area: "Gion", kind: "Ramen restaurant" }),
      linkedPlace("c", { area: "Pontocho", kind: "Ramen restaurant" }),
      linkedPlace("d", { area: "Gion", kind: "Museum" }),
    ]);
    const entries = ["a", "b", "c", "d"].map((id) => entry(id));
    // Food leads on two places; temples and museums tie on one, so the first seen follows.
    expect(suggestLabel(entries, linked)).toBe("Gion · food & temples");
  });

  it("goes by the first seen when the areas tie", () => {
    const linked = new Map([linkedPlace("a", { area: "Arashiyama" }), linkedPlace("b", { area: "Gion" })]);
    expect(suggestLabel([entry("a"), entry("b")], linked)).toBe("Arashiyama");
  });

  it("is only the area, or only the kinds, when that is all there is", () => {
    const linked = new Map([linkedPlace("a", { area: "Gion", kind: "Observation deck" })]);
    expect(suggestLabel([entry("a")], linked)).toBe("Gion");
    const noArea = new Map([linkedPlace("a", { kind: "Shrine" }), linkedPlace("b", { kind: "Japanese restaurant" })]);
    expect(suggestLabel([entry("a"), entry("b")], noArea)).toBe("temples & food");
  });

  it("falls back to the plan's category when the place has no kind", () => {
    const linked = new Map([linkedPlace("a", { area: "Higashiyama" })]);
    expect(suggestLabel([entry("a", { category: "Café" })], linked)).toBe("Higashiyama · food");
    expect(suggestLabel([entry("a", { category: "Art gallery" })], new Map())).toBe("museums");
  });

  it("maps the kind words and drops those it doesn't know", () => {
    const kinds: [string, string | null][] = [
      ["Shopping mall", "shopping"],
      ["Cocktail bar", "nightlife"],
      ["Public garden", "nature"],
      ["Night club", "nightlife"],
      ["Barbecue", null],
      ["Observation deck", null],
    ];
    for (const [kind, word] of kinds) expect(suggestLabel([entry("a")], new Map([linkedPlace("a", { kind })]))).toBe(word);
  });

  it("counts only plans for kinds, though a hotel's area still counts", () => {
    const linked = new Map([linkedPlace("h", { area: "Gion", kind: "Restaurant" }), linkedPlace("a", { kind: "Museum" })]);
    expect(suggestLabel([entry("h", { kind: "hotel" }), entry("a")], linked)).toBe("Gion · museums");
  });

  it("is null when nothing says", () => {
    expect(suggestLabel([], new Map())).toBeNull();
    expect(suggestLabel([entry("a")], new Map())).toBeNull();
  });
});

describe("the trip's stops", () => {
  const tokyo: TripStop = { name: "Tokyo", start: "2027-04-02", end: "2027-04-05" };
  const kyoto: TripStop = { name: "Kyoto", start: "2027-04-05", end: "2027-04-08" };
  const detail = (saved: TripStop[], suggested: TripStop[]) => ({ trip: { stops: saved }, suggested_stops: suggested }) as unknown as TripDetail;

  it("are the saved ones, else the suggested", () => {
    const mine = [{ name: "Osaka", start: "2027-04-02", end: "2027-04-08" }];
    expect(stopsOf(detail(mine, [tokyo, kyoto]))).toEqual(mine);
    expect(stopsOf(detail([], [tokyo, kyoto]))).toEqual([tokyo, kyoto]);
    expect(stopsOf({ trip: {} } as unknown as TripDetail)).toEqual([]);
  });

  it("name the stop a day is in, and on a travel day the one that starts", () => {
    const stops = [tokyo, kyoto];
    expect(stopOfDay(stops, "2027-04-02")).toBe(tokyo);
    expect(stopOfDay(stops, "2027-04-04")).toBe(tokyo);
    expect(stopOfDay(stops, "2027-04-05")).toBe(kyoto);
    expect(stopOfDay(stops, "2027-04-08")).toBe(kyoto);
  });

  it("are null for a day outside them all", () => {
    expect(stopOfDay([tokyo, kyoto], "2027-04-01")).toBeNull();
    expect(stopOfDay([tokyo, kyoto], "2027-04-09")).toBeNull();
    expect(stopOfDay([], "2027-04-03")).toBeNull();
  });

  it("have a colour each by order, repeating after the palette", () => {
    expect(stopColor(0)).not.toBe(stopColor(1));
    expect(stopColor(4)).toBe(stopColor(0));
  });
});
