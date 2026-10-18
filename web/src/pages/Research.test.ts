import { describe, expect, it } from "vitest";

import { addedText, changeText, clipDates, planStop, stopsWith } from "./Research";

// A made-up trip and made-up research dates.
const trip = { start: "2027-01-10", end: "2027-01-17" };

describe("clipDates", () => {
  it("keeps dates already inside the trip", () => {
    expect(clipDates("2027-01-12", "2027-01-14", trip)).toEqual({ start: "2027-01-12", end: "2027-01-14" });
  });
  it("cuts dates that run past either end", () => {
    expect(clipDates("2027-01-08", "2027-01-12", trip)).toEqual({ start: "2027-01-10", end: "2027-01-12" });
    expect(clipDates("2027-01-15", "2027-01-20", trip)).toEqual({ start: "2027-01-15", end: "2027-01-17" });
  });
  it("is null when none of the dates are in the trip", () => {
    expect(clipDates("2027-02-01", "2027-02-05", trip)).toBeNull();
    expect(clipDates("2026-12-01", "2027-01-09", trip)).toBeNull();
  });
  it("keeps a single shared day", () => {
    expect(clipDates("2027-01-17", "2027-01-20", trip)).toEqual({ start: "2027-01-17", end: "2027-01-17" });
  });
});

describe("planStop", () => {
  const whole = { name: "Tokyo", start: "2027-01-10", end: "2027-01-17" };
  const plan = (current: { name: string; start: string; end: string }[], dates: { start: string; end: string }) => planStop(current, " Osaka ", dates, trip);

  it("trims a whole-trip stop that the new stop reaches the end of", () => {
    const got = plan([whole], { start: "2027-01-14", end: "2027-01-25" });
    expect(got?.stops).toEqual([
      { name: "Tokyo", start: "2027-01-10", end: "2027-01-14" },
      { name: "Osaka", start: "2027-01-14", end: "2027-01-17" },
    ]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "ends", on: "2027-01-14" }]);
  });

  it("puts a stop at the trip end after the one before, sharing the travel day", () => {
    const current = [
      { name: "Tokyo", start: "2027-01-10", end: "2027-01-14" },
      { name: "Kyoto", start: "2027-01-14", end: "2027-01-17" },
    ];
    const got = plan(current, { start: "2027-01-16", end: "2027-01-17" });
    expect(got?.stops.map((x) => [x.name, x.start, x.end])).toEqual([
      ["Tokyo", "2027-01-10", "2027-01-14"],
      ["Kyoto", "2027-01-14", "2027-01-16"],
      ["Osaka", "2027-01-16", "2027-01-17"],
    ]);
  });

  it("trims the start of a stop that the new stop runs into from before", () => {
    const got = plan([whole], { start: "2027-01-08", end: "2027-01-12" });
    expect(got?.stops).toEqual([
      { name: "Osaka", start: "2027-01-10", end: "2027-01-12" },
      { name: "Tokyo", start: "2027-01-12", end: "2027-01-17" },
    ]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "starts", on: "2027-01-12" }]);
  });

  it("splits a stop around a new stop in the middle", () => {
    const got = plan([whole], { start: "2027-01-12", end: "2027-01-14" });
    expect(got?.stops).toEqual([
      { name: "Tokyo", start: "2027-01-10", end: "2027-01-12" },
      { name: "Osaka", start: "2027-01-12", end: "2027-01-14" },
      { name: "Tokyo", start: "2027-01-14", end: "2027-01-17" },
    ]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "splits", endsOn: "2027-01-12", startsOn: "2027-01-14" }]);
  });

  it("replaces a stop the new stop covers exactly, or lies inside", () => {
    const got = plan([whole], { start: "2027-01-10", end: "2027-01-17" });
    expect(got?.stops).toEqual([{ name: "Osaka", start: "2027-01-10", end: "2027-01-17" }]);
    expect(got?.changes).toEqual([{ name: "Tokyo", kind: "goes" }]);
    const inside = plan(
      [{ name: "Tokyo", start: "2027-01-10", end: "2027-01-12" }, { name: "Nara", start: "2027-01-12", end: "2027-01-13" }, { name: "Kyoto", start: "2027-01-13", end: "2027-01-17" }],
      { start: "2027-01-12", end: "2027-01-13" },
    );
    expect(inside?.stops.map((x) => x.name)).toEqual(["Tokyo", "Osaka", "Kyoto"]);
  });

  it("leaves stops alone that only share the travel day", () => {
    const current = [{ name: "Tokyo", start: "2027-01-10", end: "2027-01-14" }];
    const got = plan(current, { start: "2027-01-14", end: "2027-01-17" });
    expect(got?.changes).toEqual([]);
    expect(got?.stops[0]).toEqual(current[0]);
  });

  it("clips the new stop to the trip and does not change the stops it was given", () => {
    const current = [whole];
    const got = plan(current, { start: "2027-01-15", end: "2027-03-01" });
    expect(got?.stops[1]).toEqual({ name: "Osaka", start: "2027-01-15", end: "2027-01-17" });
    expect(current).toEqual([whole]);
  });

  it("is null when the dates don't fit the trip", () => {
    expect(plan([whole], { start: "2027-03-01", end: "2027-03-04" })).toBeNull();
  });

  it("is null when the result would break the stops rules", () => {
    // A one-day stop in the middle of a stop would start on the same day as the rest of it.
    expect(plan([whole], { start: "2027-01-12", end: "2027-01-12" })).toBeNull();
    // Eleven stops is one too many.
    const long = { start: "2027-01-01", end: "2027-01-31" };
    const iso = (d: number) => `2027-01-${String(d).padStart(2, "0")}`;
    const ten = Array.from({ length: 10 }, (_, n) => ({ name: `Stop ${n}`, start: iso(1 + n), end: iso(2 + n) }));
    expect(planStop(ten, "Osaka", { start: iso(20), end: iso(22) }, long)).toBeNull();
    expect(planStop(ten.slice(1), "Osaka", { start: iso(20), end: iso(22) }, long)?.stops).toHaveLength(10);
  });
});

