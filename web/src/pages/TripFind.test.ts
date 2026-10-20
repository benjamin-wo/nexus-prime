import { describe, expect, it } from "vitest";

import type { Idea, Place, TripStop } from "../api";
import { findScopes, firstScope, listFor, mergeResults, normName, scopeParams, THEMES, whereCaption } from "./TripFind";
import { wantsIdeas } from "./TripPlaces";

// Made-up places and guides.
const place = (id: string, name: string, extra: Partial<Place> = {}): Place =>
  ({ id, name, address: `${name} street`, kind: "Noodle shop", rating: "4.6", ratings: 120, price: null, ...extra }) as Place;
const idea = (name: string, extra: Partial<Idea> = {}): Idea => ({
  name, area: null, kind: "Food", why: `${name} is worth it.`, source: { url: `https://guide.example.com/${name}`, title: "A guide" }, place: null, ...extra,
});

describe("merging Google Maps results with guide ideas", () => {
  it("lists Google first, then guide-only ideas", () => {
    const merged = mergeResults([place("g1", "Hanok Noodle Bar")], [idea("Lantern Alley", { kind: "Nightlife" })]);
    expect(merged.map((m) => m.name)).toEqual(["Hanok Noodle Bar", "Lantern Alley"]);
    expect(merged.map((m) => m.from)).toEqual([["google"], ["guides"]]);
  });

  it("merges an idea matched to the same Google place, keeping rating, why and source", () => {
    const p = place("g1", "Hanok Noodle Bar");
    const [card, ...rest] = mergeResults([p], [idea("The Hanok Noodle Bar", { place: p, area: "Jung-gu" })]);
    expect(rest).toEqual([]);
    expect(card.place?.rating).toBe("4.6");
    expect(card.why).toBe("The Hanok Noodle Bar is worth it.");
    expect(card.source?.title).toBe("A guide");
    expect(card.area).toBe("Jung-gu");
    expect(card.from).toEqual(["google", "guides"]);
  });

  it("merges by name, ignoring case, accents and punctuation, when the idea has no place", () => {
    const merged = mergeResults([place("g1", "Café Lumière")], [idea("cafe  lumiere!")]);
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({ why: "cafe  lumiere! is worth it.", from: ["google", "guides"], place: { id: "g1" } });
  });

  it("adds a Google match to a guide card that had none, and joins one idea told twice", () => {
    const p = place("g9", "Old Temple", { kind: "Temple" });
    const merged = mergeResults([], [idea("Old Temple", { kind: "Sights" }), idea("old temple", { place: p, why: "Second telling." })]);
    expect(merged).toHaveLength(1);
    expect(merged[0].place?.id).toBe("g9");
    expect(merged[0].why).toBe("Old Temple is worth it.");
    expect(merged[0].listKind).toBe("Sights");
  });

  it("shows a place Google lists twice once, and keeps different places apart", () => {
    const merged = mergeResults([place("g1", "Tea House"), place("g1", "Tea House"), place("g2", "Tea House Annex")], []);
    expect(merged.map((m) => m.key)).toEqual(["g1", "g2"]);
  });

  it("keeps a guide idea's own Google match as its card", () => {
    const p = place("g3", "Night Market", { area: "Euljiro" });
    const [card] = mergeResults([], [idea("Night Market", { place: p })]);
    expect(card).toMatchObject({ key: "g3", area: "Euljiro", from: ["guides"] });
    expect(card.place?.rating).toBe("4.6");
  });

  it("normalises names for comparing", () => {
    expect(normName("  Café-Lumière, No. 2 ")).toBe("cafelumiereno2");
  });
});

describe("what a saved result is filed under", () => {
  it("is the theme searched, else the guide's kind, else Google's", () => {
    const [both] = mergeResults([place("g1", "Hanok Noodle Bar")], [idea("Hanok Noodle Bar")]);
    expect(listFor(both, "Rainy day")).toBe("Rainy day");
    expect(listFor(both, null)).toBe("Food");
    const [google] = mergeResults([place("g2", "Tea House")], []);
    expect(listFor(google, null)).toBe("Noodle shop");
  });
});

