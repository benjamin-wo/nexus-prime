import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Booking, TripDetail } from "../api";
import { nearbyOf } from "./TripArrange";
import { IdeasMap } from "./TripIdeasMap";
import { renderWithProviders } from "../testing";

// A stand-in for Google's script: it records what the page draws and lets a test press the map.
type Handler = (e: { latLng?: { lat(): number; lng(): number } }) => void;
const fake = vi.hoisted(() => ({ on: {} as Record<string, Handler[]>, markers: [] as { o: Record<string, unknown>; click?: () => void }[], circles: [] as Record<string, unknown>[] }));
vi.mock("../maps", () => ({
  onMapsAuthFailure: () => () => undefined,
  loadMaps: async () => ({
    circle: 0,
    Map: class {
      addListener(e: string, f: Handler) { (fake.on[e] ??= []).push(f); }
      fitBounds() {} setCenter() {} setZoom() {} panTo() {}
    },
    Marker: class {
      o: Record<string, unknown>; click?: () => void;
      constructor(o: Record<string, unknown>) { this.o = o; fake.markers.push(this); }
      addListener(_: string, f: () => void) { this.click = f; }
      setMap() {}
    },
    Circle: class { constructor(o: Record<string, unknown>) { fake.circles.push(o); } setMap() {} },
    Polyline: class { setMap() {} },
    LatLngBounds: class { extend() {} },
  }),
}));

// Made-up trip and coordinates.
function entry(id: string, fields: Partial<Booking>): Booking {
  return {
    id, trip_id: "t1", kind: "activity", title: id, provider: null, starts: "2026-11-11", ends: null, segments: [],
    hotel: null, address: null, check_in: null, check_out: null, reference: null, booked_via: null, category: null,
    scheduled: true, cost: null, logged: false, manual: true, at: null, day: "2026-11-11", ...fields,
  } as Booking;
}
const planned = entry("walk", { title: "Harbour walk", lat: 10.0, lng: 20.0 });
const cafe = entry("cafe", { title: "Corner cafe", scheduled: false, day: null, starts: "2026-09-28", lat: 10.01, lng: 20.0 });
const hidden = entry("hidden", { title: "Secret garden", scheduled: false, day: null, starts: "2026-09-28" });
const detail = {
  trip: { id: "t1", destination: "Exampleton", start: "2026-11-10", end: "2026-11-12", day_labels: { "2026-11-11": "Harbour" }, stops: [] },
  suggested_stops: [], bookings: [planned, cafe, hidden], places_order: [], days: [],
} as unknown as TripDetail;

function show(over: { onPick?: (b: Booking) => void; onDrop?: (at: { lat: number; lng: number }, name: string) => Promise<void> } = {}) {
  const near = nearbyOf(detail, new Map());
  return renderWithProviders(
    <IdeasMap detail={detail} apiKey="k" ideas={[cafe, hidden]} color={() => "#123456"} near={near} viewing="2026-11-11" onPick={over.onPick ?? (() => undefined)} onDrop={over.onDrop ?? (async () => undefined)} />,
  );
}
const press = (lat: number, lng: number) => act(() => fake.on.mousedown.forEach((f) => f({ latLng: { lat: () => lat, lng: () => lng } })));

beforeEach(() => {
  fake.on = {};
  fake.markers = [];
  fake.circles = [];
});

describe("the ideas map", () => {
  it("pins each idea in its list's colour, rings the day and names it", async () => {
    show();
    await waitFor(() => expect(fake.markers.length).toBeGreaterThan(0));
    const pin = fake.markers.find((m) => m.o.title === "Corner cafe");
    expect(pin?.o.icon).toMatchObject({ fillColor: "#123456" });
    // The day the idea is near: ringed, named with its label, and highlighted as the one viewed.
    expect(fake.circles).toHaveLength(1);
    expect(fake.circles[0]).toMatchObject({ center: { lat: 10, lng: 20 }, strokeWeight: 3 });
    expect(fake.markers.some((m) => m.o.title === "Day 2 · Harbour")).toBe(true);
    // The idea with no place is listed, not pinned.
    expect(fake.markers.some((m) => m.o.title === "Secret garden")).toBe(false);
    expect(screen.getByText(/Not on the map: link a place to pin it\. Secret garden/)).toBeInTheDocument();
  });

  it("opens an idea's day picker when its pin is tapped", async () => {
    const picked: string[] = [];
    show({ onPick: (b) => picked.push(b.id) });
    await waitFor(() => expect(fake.markers.find((m) => m.o.title === "Corner cafe")).toBeTruthy());
    act(() => fake.markers.find((m) => m.o.title === "Corner cafe")!.click!());
    expect(picked).toEqual(["cafe"]);
  });

  it("asks for a name after a held press, then drops the pin there", async () => {
    const dropped: [unknown, string][] = [];
    show({ onDrop: async (at, name) => void dropped.push([at, name]) });
    await waitFor(() => expect(fake.on.mousedown).toBeTruthy());
    const user = userEvent.setup();
    press(10.123456789, 20.5);
    expect(screen.queryByRole("dialog")).toBeNull();
    const dialog = await screen.findByRole("dialog", { name: "Drop a pin here" }, { timeout: 1500 });
    expect(screen.getByLabelText("Name")).toHaveValue("Dropped pin");
    await user.click(screen.getByRole("button", { name: "Save pin" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(dropped).toEqual([[{ lat: 10.123457, lng: 20.5 }, "Dropped pin"]]);
  });

  it("drops nothing when the press is let go early", async () => {
    show();
    await waitFor(() => expect(fake.on.mousedown).toBeTruthy());
    press(10, 20);
    act(() => fake.on.mouseup.forEach((f) => f({})));
    await new Promise((r) => setTimeout(r, 700));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
