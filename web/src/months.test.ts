import { describe, expect, it } from "vitest";

import { currentMonth, earliestMonth, monthLabel, monthName, monthRange, pickedMonth, shiftMonth } from "./months";

describe("shiftMonth", () => {
  it("steps across year ends in both directions", () => {
    expect(shiftMonth("2026-11", -1)).toBe("2026-10");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-11", -24)).toBe("2024-11");
  });
});

describe("monthRange", () => {
  it("is the first and the last day, whatever the month's length", () => {
    expect(monthRange("2026-10")).toEqual({ start: "2026-10-01", end: "2026-10-31" });
    expect(monthRange("2026-09")).toEqual({ start: "2026-09-01", end: "2026-09-30" });
    expect(monthRange("2026-02")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(monthRange("2028-02")).toEqual({ start: "2028-02-01", end: "2028-02-29" });
  });
});

describe("currentMonth", () => {
  it("is the month it is in the user's timezone", () => {
    const edge = new Date("2026-10-31T17:30:00Z");
    expect(currentMonth("UTC", edge)).toBe("2026-10");
    expect(currentMonth("Asia/Singapore", edge)).toBe("2026-11");
    expect(currentMonth("America/Los_Angeles", edge)).toBe("2026-10");
  });
});

describe("pickedMonth", () => {
  const now = "2026-11";

  it("takes a month up to this one, back as far as two years", () => {
    expect(pickedMonth("2026-10", now)).toBe("2026-10");
    expect(pickedMonth("2026-11", now)).toBe("2026-11");
    expect(pickedMonth(earliestMonth(now), now)).toBe("2024-11");
  });

  it("falls back to this month for a missing, malformed or impossible value", () => {
    for (const raw of [null, "", "october", "2026-1", "2026-13", "2026-00", "2026-10-01", "26-10"]) {
      expect(pickedMonth(raw, now)).toBe(now);
    }
  });

  it("falls back to this month for the future and for more than two years back", () => {
    expect(pickedMonth("2026-12", now)).toBe(now);
    expect(pickedMonth("2027-01", now)).toBe(now);
    expect(pickedMonth("2024-10", now)).toBe(now);
  });
});

describe("names", () => {
  it("writes a month in words", () => {
    expect(monthLabel("2026-10")).toMatch(/October.*2026|2026.*October/);
    expect(monthName("2026-09")).toBe("September");
  });
});