const tokyo: TripStop = { name: "Tokyo", start: "2027-04-02", end: "2027-04-04" };
const kyoto: TripStop = { name: "Kyoto", start: "2027-04-05", end: "2027-04-08" };
const trip = { start: "2027-04-02", end: "2027-04-08" };

describe("where a search can look", () => {
  it("offers the whole trip, each stop once there are two, and the day with its name", () => {
    const scopes = findScopes({ stops: [tokyo, kyoto], ...trip, day: "2027-04-06", labels: new Map([["2027-04-06", "Gion"]]) });
    expect(scopes.map((s) => s.label)).toEqual(["Whole trip", "In Tokyo", "In Kyoto", "Near Day 5 · Gion"]);
    expect(findScopes({ stops: [tokyo], ...trip, day: "2027-04-03" }).map((s) => s.label)).toEqual(["Whole trip", "Near Day 2"]);
    expect(findScopes({ stops: [], ...trip }).map((s) => s.label)).toEqual(["Whole trip"]);
  });

  it("leaves out a day that isn't in the trip", () => {
    expect(findScopes({ stops: [], ...trip, day: "2027-04-09" })).toHaveLength(1);
    expect(findScopes({ stops: [], ...trip, day: "2027-04-01" })).toHaveLength(1);
  });

  it("sends a stop's name or a day, never both", () => {
    const scopes = findScopes({ stops: [tokyo, kyoto], ...trip, day: "2027-04-06" });
    expect(scopes.map(scopeParams)).toEqual([{}, { stop: "Tokyo" }, { stop: "Kyoto" }, { day: "2027-04-06" }]);
    expect(scopeParams(null)).toEqual({});
  });

  it("begins near the day it was opened from, else the viewed day's stop, else the whole trip", () => {
    const stops = [tokyo, kyoto];
    const scopes = findScopes({ stops, ...trip, day: "2027-04-06" });
    expect(firstScope(scopes, { near: "2027-04-06", viewing: "2027-04-03", stops })).toBe("day:2027-04-06");
    expect(firstScope(scopes, { viewing: "2027-04-06", stops })).toBe("stop:Kyoto");
    expect(firstScope(scopes, { viewing: null, stops })).toBe("trip");
    // One stop is the whole trip anyway.
    expect(firstScope(findScopes({ stops: [tokyo], ...trip }), { viewing: "2027-04-03", stops: [tokyo] })).toBe("trip");
  });
});

describe("theme chips", () => {
  it("are the seven themes, each an idea-ish query so guides are read too", () => {
    expect(THEMES.map((t) => t.label)).toEqual(["Food", "Sights", "Museums", "Nature", "Shopping", "Nightlife", "Rainy day"]);
    for (const t of THEMES) expect(wantsIdeas(t.query)).toBe(true);
  });
});

describe("the line saying where a search looks", () => {
  const scopes = findScopes({ stops: [tokyo, kyoto, { name: "Osaka", start: "2027-04-09", end: "2027-04-10" }], start: "2027-04-02", end: "2027-04-10", day: "2027-04-06" });
  const caption = (key: string, withIdeas = false) =>
    whereCaption({ scope: scopes.find((s) => s.key === key) ?? null, scopes, destination: "Japan", withIdeas });

  it("names every stop for the whole trip, one stop for a stop, and the day's plans for a day", () => {
    expect(caption("trip")).toBe("Across Tokyo, Kyoto and Osaka.");
    expect(caption("stop:Kyoto")).toBe("In Kyoto.");
    expect(caption("day:2027-04-06")).toBe("Within about 2 km of Day 5's plans.");
  });

  it("adds that guides are read too only when ideas are on", () => {
    expect(caption("trip", true)).toBe("Across Tokyo, Kyoto and Osaka. Google and guides together.");
  });

  it("falls back to the destination when the trip has no stops", () => {
    const one = findScopes({ stops: [], ...trip });
    expect(whereCaption({ scope: one[0], scopes: one, destination: "Seoul", withIdeas: false })).toBe("Near Seoul.");
  });
});
