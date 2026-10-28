import { describe, expect, it } from "vitest";

import { costDayLabel, featureLabel, formatCount, formatTokens, formatUsd } from "./costs";

describe("formatUsd", () => {
  it("writes cents for ordinary amounts", () => {
    expect(formatUsd("0.4123")).toBe("US$0.41");
    expect(formatUsd("12.3456")).toBe("US$12.35");
    expect(formatUsd("18.20")).toBe("US$18.20");
    expect(formatUsd(3.1)).toBe("US$3.10");
  });

  it("always shows two decimals, with thousands separators", () => {
    expect(formatUsd("7")).toBe("US$7.00");
    expect(formatUsd("1234.5")).toBe("US$1,234.50");
  });

  it("shows four decimals under a cent", () => {
    expect(formatUsd("0.0042")).toBe("US$0.0042");
    expect(formatUsd("0.0001")).toBe("US$0.0001");
    expect(formatUsd("0.0099")).toBe("US$0.0099");
  });

  it("writes a cent as a cent and zero as zero", () => {
    expect(formatUsd("0.01")).toBe("US$0.01");
    expect(formatUsd("0")).toBe("US$0.00");
    expect(formatUsd("0.0000")).toBe("US$0.00");
  });

  it("does not show a bad figure as NaN", () => {
    expect(formatUsd("")).toBe("US$0.00");
    expect(formatUsd("oops")).toBe("US$0.00");
  });
});

describe("formatTokens and formatCount", () => {
  it("shortens token counts", () => {
    expect(formatTokens(950)).toBe("950");
    expect(formatTokens(220_000)).toBe("220k");
    expect(formatTokens(3_400_000)).toBe("3.4M");
    expect(formatTokens(12_000_000)).toBe("12M");
    expect(formatTokens(1_000)).toBe("1k");
  });

  it("separates thousands in call counts", () => {
    expect(formatCount(1200)).toBe("1,200");
    expect(formatCount(52)).toBe("52");
  });
});

describe("featureLabel", () => {
  it("gives friendly names to the known features", () => {
    expect(featureLabel("chat")).toBe("Chat");
    expect(featureLabel("voice")).toBe("Voice notes");
    expect(featureLabel("photo")).toBe("Photos");
    expect(featureLabel("memory.update")).toBe("Memory");
    expect(featureLabel("travel.photos")).toBe("Trip photos");
    expect(featureLabel("email.sweep")).toBe("Email sweep");
    expect(featureLabel("pdf")).toBe("PDFs");
    expect(featureLabel("department.step.travel.research")).toBe("Trip research");
    expect(featureLabel("unknown")).toBe("Other");
  });

  it("shows an unknown key as it is", () => {
    expect(featureLabel("brief.daily")).toBe("brief.daily");
    expect(featureLabel("toString")).toBe("toString");
    expect(featureLabel("")).toBe("");
  });
});

describe("costDayLabel", () => {
  it("names the day by the calendar", () => {
    expect(costDayLabel("2026-10-27")).toBe("Tue 27 Oct");
  });
});
