import { describe, expect, it } from "vitest";

import { distance, metresBetween } from "./geo";

// Made-up points, a degree of latitude apart on the equator and beside the poles.
describe("metresBetween", () => {
  it("is zero for the same point", () => {
    expect(metresBetween({ lat: 10, lng: 20 }, { lat: 10, lng: 20 })).toBe(0);
  });

  it("measures a degree of latitude as about 111.2 km", () => {
    expect(metresBetween({ lat: 0, lng: 0 }, { lat: 1, lng: 0 })).toBeCloseTo(111195, -1);
  });

  it("shrinks a degree of longitude with the latitude", () => {
    const equator = metresBetween({ lat: 0, lng: 0 }, { lat: 0, lng: 1 });
    const north = metresBetween({ lat: 60, lng: 0 }, { lat: 60, lng: 1 });
    expect(equator).toBeCloseTo(111195, -1);
    expect(north / equator).toBeCloseTo(0.5, 2);
  });

  it("is the same either way round, and crosses the date line the short way", () => {
    const a = { lat: 12.5, lng: 179.5 };
    const b = { lat: 12.5, lng: -179.5 };
    expect(metresBetween(a, b)).toBeCloseTo(metresBetween(b, a), 6);
    expect(metresBetween(a, b)).toBeLessThan(120000);
  });

  it("goes half way round the world between opposite points", () => {
    expect(metresBetween({ lat: 0, lng: 0 }, { lat: 0, lng: 180 })).toBeCloseTo(Math.PI * 6371000, -1);
  });
});

describe("distance", () => {
  it("says metres to the nearest ten, then kilometres", () => {
    expect(distance(344)).toBe("340 m");
    expect(distance(1234)).toBe("1.2 km");
  });
});