describe("stopsWith", () => {
  it("is the stops of the plan, or null", () => {
    const tokyo = { name: "Tokyo", start: "2027-01-10", end: "2027-01-17" };
    expect(stopsWith([tokyo], "Osaka", { start: "2027-01-14", end: "2027-01-17" }, trip)?.map((x) => x.name)).toEqual(["Tokyo", "Osaka"]);
    expect(stopsWith([tokyo], "Osaka", { start: "2027-03-01", end: "2027-03-04" }, trip)).toBeNull();
  });
});

describe("changeText", () => {
  it("says what happens to a stop", () => {
    expect(changeText({ name: "Tokyo", kind: "goes" })).toBe("Tokyo would be replaced");
    expect(changeText({ name: "Tokyo", kind: "ends", on: "2027-01-14" })).toMatch(/^Tokyo would end on .*14/);
    expect(changeText({ name: "Tokyo", kind: "starts", on: "2027-01-14" })).toMatch(/^Tokyo would start on .*14/);
    expect(changeText({ name: "Tokyo", kind: "splits", endsOn: "2027-01-12", startsOn: "2027-01-14" })).toMatch(/end on .*12 and start again on .*14/);
  });
});

describe("addedText", () => {
  it("says how many were added and how many were already there", () => {
    expect(addedText({ added: 9, skipped: 2 }, "Japan in spring")).toBe("Added 9 ideas to Japan in spring (2 were already there)");
  });
  it("uses the singular and leaves out nothing skipped", () => {
    expect(addedText({ added: 1, skipped: 0 }, "Japan in spring")).toBe("Added 1 idea to Japan in spring");
    expect(addedText({ added: 0, skipped: 1 }, "Japan in spring")).toBe("Added 0 ideas to Japan in spring (1 was already there)");
  });
});
