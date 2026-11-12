import { describe, expect, it } from "vitest";

import { describeZone, filterZones, friendlyZone, shouldReportZone, sourceNote, zoneChoices, zoneOffset } from "./timezone";

const JULY = new Date("2026-07-01T12:00:00Z");
const JANUARY = new Date("2026-01-15T12:00:00Z");

describe("friendlyZone", () => {
  it("is the city of an IANA name", () => {
    expect(friendlyZone("Europe/Madrid")).toBe("Madrid");
    expect(friendlyZone("Asia/Singapore")).toBe("Singapore");
    expect(friendlyZone("America/New_York")).toBe("New York");
    expect(friendlyZone("America/Argentina/Buenos_Aires")).toBe("Buenos Aires");
    expect(friendlyZone("UTC")).toBe("UTC");
  });
});

describe("zoneOffset", () => {
  it("is the offset from UTC at that moment", () => {
    expect(zoneOffset("Europe/Madrid", JULY)).toBe("UTC+2");
    expect(zoneOffset("Europe/Madrid", JANUARY)).toBe("UTC+1");
    expect(zoneOffset("Asia/Singapore", JULY)).toBe("UTC+8");
    expect(zoneOffset("America/New_York", JANUARY)).toBe("UTC-5");
    expect(zoneOffset("UTC", JULY)).toBe("UTC");
  });

  it("keeps half and quarter hours", () => {
    expect(zoneOffset("Asia/Kolkata", JULY)).toBe("UTC+5:30");
    expect(zoneOffset("Asia/Kathmandu", JULY)).toBe("UTC+5:45");
  });

  it("is empty for a zone the browser doesn't know", () => {
    expect(zoneOffset("Mars/Olympus", JULY)).toBe("");
    expect(describeZone("Mars/Olympus", JULY)).toBe("Olympus");
  });
});

describe("describeZone", () => {
  it("joins the city and the offset", () => {
    expect(describeZone("Europe/Madrid", JULY)).toBe("Madrid · UTC+2");
    expect(describeZone("Asia/Singapore", JULY)).toBe("Singapore · UTC+8");
  });
});

describe("sourceNote", () => {
  it("says what put Nexus on the zone", () => {
    expect(sourceNote("phone")).toBe("from your phone");
    expect(sourceNote("chat")).toBe("you set it");
    expect(sourceNote("trip")).toBe("from your trip");
    expect(sourceNote("home")).toBe("home");
    expect(sourceNote(undefined)).toBe("home");
  });
});

describe("shouldReportZone", () => {
  const now = Date.parse("2026-10-24T12:00:00Z");
  const hoursAgo = (h: number) => new Date(now - h * 3600_000).toISOString();
  const state = (over: Record<string, unknown> = {}) => ({
    timezone: "Asia/Singapore",
    home_timezone: "Asia/Singapore",
    timezone_source: "home" as const,
    timezone_set_at: null,
    ...over,
  });

  it("reports a phone zone that differs", () => {
    expect(shouldReportZone("Europe/Madrid", state(), now)).toBe(true);
  });

  it("reports when the zone is the same but the server hasn't recorded the phone as the source", () => {
    expect(shouldReportZone("Asia/Singapore", state(), now)).toBe(true);
    expect(shouldReportZone("Asia/Singapore", state({ timezone_source: "trip" }), now)).toBe(true);
  });

  it("stays quiet when the phone is already the source and the zones match", () => {
    expect(shouldReportZone("Asia/Singapore", state({ timezone_source: "phone", timezone_set_at: hoursAgo(1) }), now)).toBe(false);
  });

  it("reports a new phone zone after the last report", () => {
    expect(shouldReportZone("Asia/Tokyo", state({ timezone_source: "phone", timezone_set_at: hoursAgo(1) }), now)).toBe(true);
  });

  it("reports nothing without a zone", () => {
    expect(shouldReportZone(null, state(), now)).toBe(false);
    expect(shouldReportZone(undefined, state(), now)).toBe(false);
    expect(shouldReportZone("", state(), now)).toBe(false);
    expect(shouldReportZone("   ", state(), now)).toBe(false);
  });

  it("leaves a zone the person set in the last 24 hours alone", () => {
    const chosen = state({ timezone: "Asia/Tokyo", timezone_source: "chat", timezone_set_at: hoursAgo(3) });
    expect(shouldReportZone("Europe/Madrid", chosen, now)).toBe(false);
    expect(shouldReportZone("Asia/Tokyo", chosen, now)).toBe(false);
    expect(shouldReportZone("Europe/Madrid", state({ timezone: "Asia/Tokyo", timezone_source: "chat", timezone_set_at: hoursAgo(23.9) }), now)).toBe(false);
  });

  it("lets the phone move a manual choice once 24 hours have passed", () => {
    expect(shouldReportZone("Europe/Madrid", state({ timezone: "Asia/Tokyo", timezone_source: "chat", timezone_set_at: hoursAgo(24) }), now)).toBe(true);
    expect(shouldReportZone("Europe/Madrid", state({ timezone: "Asia/Tokyo", timezone_source: "chat", timezone_set_at: hoursAgo(72) }), now)).toBe(true);
  });

  it("guards a manual choice only when it knows when it was made", () => {
    expect(shouldReportZone("Europe/Madrid", state({ timezone: "Asia/Tokyo", timezone_source: "chat", timezone_set_at: null }), now)).toBe(true);
  });

  it("does not guard a zone set by a trip", () => {
    expect(shouldReportZone("Europe/Madrid", state({ timezone: "Asia/Tokyo", timezone_source: "trip", timezone_set_at: hoursAgo(1) }), now)).toBe(true);
  });
});

describe("zone choices", () => {
  it("lists zones sorted by city and always includes the ones asked for", () => {
    const zones = zoneChoices(["Etc/Nowhere"]);
    expect(zones).toContain("Europe/Madrid");
    expect(zones).toContain("Etc/Nowhere");
    const cities = zones.map(friendlyZone);
    expect(cities).toEqual([...cities].sort((a, b) => a.localeCompare(b)));
  });

  it("filters by city, region or part of the name", () => {
    const zones = ["Europe/Madrid", "America/New_York", "Asia/Tokyo"];
    expect(filterZones(zones, "madr")).toEqual(["Europe/Madrid"]);
    expect(filterZones(zones, "new york")).toEqual(["America/New_York"]);
    expect(filterZones(zones, "asia")).toEqual(["Asia/Tokyo"]);
    expect(filterZones(zones, "  ")).toEqual(zones);
    expect(filterZones(zones, "zzz")).toEqual([]);
  });
});
