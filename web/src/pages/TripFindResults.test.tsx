import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Place } from "../api";
import { type Found, ResultList } from "./TripFind";

const found = (name: string, place: Partial<Place> | null): Found => ({
  key: name, name, area: "Gion", address: null, kind: null, listKind: null, price: null,
  place: place === null ? null : ({ id: name, name, rating: null, ratings: null, ...place } as Place),
  why: null, source: null, from: ["google"],
});

describe("a result's meta line", () => {
  it("starts with the rating when there is one, and with the area when there is none", () => {
    render(
      <ResultList
        results={[found("Rated Place", { rating: "4.6", ratings: 120 }), found("Unrated Place", {})]}
        label="Results"
        pickLabel="Save"
        busy={false}
        dayScope={null}
        onPick={() => undefined}
      />,
    );
    const [rated, unrated] = screen.getAllByRole("listitem");
    expect(rated).toHaveTextContent("Rated 4.6 (120) · Gion · Google Maps");
    expect(unrated).toHaveTextContent("Unrated PlaceGion · Google Maps");
  });
});
