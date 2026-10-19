import { describe, expect, it } from "vitest";

import { tripInviteIn } from "./telegram";

describe("the trip invite in an address", () => {
  it("is the token of a trip invite link", () => {
    expect(tripInviteIn("/trip-invite/abc_DEF-123")).toBe("abc_DEF-123");
    expect(tripInviteIn("/trip-invite/a%20b")).toBe("a b");
  });

  it("is nothing for any other address", () => {
    for (const path of ["/", "/travel", "/invite/abc", "/trip-invite/", "/trip-invite", "/x/trip-invite/abc"]) {
      expect(tripInviteIn(path)).toBeNull();
    }
    expect(tripInviteIn("/trip-invite/%E0%A4%A")).toBeNull(); // not valid percent-encoding
  });
});
