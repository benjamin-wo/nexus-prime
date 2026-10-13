import { describe, expect, it } from "vitest";

import { onlyNamesDay, repeatsTitle } from "./TripBits";

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
