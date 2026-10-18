import { describe, expect, it } from "vitest";

import { emptyDayText } from "./SharedTrip";

describe("what an empty day on the shared page says", () => {
  it("calls a day a hidden booking falls on a travel day", () => {
    expect(emptyDayText("2027-03-02", ["2027-03-02", "2027-03-09"])).toBe("Travel day");
  });

  it("keeps the plain wording for other days, and when nothing is hidden", () => {
    expect(emptyDayText("2027-03-03", ["2027-03-02"])).toBe("Nothing planned yet");
    expect(emptyDayText("2027-03-02", [])).toBe("Nothing planned yet");
  });
});
