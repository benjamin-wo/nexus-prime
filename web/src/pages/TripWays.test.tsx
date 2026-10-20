import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Trip, TripDetail, TripMember } from "../api";
import { mockApi } from "../testing";
import { TripPage } from "./Trips";

const me = (role: "owner" | "member") => ({ user: { telegram_user_id: 1, role, home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" });

// A made-up trip with only the fields the page reads.
const trip = (over: Partial<Trip> = {}): Trip =>
  ({
    id: "t1", destination: "Tokyo", start: "2027-04-02", end: "2027-04-05", days: 4, currency: "JPY", budget: null, companions: [], set_aside: null,
    planned: {}, status: "upcoming", days_until: 120, day_number: null, notes: null, day_labels: {}, stops: [], split_evenly: true,
    role: "owner", owner_name: "Ben", packing: [], ...over,
  }) as Trip;

const detail = (t: Trip, over: Partial<TripDetail> = {}): TripDetail =>
  ({
    trip: t, bookings: [], days: [], places_order: [], places: true, ideas: false, suggested_stops: [], routes: true, map_key: "k",
    booked: null, booked_unlogged: null, to_spend: null,
    ready: { nights_without_stay: [], has_transport: true, has_budget: false, done: 2, total: 3 },
    spending: null, saving: null, owed: [], to_split: [], just_mine: [], paid_by_others: [], balances: [], items: [], ...over,
  }) as unknown as TripDetail;

function renderTrip() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/travel/trips/t1"]}>
        <Routes>
          <Route path="/travel/trips/:id" element={<TripPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("getting around and directions", () => {
  it("is in the owner's trip menu, in a sheet with both pickers, and no longer under the itinerary", async () => {
    const calls = mockApi({
      "GET /me": () => me("owner"),
      "GET /travel/trips/t1": () => detail(trip({ getting_around: "transit" })),
      "GET /travel/trips/t1/members": () => [] as TripMember[],
      "GET /travel/trips/t1/activity": () => [],
      "PUT /travel/trips/t1/getting-around": () => ({}),
    });
    renderTrip();
    const itinerary = await screen.findByRole("region", { name: "Itinerary" });
    expect(within(itinerary).queryByLabelText("Getting around")).toBeNull();
    expect(within(itinerary).queryByLabelText("Directions open in")).toBeNull();
    expect(within(itinerary).getByText("Times are local.")).toBeInTheDocument();
    // Owners get no read-only line under the map: they have the menu.
    expect(screen.queryByText(/^Getting around:/)).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Trip options" }));
    await user.click(screen.getByRole("menuitem", { name: "Getting around and directions" }));
    const sheet = await screen.findByRole("dialog", { name: "Getting around and directions" });
    expect(within(sheet).getByLabelText("Directions open in")).toBeInTheDocument();
    await user.selectOptions(within(sheet).getByLabelText("Getting around"), "car");
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ by: "car" }));

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Getting around and directions" })).toBeNull();
  });

  it("is left out of the menu when the trip has no maps or routes", async () => {
    mockApi({
      "GET /me": () => me("owner"),
      "GET /travel/trips/t1": () => detail(trip(), { routes: false, places: false, map_key: null }),
      "GET /travel/trips/t1/members": () => [] as TripMember[],
      "GET /travel/trips/t1/activity": () => [],
    });
    renderTrip();
    await screen.findByRole("region", { name: "Itinerary" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Trip options" }));
    expect(screen.getByRole("menuitem", { name: "Edit trip" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Getting around and directions" })).toBeNull();
  });

  it("is one read-only line under the map for a member", async () => {
    mockApi({
      "GET /me": () => me("member"),
      "GET /travel/trips/t1": () => detail(trip({ role: "member", owner_name: "Alex T.", getting_around: "car" })),
      "GET /travel/trips/t1/members": () => [] as TripMember[],
      "GET /travel/trips/t1/activity": () => [],
    });
    renderTrip();
    const map = await screen.findByRole("region", { name: "Map" });
    expect(within(map).getByText("Getting around: hire car")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Trip options" })).toBeNull();
    expect(screen.queryByLabelText("Getting around")).toBeNull();
    expect(screen.queryByLabelText("Directions open in")).toBeNull();
  });

  it("says public transport when the trip hasn't picked", async () => {
    mockApi({
      "GET /me": () => me("member"),
      "GET /travel/trips/t1": () => detail(trip({ role: "member", owner_name: "Alex T." })),
      "GET /travel/trips/t1/members": () => [] as TripMember[],
      "GET /travel/trips/t1/activity": () => [],
    });
    renderTrip();
    expect(await screen.findByText("Getting around: public transport")).toBeInTheDocument();
  });
});
