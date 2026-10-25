import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Booking, Hop, Place, Trip, TripDetail, TripMember } from "../api";
import { mockApi } from "../testing";
import { TripPage } from "./Trips";

const me = { user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };

const trip = {
  id: "t1", destination: "Tokyo", start: "2027-04-02", end: "2027-04-05", days: 4, currency: "JPY", budget: null, companions: [], set_aside: null,
  planned: {}, status: "upcoming", days_until: 120, day_number: null, notes: null, day_labels: {}, stops: [], split_evenly: true,
  role: "owner", owner_name: "Ben", packing: [],
} as unknown as Trip;

const detail = (bookings: Booking[], over: Partial<TripDetail> = {}): TripDetail =>
  ({
    trip, bookings, days: [], places_order: [], places: true, ideas: false, suggested_stops: [], routes: true, map_key: "k",
    booked: null, booked_unlogged: null, to_spend: null,
    ready: { nights_without_stay: [], has_transport: true, has_budget: false, done: 2, total: 3 },
    spending: null, saving: null, owed: [], to_split: [], just_mine: [], paid_by_others: [], balances: [], items: [], ...over,
  }) as unknown as TripDetail;

// Made-up plans on the same day.
const plan = (id: string, title: string, at: string, over: Partial<Booking> = {}): Booking =>
  ({
    id, trip_id: "t1", kind: "activity", title, provider: null, starts: "2027-04-03", ends: null, segments: [], hotel: null, address: null,
    check_in: null, check_out: null, name: title, day: "2027-04-03", at, note: null, reference: null, booked_via: null, category: null,
    place_id: null, scheduled: true, cost: null, logged: false, manual: true, ...over,
  }) as unknown as Booking;

const flight = plan("f1", "Flight to Osaka", "18:00", {
  kind: "flight", name: null, segments: [{ number: "XX1", origin: "Tokyo", destination: "Osaka", departs: "2027-04-03T18:00", arrives: "2027-04-03T19:30" }],
});

const place = (id: string, name: string): Place =>
  ({ id, name, address: null, kind: "Park", rating: null, ratings: null, price: null, maps_url: null, website: null, phone: null, summary: null, status: null, hours: [], reviews: [] }) as Place;

const hop = (a: Booking, b: Booking): Hop =>
  ({ start_id: a.id, end_id: b.id, start: a.title, end: b.title, mode: "walk", minutes: 14, metres: 944, tight: false, directions: "https://maps.example/dir" }) as Hop;

function renderDay() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/travel/trips/t1?day=2027-04-03"]}>
        <Routes>
          <Route path="/travel/trips/:id" element={<TripPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const base = (d: () => TripDetail, extra: Record<string, (body: unknown) => unknown> = {}) => ({
  "GET /me": () => me,
  "GET /travel/trips/t1": d,
  "GET /travel/trips/t1/members": () => [] as TripMember[],
  "GET /travel/trips/t1/activity": () => [],
  "GET /travel/trips/t1/places": () => [],
  ...extra,
});

// The day's list items, in order.
const rowsOf = (inside: HTMLElement) => Array.from(inside.closest("ul")!.children) as HTMLElement[];

const hint = (title: string) => screen.queryByRole("button", { name: `Link a place for ${title}` });

describe("a plan with no place on the day's list", () => {
  it("says there is no travel time next to it, once, and not next to linked plans", async () => {
    const a = plan("a", "Senso-ji Temple", "09:00", { place_id: "pA" });
    const b = plan("b", "Ramen lunch", "12:00");
    const c = plan("c", "Ueno Park", "15:00", { place_id: "pC" });
    mockApi(base(() => detail([a, b, c]), { "GET /travel/trips/t1/days/2027-04-03/hops": () => [] }));
    renderDay();
    expect(await screen.findByRole("button", { name: "Link a place for Ramen lunch" })).toBeInTheDocument();
    expect(screen.getAllByText(/No travel time/)).toHaveLength(1);
    expect(hint("Senso-ji Temple")).toBeNull();
    expect(hint("Ueno Park")).toBeNull();
    // Right after it, between it and the plan that follows.
    const button = screen.getByRole("button", { name: "Link a place for Ramen lunch" });
    const rows = rowsOf(button);
    const at = rows.findIndex((li) => li.contains(button));
    expect(rows[at - 1]?.id).toBe("entry-b");
    expect(rows[at + 1]?.id).toBe("entry-c");
  });

  it("sits before the plan when it is the day's last", async () => {
    const a = plan("a", "Senso-ji Temple", "09:00", { place_id: "pA" });
    const b = plan("b", "Ramen dinner", "19:00");
    mockApi(base(() => detail([a, b]), { "GET /travel/trips/t1/days/2027-04-03/hops": () => [] }));
    renderDay();
    const button = await screen.findByRole("button", { name: "Link a place for Ramen dinner" });
    const rows = rowsOf(button);
    const at = rows.findIndex((li) => li.contains(button));
    expect(rows[at + 1]?.id).toBe("entry-b");
  });

  it("is left out for flights, for a lone plan, and where Google Maps is off", async () => {
    mockApi(base(() => detail([plan("a", "Senso-ji Temple", "09:00", { place_id: "pA" }), flight])));
    const first = renderDay();
    await screen.findByText("Flight to Osaka");
    expect(screen.queryByText(/No travel time/)).toBeNull();
    first.unmount();

    mockApi(base(() => detail([plan("b", "Ramen lunch", "12:00")])));
    const second = renderDay();
    await screen.findByText("Ramen lunch");
    expect(screen.queryByText(/No travel time/)).toBeNull();
    second.unmount();

    const a = plan("a", "Senso-ji Temple", "09:00", { place_id: "pA" });
    mockApi(base(() => detail([a, plan("b", "Ramen lunch", "12:00")], { places: false })));
    renderDay();
    await screen.findByText("Ramen lunch");
    expect(screen.queryByText(/No travel time/)).toBeNull();
  });

  it("opens the place finder, and linking refreshes the day's travel times", async () => {
    const a = plan("a", "Senso-ji Temple", "09:00", { place_id: "pA" });
    let b = plan("b", "Ueno Park", "12:00");
    const calls = mockApi(
      base(() => detail([a, b]), {
        "GET /travel/places/search": () => [place("pB", "Ueno Park")],
        "PUT /travel/bookings/b/place": (body) => {
          b = { ...b, place_id: (body as { place_id: string }).place_id };
          return b;
        },
        "GET /travel/trips/t1/days/2027-04-03/hops": () => (b.place_id ? [hop(a, b)] : []),
      }),
    );
    renderDay();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Link a place for Ueno Park" }));
    expect(await screen.findByRole("search", { name: "Search Google Maps" })).toBeInTheDocument();
    expect(screen.getByLabelText("Look for")).toHaveValue("Ueno Park");
    await user.click(screen.getByRole("button", { name: "Search", exact: true } as never));
    await user.click(await screen.findByRole("button", { name: "Link: Ueno Park" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ place_id: "pB" }));
    expect(await screen.findByRole("listitem", { name: "From Senso-ji Temple to Ueno Park" })).toHaveTextContent("14 min walk");
    expect(screen.queryByText(/No travel time/)).toBeNull();
  });
});
