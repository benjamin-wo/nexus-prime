import { describe, expect, it } from "vitest";

import { e1rm, formatClockSeconds, formatDuration, formatSet, formatVolume, formatWeight, trimDecimal } from "./format";

describe("health formatting", () => {
  it("trims a decimal string", () => {
    expect(trimDecimal("85.00")).toBe("85");
    expect(trimDecimal("82.50")).toBe("82.5");
    expect(trimDecimal("100")).toBe("100");
    expect(trimDecimal("abc")).toBe("abc");
  });
  it("writes a weight and a set", () => {
    expect(formatWeight("85.00", "kg")).toBe("85 kg");
    expect(formatWeight(null)).toBe("Bodyweight");
    expect(formatSet({ weight: "85.00", unit: "kg", reps: 5, seconds: null })).toBe("85 kg × 5");
    expect(formatSet({ weight: null, unit: "kg", reps: null, seconds: 45 })).toBe("45 s");
  });
  it("estimates a one-rep max like the server", () => {
    expect(e1rm(80, 1)).toBe(80);
    expect(e1rm(80, 5)).toBeCloseTo(93.33, 1);
    expect(e1rm(80, 13)).toBeNull();
    expect(e1rm(0, 5)).toBeNull();
  });
  it("writes durations, volumes and the clock", () => {
    expect(formatDuration(40)).toBe("40 s");
    expect(formatDuration(3120)).toBe("52 min");
    expect(formatDuration(3900)).toBe("1 h 05 min");
    expect(formatVolume("1240.00")).toBe("1,240 kg");
    expect(formatClockSeconds(90)).toBe("1:30");
    expect(formatClockSeconds(-3)).toBe("0:00");
  });
});
